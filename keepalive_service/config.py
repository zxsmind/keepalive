from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean value")


def _read_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a floating point value") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer value") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not items:
        raise ConfigError(f"{name} must contain at least one item")
    return items


@dataclass(frozen=True)
class ResourceTarget:
    enabled: bool
    target_percent: float


@dataclass(frozen=True)
class AppConfig:
    control_interval_seconds: float
    ema_alpha: float
    idle_resume_percent: float
    idle_pause_percent: float
    idle_resume_cycles: int
    cpu_cores: int
    cpu: ResourceTarget
    memory: ResourceTarget
    memory_max_reserve_of_available_percent: float
    disk: ResourceTarget
    network: ResourceTarget
    disk_capacity_mib_per_second: float | None
    disk_chunk_kib: int
    disk_working_set_mib: int
    disk_calibration_mib: int
    network_interface: str | None
    network_capacity_mbit: float | None
    network_endpoints: tuple[str, ...]
    network_timeout_seconds: float
    work_dir: Path
    heartbeat_file: Path
    log_level: str

    def controller_enabled(self, resource: str) -> bool:
        return bool(getattr(self, resource).enabled)

    @classmethod
    def from_env(cls) -> "AppConfig":
        work_dir = Path(os.getenv("WORK_DIR", "/var/lib/keepalive")).expanduser().resolve()
        heartbeat_file = Path(
            os.getenv("HEARTBEAT_FILE", str(work_dir / "heartbeat.json"))
        ).expanduser().resolve()

        control_interval = _read_float("CONTROL_INTERVAL", 10.0, 0.5, 300.0)
        idle_pause = _read_float("IDLE_PAUSE_PERCENT", 12.0, 0.0, 100.0)
        idle_resume = _read_float("IDLE_RESUME_PERCENT", 4.0, 0.0, idle_pause)

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ConfigError("LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR")

        disk_capacity = _read_float("DISK_CAPACITY_MIBPS", 0.0, 0.0, 10240.0)
        network_capacity = _read_float("NETWORK_CAPACITY_MBIT", 0.0, 0.0, 400000.0)

        return cls(
            control_interval_seconds=control_interval,
            ema_alpha=_read_float("EMA_ALPHA", 0.35, 0.05, 1.0),
            idle_resume_percent=idle_resume,
            idle_pause_percent=idle_pause,
            idle_resume_cycles=_read_int("IDLE_RESUME_CYCLES", 6, 1, 120),
            cpu_cores=_read_int("CPU_CORES", os.cpu_count() or 1, 1, 1024),
            cpu=ResourceTarget(
                enabled=_read_bool("CPU_ENABLED", True),
                target_percent=_read_float("CPU_TARGET_PERCENT", 23.0, 0.0, 100.0),
            ),
            memory=ResourceTarget(
                enabled=_read_bool("MEMORY_ENABLED", False),
                target_percent=_read_float("MEMORY_TARGET_PERCENT", 0.0, 0.0, 95.0),
            ),
            memory_max_reserve_of_available_percent=_read_float(
                "MEMORY_MAX_RESERVE_OF_AVAILABLE_PERCENT",
                50.0,
                1.0,
                95.0,
            ),
            disk=ResourceTarget(
                enabled=_read_bool("DISK_ENABLED", False),
                target_percent=_read_float("DISK_TARGET_PERCENT", 0.0, 0.0, 100.0),
            ),
            network=ResourceTarget(
                enabled=_read_bool("NETWORK_ENABLED", False),
                target_percent=_read_float("NETWORK_TARGET_PERCENT", 0.0, 0.0, 100.0),
            ),
            disk_capacity_mib_per_second=None if disk_capacity == 0.0 else disk_capacity,
            disk_chunk_kib=_read_int("DISK_CHUNK_KIB", 1024, 64, 16384),
            disk_working_set_mib=_read_int("DISK_WORKING_SET_MIB", 128, 16, 4096),
            disk_calibration_mib=_read_int("DISK_CALIBRATION_MIB", 32, 8, 512),
            network_interface=os.getenv("NETWORK_INTERFACE") or None,
            network_capacity_mbit=None if network_capacity == 0.0 else network_capacity,
            network_endpoints=_read_list(
                "NETWORK_ENDPOINTS",
                (
                    "https://checkip.amazonaws.com",
                    "https://cloudflare.com/cdn-cgi/trace",
                ),
            ),
            network_timeout_seconds=_read_float("NETWORK_TIMEOUT_SECONDS", 10.0, 1.0, 60.0),
            work_dir=work_dir,
            heartbeat_file=heartbeat_file,
            log_level=log_level,
        )
