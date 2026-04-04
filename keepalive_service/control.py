from __future__ import annotations

from dataclasses import dataclass

from keepalive_service.config import AppConfig
from keepalive_service.models import ServiceState, Snapshot


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


@dataclass
class TargetPlan:
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_percent: float


class IdleStateMachine:
    def __init__(self, config: AppConfig):
        self._config = config
        self._resume_streak = 0
        self._state = ServiceState(paused=False, pause_reason=None)

    @property
    def state(self) -> ServiceState:
        return self._state

    def evaluate(self, snapshot: Snapshot) -> ServiceState:
        pause_values: dict[str, float] = {}
        if self._config.cpu.enabled:
            pause_values["cpu"] = snapshot.cpu.real_percent
        if self._config.disk.enabled:
            pause_values["disk"] = snapshot.disk.real_percent
        if self._config.network.enabled:
            pause_values["network"] = snapshot.network.real_percent

        if not self._state.paused:
            for name, value in pause_values.items():
                if value >= self._config.idle_pause_percent:
                    self._state = ServiceState(paused=True, pause_reason=name)
                    self._resume_streak = 0
                    return self._state
            return self._state

        if not pause_values:
            self._state = ServiceState(paused=False, pause_reason=None)
            self._resume_streak = 0
            return self._state

        if all(value <= self._config.idle_resume_percent for value in pause_values.values()):
            self._resume_streak += 1
            if self._resume_streak >= self._config.idle_resume_cycles:
                self._state = ServiceState(paused=False, pause_reason=None)
                self._resume_streak = 0
        else:
            self._resume_streak = 0

        return self._state


class TargetPlanner:
    def __init__(self, config: AppConfig):
        self._config = config

    def build(self, snapshot: Snapshot, state: ServiceState) -> TargetPlan:
        if state.paused:
            return TargetPlan(0.0, 0.0, 0.0, 0.0)

        return TargetPlan(
            cpu_percent=self._top_up(snapshot.cpu.real_percent, self._config.cpu.target_percent, self._config.cpu.enabled),
            memory_percent=self._top_up(
                snapshot.memory.real_percent,
                self._config.memory.target_percent,
                self._config.memory.enabled,
            ),
            disk_percent=self._top_up(snapshot.disk.real_percent, self._config.disk.target_percent, self._config.disk.enabled),
            network_percent=self._top_up(
                snapshot.network.real_percent,
                self._config.network.target_percent,
                self._config.network.enabled,
            ),
        )

    @staticmethod
    def _top_up(real_percent: float, target_percent: float, enabled: bool) -> float:
        if not enabled:
            return 0.0
        return _clamp(target_percent - real_percent)
