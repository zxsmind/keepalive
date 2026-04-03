from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass

import psutil

from keepalive_service.config import AppConfig, ConfigError


class RuntimeCheckError(RuntimeError):
    """Raised when runtime prerequisites are not satisfied."""


@dataclass(frozen=True)
class RuntimeReport:
    warnings: tuple[str, ...]


class RuntimeDoctor:
    def __init__(self, config: AppConfig):
        self._config = config

    def inspect(self) -> RuntimeReport:
        warnings: list[str] = []

        if platform.system() != "Linux":
            raise RuntimeCheckError("KeepAlive is intended to run on Linux hosts")

        if shutil.which("stress-ng") is None:
            raise RuntimeCheckError("stress-ng is not installed or is not on PATH")

        self._config.work_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(self._config.work_dir, os.W_OK):
            raise RuntimeCheckError(f"work directory is not writable: {self._config.work_dir}")

        if self._config.cpu_cores > (os.cpu_count() or 1):
            warnings.append(
                "CPU_CORES is greater than visible CPU count; synthetic CPU estimation may be skewed"
            )

        if self._config.network.enabled:
            stats = psutil.net_if_stats()
            if self._config.network_interface and self._config.network_interface not in stats:
                raise RuntimeCheckError(
                    f"configured network interface was not found: {self._config.network_interface}"
                )
            if not self._config.network_endpoints:
                raise ConfigError("NETWORK_ENDPOINTS must contain at least one URL when networking is enabled")

        if self._config.disk.enabled and psutil.disk_io_counters(nowrap=True) is None:
            warnings.append("disk counters are unavailable; disk control will not behave accurately")

        return RuntimeReport(warnings=tuple(warnings))
