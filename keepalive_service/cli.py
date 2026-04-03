from __future__ import annotations

import argparse
import json
import time

from keepalive_service.config import AppConfig, ConfigError
from keepalive_service.diagnostics import RuntimeCheckError, RuntimeDoctor
from keepalive_service.logging_utils import configure_logging
from keepalive_service.service import KeepAliveService
from keepalive_service.status import StatusError, format_status, load_status_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive host activity controller")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "status", "doctor", "config", "print-config", "health", "healthcheck"),
        default="run",
        help="command to execute",
    )
    parser.add_argument("--doctor", action="store_true", help="validate runtime prerequisites")
    parser.add_argument("--print-config", action="store_true", help="print normalized config and exit")
    parser.add_argument("--healthcheck", action="store_true", help="validate the heartbeat file")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit JSON for status output")
    parser.add_argument(
        "--max-age",
        type=int,
        default=120,
        help="maximum acceptable heartbeat age in seconds",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = AppConfig.from_env()
    except ConfigError as exc:
        parser.error(str(exc))
        return 2

    command = _resolve_command(args)

    if command == "config":
        command = "print-config"

    if command == "health":
        command = "healthcheck"

    if command == "print-config":
        print(json.dumps(_config_payload(config), indent=2, sort_keys=True))
        return 0

    if command == "doctor":
        return run_doctor(config)

    if command == "healthcheck":
        return run_healthcheck(config, args.max_age)

    if command == "status":
        return run_status(config, args.max_age, args.json_output)

    logger = configure_logging(config.log_level)
    service = KeepAliveService(config, logger)
    return service.run()


def run_healthcheck(config: AppConfig, max_age_seconds: int) -> int:
    try:
        payload = load_status_payload(config.heartbeat_file)
    except StatusError:
        return 1

    timestamp = int(payload.get("timestamp", 0))
    return 0 if (time.time() - timestamp) <= max_age_seconds else 1


def run_status(config: AppConfig, max_age_seconds: int, json_output: bool) -> int:
    try:
        payload = load_status_payload(config.heartbeat_file)
    except StatusError as exc:
        print(str(exc))
        return 1

    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(format_status(payload, max_age_seconds=max_age_seconds))
    return 0


def run_doctor(config: AppConfig) -> int:
    try:
        report = RuntimeDoctor(config).inspect()
    except (ConfigError, RuntimeCheckError) as exc:
        print(str(exc))
        return 1

    payload = {
        "status": "ok",
        "warnings": list(report.warnings),
        "config": _config_payload(config),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _config_payload(config: AppConfig) -> dict[str, object]:
    return {
        "control_interval_seconds": config.control_interval_seconds,
        "cpu_cores": config.cpu_cores,
        "cpu_target_percent": config.cpu.target_percent,
        "memory_target_percent": config.memory.target_percent,
        "memory_max_reserve_of_available_percent": config.memory_max_reserve_of_available_percent,
        "disk_target_percent": config.disk.target_percent,
        "network_target_percent": config.network.target_percent,
        "idle_pause_percent": config.idle_pause_percent,
        "idle_resume_percent": config.idle_resume_percent,
        "idle_resume_cycles": config.idle_resume_cycles,
        "work_dir": str(config.work_dir),
        "heartbeat_file": str(config.heartbeat_file),
        "network_interface": config.network_interface,
        "network_endpoints": list(config.network_endpoints),
    }


def _resolve_command(args: argparse.Namespace) -> str:
    if args.print_config:
        return "print-config"
    if args.doctor:
        return "doctor"
    if args.healthcheck:
        return "healthcheck"
    return args.command
