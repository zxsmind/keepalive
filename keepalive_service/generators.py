from __future__ import annotations

import gc
import mmap
import os
import subprocess
import threading
import time
import urllib.request
from typing import Optional

import psutil

from keepalive_service.config import AppConfig


class CPUGenerator:
    def __init__(self, cpu_cores: int, logger, reconfigure_grace_seconds: float):
        self._cpu_cores = cpu_cores
        self._log = logger
        self._reconfigure_grace_seconds = reconfigure_grace_seconds
        self._process: Optional[subprocess.Popen] = None
        self._active_target = 0
        self._previous_cpu_seconds: dict[int, float] = {}
        self._last_spawn_time = 0.0
        self._lock = threading.Lock()

    def set_target(self, percent: float) -> None:
        target = int(round(percent))
        with self._lock:
            if target == self._active_target and self._process and self._process.poll() is None:
                return

            process_alive = self._process is not None and self._process.poll() is None
            if process_alive and target > 0 and self._active_target > 0:
                if abs(target - self._active_target) <= 1:
                    return

                age = time.monotonic() - self._last_spawn_time
                if age < self._reconfigure_grace_seconds:
                    return

            self._stop_locked()
            if target <= 0:
                return

            command = [
                "stress-ng",
                "--cpu",
                str(self._cpu_cores),
                "--cpu-load",
                str(target),
                "--cpu-method",
                "loop",
                "--quiet",
            ]

            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except OSError as exc:
                self._process = None
                self._active_target = 0
                self._log.error("failed to launch stress-ng: %s", exc)
                return

            time.sleep(0.5)
            if self._process.poll() is not None:
                error_output = ""
                if self._process.stderr is not None:
                    try:
                        error_output = self._process.stderr.read().strip()
                    except OSError:
                        error_output = ""
                self._log.error(
                    "stress-ng exited immediately with code %s%s",
                    self._process.returncode,
                    f": {error_output}" if error_output else "",
                )
                self._close_process_handles()
                self._process = None
                self._active_target = 0
                return

            self._active_target = target
            self._previous_cpu_seconds = {}
            self._last_spawn_time = time.monotonic()

    def estimate_percent(self, elapsed_seconds: float) -> float:
        with self._lock:
            if not self._process or self._process.poll() is not None:
                self._process = None
                self._active_target = 0
                self._previous_cpu_seconds = {}
                return 0.0

            try:
                root = psutil.Process(self._process.pid)
                processes = [root, *root.children(recursive=True)]
                current_cpu_seconds: dict[int, float] = {}
                for process in processes:
                    try:
                        cpu_times = process.cpu_times()
                        current_cpu_seconds[process.pid] = cpu_times.user + cpu_times.system
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                delta_cpu_seconds = 0.0
                for pid, cpu_seconds in current_cpu_seconds.items():
                    previous = self._previous_cpu_seconds.get(pid)
                    if previous is None:
                        continue
                    delta_cpu_seconds += max(0.0, cpu_seconds - previous)

                self._previous_cpu_seconds = current_cpu_seconds
                if not current_cpu_seconds:
                    return 0.0

                return max(0.0, (delta_cpu_seconds / max(elapsed_seconds, 0.001)) / self._cpu_cores * 100.0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._previous_cpu_seconds = {}
                return 0.0

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._close_process_handles()
        self._process = None
        self._active_target = 0
        self._previous_cpu_seconds = {}

    def _close_process_handles(self) -> None:
        if not self._process:
            return
        if self._process.stderr is not None:
            self._process.stderr.close()


class MemoryGenerator:
    def __init__(self, block_size_mib: int = 16):
        self._block_size = block_size_mib * 1024 * 1024
        self._buffers: list[mmap.mmap] = []
        self._reserved_bytes = 0
        self._lock = threading.Lock()

    def set_target_percent(self, percent: float, total_memory_bytes: int) -> None:
        target_bytes = int(total_memory_bytes * (percent / 100.0))
        with self._lock:
            while self._reserved_bytes < target_bytes:
                block = mmap.mmap(-1, self._block_size)
                for offset in range(0, self._block_size, 4096):
                    block[offset:offset + 1] = b"\0"
                self._buffers.append(block)
                self._reserved_bytes += self._block_size

            while self._reserved_bytes - self._block_size >= target_bytes and self._buffers:
                block = self._buffers.pop()
                block.close()
                self._reserved_bytes -= self._block_size

        if target_bytes == 0:
            gc.collect()

    def synthetic_percent(self, total_memory_bytes: int) -> float:
        if total_memory_bytes <= 0:
            return 0.0
        with self._lock:
            return (self._reserved_bytes / total_memory_bytes) * 100.0

    def stop(self) -> None:
        with self._lock:
            while self._buffers:
                self._buffers.pop().close()
            self._reserved_bytes = 0
        gc.collect()


class DiskGenerator:
    def __init__(self, config: AppConfig):
        self._config = config
        self._file_path = config.work_dir / "disk-worker.bin"
        self._bytes_written = 0
        self._target_percent = 0.0
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._lock = threading.Lock()
        self._offset = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="disk-generator")
        self._thread.start()

    def set_target(self, percent: float) -> None:
        with self._lock:
            self._target_percent = max(0.0, min(100.0, percent))
        self._wakeup.set()

    def record_and_reset_bytes(self) -> int:
        with self._lock:
            written = self._bytes_written
            self._bytes_written = 0
            return written

    def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        self._config.work_dir.mkdir(parents=True, exist_ok=True)
        chunk = b"\0" * (self._config.disk_chunk_kib * 1024)
        working_set_bytes = self._config.disk_working_set_mib * 1024 * 1024
        period_seconds = 1.0

        with open(self._file_path, "wb+") as handle:
            handle.truncate(working_set_bytes)
            while not self._stop.is_set():
                with self._lock:
                    target_percent = self._target_percent
                if target_percent <= 0:
                    self._wakeup.wait(timeout=period_seconds)
                    self._wakeup.clear()
                    continue

                cycle_start = time.monotonic()
                active_seconds = period_seconds * target_percent / 100.0
                active_until = cycle_start + active_seconds
                while time.monotonic() < active_until and not self._stop.is_set():
                    handle.seek(self._offset)
                    handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                    self._offset = (self._offset + len(chunk)) % working_set_bytes
                    with self._lock:
                        self._bytes_written += len(chunk)

                remaining = max(0.0, period_seconds - (time.monotonic() - cycle_start))
                if remaining > 0:
                    self._stop.wait(remaining)


