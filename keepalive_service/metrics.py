from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from keepalive_service.config import AppConfig
from keepalive_service.generators import CPUGenerator, DiskGenerator, MemoryGenerator, NetworkGenerator
from keepalive_service.models import ResourceSample, Snapshot


class SmoothedValue:
    def __init__(self, alpha: float):
        self._alpha = alpha
        self._value: float | None = None

    def update(self, value: float) -> float:
        if self._value is None:
            self._value = value
        else:
            self._value = (self._alpha * value) + ((1.0 - self._alpha) * self._value)
        return self._value


@dataclass
class CapacityInfo:
    disk_mib_per_second: float
    network_mbit: float
    network_interface: str | None

    @property
    def network_bytes_per_second(self) -> float:
        return self.network_mbit * 125000.0


class CapacityResolver:
    def __init__(self, config: AppConfig, logger):
        self._config = config
        self._log = logger

    def resolve(self) -> CapacityInfo:
        disk_capacity = 1.0
        if self._config.disk.enabled:
            disk_capacity = self._config.disk_capacity_mib_per_second or self._benchmark_disk_capacity()

        network_interface = None
        network_mbit = 1.0
        if self._config.network.enabled:
            network_interface, network_mbit = self._resolve_network_capacity()
        return CapacityInfo(
            disk_mib_per_second=disk_capacity,
            network_mbit=network_mbit,
            network_interface=network_interface,
        )

    def _benchmark_disk_capacity(self) -> float:
        self._config.work_dir.mkdir(parents=True, exist_ok=True)
        sample_size_bytes = self._config.disk_calibration_mib * 1024 * 1024
        chunk_size = self._config.disk_chunk_kib * 1024
        path = self._config.work_dir / "disk-calibration.bin"
        payload = b"\0" * chunk_size

        start = time.monotonic()
        written = 0
        with open(path, "wb", buffering=0) as handle:
            while written < sample_size_bytes:
                handle.write(payload)
                written += chunk_size
            os.fsync(handle.fileno())
        elapsed = max(0.001, time.monotonic() - start)
        capacity = max(1.0, (written / 1024 / 1024) / elapsed)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self._log.info("disk capacity auto-calibrated at %.1f MiB/s", capacity)
        return capacity

    def _resolve_network_capacity(self) -> tuple[str | None, float]:
        if self._config.network_capacity_mbit:
            return self._config.network_interface, self._config.network_capacity_mbit

        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)

        interface = self._config.network_interface
        if interface:
            speed = stats.get(interface).speed if interface in stats else 0
            if speed > 0:
                return interface, float(speed)
            self._log.warning(
                "network interface %s did not report link speed, falling back to 1000 Mbit",
                interface,
            )
            return interface, 1000.0

        best_name: str | None = None
        best_score = -1.0
        for name, stat in stats.items():
            if not stat.isup or stat.speed <= 0:
                continue
            counter = counters.get(name)
            score = float(stat.speed)
            if counter is not None:
                score += (counter.bytes_recv + counter.bytes_sent) / 1_000_000_000.0
            if score > best_score:
                best_name = name
                best_score = score

        if best_name is None:
            self._log.warning("no network interface reported link speed, falling back to 1000 Mbit")
            return None, 1000.0

        return best_name, float(stats[best_name].speed)


