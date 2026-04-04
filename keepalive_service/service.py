from __future__ import annotations

import signal
import threading
import time

import psutil

from keepalive_service.config import AppConfig
from keepalive_service.control import IdleStateMachine, TargetPlanner
from keepalive_service.diagnostics import RuntimeDoctor
from keepalive_service.generators import (
    CPUGenerator,
    DiskGenerator,
    MemoryGenerator,
    NetworkGenerator,
    NullDiskGenerator,
    NullNetworkGenerator,
)
from keepalive_service.metrics import CapacityResolver, MetricsSampler


class KeepAliveService:
    def __init__(self, config: AppConfig, logger):
        self._config = config
        self._log = logger
        self._stop = threading.Event()
        self._started_at = int(time.time())
        self._cpu = CPUGenerator(
            config.cpu_cores,
            logger,
            reconfigure_grace_seconds=max(config.control_interval_seconds * 1.5, 10.0),
        )
        self._memory = MemoryGenerator()
        self._disk = DiskGenerator(config) if config.disk.enabled else NullDiskGenerator()
        capacity = CapacityResolver(config, logger).resolve()
        self._network = (
            NetworkGenerator(config, capacity.network_bytes_per_second)
            if config.network.enabled
            else NullNetworkGenerator()
        )
        self._sampler = MetricsSampler(config, capacity, self._cpu, self._memory, self._disk, self._network)
        self._state_machine = IdleStateMachine(config)
        self._planner = TargetPlanner(config)

    def run(self) -> int:
        self._config.work_dir.mkdir(parents=True, exist_ok=True)
        self._install_signal_handlers()
        self._run_diagnostics()
        self._log_startup()

        try:
            while not self._stop.is_set():
                snapshot = self._sampler.sample()
                state = self._state_machine.evaluate(snapshot)
                plan = self._planner.build(snapshot, state)

                memory_info = psutil.virtual_memory()
                self._cpu.set_target(plan.cpu_percent)
                self._memory.set_target_percent(
                    self._safe_memory_target_percent(plan.memory_percent, memory_info),
                    memory_info.total,
                )
                self._disk.set_target(plan.disk_percent)
                self._network.set_target(plan.network_percent)
                self._sampler.write_heartbeat(
                    self._config.heartbeat_file,
                    self._started_at,
                    state.paused,
                    state.pause_reason,
                    snapshot,
                    targets={
                        "cpu": plan.cpu_percent,
                        "memory": plan.memory_percent,
                        "disk": plan.disk_percent,
                        "network": plan.network_percent,
                    },
                )
                self._log_status(snapshot, state, plan)

                if self._stop.wait(self._config.control_interval_seconds):
                    break
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        self._cpu.stop()
        self._memory.stop()
        self._disk.stop()
        self._network.stop()

    def stop(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        def handle_signal(*_) -> None:
            self._log.info("shutdown requested")
            self.stop()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    def _log_startup(self) -> None:
        self._log.info("KeepAlive starting")
        self._log.info(
            "targets cpu=%.1f%% memory=%.1f%% disk=%.1f%% network=%.1f%%",
            self._config.cpu.target_percent,
            self._config.memory.target_percent,
            self._config.disk.target_percent,
            self._config.network.target_percent,
        )
        self._log.info(
            "controllers cpu=%s memory=%s disk=%s network=%s",
            "on" if self._config.cpu.enabled else "off",
            "on" if self._config.memory.enabled else "off",
            "on" if self._config.disk.enabled else "off",
            "on" if self._config.network.enabled else "off",
        )
        self._log.info(
            "idle pause=%.1f%% resume=%.1f%% after %d cycles",
            self._config.idle_pause_percent,
            self._config.idle_resume_percent,
            self._config.idle_resume_cycles,
        )
        self._log.info(
            "memory safety reserve cap=%.1f%% of currently available memory",
            self._config.memory_max_reserve_of_available_percent,
        )

    def _log_status(self, snapshot, state, plan) -> None:
        mode = "paused" if state.paused else "active"
        reason = f" reason={state.pause_reason}" if state.pause_reason else ""
        self._log.info(
            "mode=%s%s | cpu real=%4.1f total=%4.1f target=%4.1f | mem real=%4.1f total=%4.1f target=%4.1f | disk real=%4.1f total=%4.1f target=%4.1f | net real=%4.1f total=%4.1f target=%4.1f",
            mode,
            reason,
            snapshot.cpu.real_percent,
            snapshot.cpu.total_percent,
            plan.cpu_percent,
            snapshot.memory.real_percent,
            snapshot.memory.total_percent,
            plan.memory_percent,
            snapshot.disk.real_percent,
            snapshot.disk.total_percent,
            plan.disk_percent,
            snapshot.network.real_percent,
            snapshot.network.total_percent,
            plan.network_percent,
        )

    def _run_diagnostics(self) -> None:
        report = RuntimeDoctor(self._config).inspect()
        for warning in report.warnings:
            self._log.warning(warning)

    def _safe_memory_target_percent(self, requested_percent: float, memory_info) -> float:
        if requested_percent <= 0:
            return 0.0

        total_target_bytes = memory_info.total * (requested_percent / 100.0)
        available_limit_bytes = memory_info.available * (
            self._config.memory_max_reserve_of_available_percent / 100.0
        )
        safe_target_bytes = min(total_target_bytes, available_limit_bytes)
        return max(0.0, (safe_target_bytes / memory_info.total) * 100.0)