class NetworkGenerator:
    def __init__(self, config: AppConfig, capacity_bytes_per_second: float):
        self._config = config
        self._capacity_bytes_per_second = capacity_bytes_per_second
        self._bytes_transferred = 0
        self._target_percent = 0.0
        self._endpoint_index = 0
        self._stop = threading.Event()
        self._wakeup = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True, name="network-generator")
        self._thread.start()

    def set_target(self, percent: float) -> None:
        with self._lock:
            self._target_percent = max(0.0, min(100.0, percent))
        self._wakeup.set()

    def record_and_reset_bytes(self) -> int:
        with self._lock:
            transferred = self._bytes_transferred
            self._bytes_transferred = 0
            return transferred

    def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        period_seconds = 5.0
        while not self._stop.is_set():
            with self._lock:
                target_percent = self._target_percent
            if target_percent <= 0:
                self._wakeup.wait(timeout=period_seconds)
                self._wakeup.clear()
                continue

            budget = int(self._capacity_bytes_per_second * (target_percent / 100.0) * period_seconds)
            budget = max(1024, budget)
            self._fetch_bytes(budget)
            self._stop.wait(period_seconds)

    def _fetch_bytes(self, budget: int) -> None:
        url = self._config.network_endpoints[self._endpoint_index % len(self._config.network_endpoints)]
        self._endpoint_index += 1
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "KeepAlive/1.0",
                "Range": f"bytes=0-{budget - 1}",
                "Cache-Control": "no-cache",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self._config.network_timeout_seconds) as response:
                remaining = budget
                while remaining > 0 and not self._stop.is_set():
                    chunk = response.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    with self._lock:
                        self._bytes_transferred += len(chunk)
        except Exception:
            return