class MetricsSampler:
    def __init__(
        self,
        config: AppConfig,
        capacity: CapacityInfo,
        cpu: CPUGenerator,
        memory: MemoryGenerator,
        disk: DiskGenerator,
        network: NetworkGenerator,
    ):
        self._config = config
        self._capacity = capacity
        self._cpu = cpu
        self._memory = memory
        self._disk = disk
        self._network = network
        self._last_disk = psutil.disk_io_counters(nowrap=True)
        self._last_net = self._read_network_counters()
        self._last_time = time.monotonic()
        self._cpu_smoother = SmoothedValue(config.ema_alpha)
        self._memory_smoother = SmoothedValue(config.ema_alpha)
        self._disk_smoother = SmoothedValue(config.ema_alpha)
        self._network_smoother = SmoothedValue(config.ema_alpha)
        psutil.cpu_percent(interval=None)

    def sample(self) -> Snapshot:
        now = time.monotonic()
        elapsed = max(0.001, now - self._last_time)
        self._last_time = now

        total_cpu = self._cpu_smoother.update(psutil.cpu_percent(interval=None))
        memory_info = psutil.virtual_memory()
        total_memory = self._memory_smoother.update(memory_info.percent)
        synthetic_memory = self._memory.synthetic_percent(memory_info.total) if self._config.memory.enabled else 0.0

        if self._config.disk.enabled:
            total_disk = self._disk_smoother.update(self._read_disk_percent(elapsed))
            synthetic_disk = (
                (self._disk.record_and_reset_bytes() / 1024 / 1024) / elapsed / self._capacity.disk_mib_per_second
            ) * 100.0
        else:
            total_disk = 0.0
            synthetic_disk = 0.0

        if self._config.network.enabled:
            total_network = self._network_smoother.update(self._read_network_percent(elapsed))
            synthetic_network = (
                (self._network.record_and_reset_bytes() / elapsed) / self._capacity.network_bytes_per_second
            ) * 100.0
        else:
            total_network = 0.0
            synthetic_network = 0.0

        synthetic_cpu = self._cpu.estimate_percent(elapsed) if self._config.cpu.enabled else 0.0

        return Snapshot(
            cpu=self._build_sample(total_cpu, synthetic_cpu),
            memory=self._build_sample(total_memory, synthetic_memory),
            disk=self._build_sample(total_disk, synthetic_disk),
            network=self._build_sample(total_network, synthetic_network),
        )

    def write_heartbeat(
        self,
        path: Path,
        started_at: int,
        paused: bool,
        reason: str | None,
        snapshot: Snapshot,
        targets: dict[str, float],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "started_at": started_at,
            "timestamp": int(time.time()),
            "paused": paused,
            "reason": reason,
            "targets": targets,
            "controllers": {
                "cpu": self._config.cpu.enabled,
                "memory": self._config.memory.enabled,
                "disk": self._config.disk.enabled,
                "network": self._config.network.enabled,
            },
            "cpu": snapshot.cpu.__dict__,
            "memory": snapshot.memory.__dict__,
            "disk": snapshot.disk.__dict__,
            "network": snapshot.network.__dict__,
        }
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def _read_disk_percent(self, elapsed: float) -> float:
        current = psutil.disk_io_counters(nowrap=True)
        previous = self._last_disk
        self._last_disk = current
        if current is None or previous is None:
            return 0.0
        delta_bytes = (current.read_bytes - previous.read_bytes) + (current.write_bytes - previous.write_bytes)
        mib_per_second = (delta_bytes / 1024 / 1024) / elapsed
        return min(100.0, (mib_per_second / self._capacity.disk_mib_per_second) * 100.0)

    def _read_network_percent(self, elapsed: float) -> float:
        current = self._read_network_counters()
        previous = self._last_net
        self._last_net = current
        delta_bytes = max(0, current - previous)
        return min(100.0, ((delta_bytes / elapsed) / self._capacity.network_bytes_per_second) * 100.0)

    def _read_network_counters(self) -> int:
        if self._capacity.network_interface:
            counters = psutil.net_io_counters(pernic=True)
            nic = counters.get(self._capacity.network_interface)
            if nic is not None:
                return nic.bytes_sent + nic.bytes_recv
        total = psutil.net_io_counters()
        return total.bytes_sent + total.bytes_recv

    @staticmethod
    def _build_sample(total_percent: float, synthetic_percent: float) -> ResourceSample:
        synthetic = max(0.0, min(total_percent, synthetic_percent))
        return ResourceSample(
            total_percent=max(0.0, total_percent),
            synthetic_percent=synthetic,
            real_percent=max(0.0, total_percent - synthetic),
        )
