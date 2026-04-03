from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceSample:
    total_percent: float
    synthetic_percent: float
    real_percent: float


@dataclass(frozen=True)
class Snapshot:
    cpu: ResourceSample
    memory: ResourceSample
    disk: ResourceSample
    network: ResourceSample


@dataclass(frozen=True)
class ServiceState:
    paused: bool
    pause_reason: str | None
