from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


RESOURCE_ORDER = ("cpu", "memory", "disk", "network")
RESOURCE_LABELS = {
    "cpu": "CPU",
    "memory": "Memory",
    "disk": "Disk",
    "network": "Network",
}


class StatusError(RuntimeError):
    """Raised when status output cannot be produced."""


def load_status_payload(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StatusError(f"heartbeat file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StatusError(f"heartbeat file is not valid JSON: {path}") from exc


def format_status(payload: dict[str, object], max_age_seconds: int, now: float | None = None) -> str:
    current_time = time.time() if now is None else now
    started_at = int(payload.get("started_at", 0) or 0)
    heartbeat_at = int(payload.get("timestamp", 0) or 0)
    heartbeat_age = max(0, int(current_time - heartbeat_at))
    state = "paused" if payload.get("paused", False) else "active"
    reason = payload.get("reason") or "-"
    load_score = _synthetic_load_score(payload)
    freshness = "stale" if heartbeat_age > max_age_seconds else "fresh"

    lines = [
        "KeepAlive Status",
        f"State      : {state} ({freshness})",
        f"Reason     : {reason}",
        f"Started    : {_format_timestamp(started_at)} ({_format_duration(max(0, int(current_time - started_at)))})",
        f"Heartbeat  : {_format_timestamp(heartbeat_at)} ({heartbeat_age}s ago)",
        f"Load Score : {load_score:4.1f}% synthetic",
        "",
        "Resources",
    ]

    targets = payload.get("targets", {})
    for resource in RESOURCE_ORDER:
        sample = payload.get(resource)
        if not isinstance(sample, dict):
            continue
        target = _safe_float(targets.get(resource)) if isinstance(targets, dict) else 0.0
        lines.append(_format_resource_line(resource, sample, target))

    return "\n".join(lines)


def _format_resource_line(resource: str, sample: dict[str, object], target: float) -> str:
    total = _safe_float(sample.get("total_percent"))
    real = _safe_float(sample.get("real_percent"))
    synthetic = _safe_float(sample.get("synthetic_percent"))
    return (
        f"{RESOURCE_LABELS[resource]:<8} "
        f"total={total:5.1f}%  "
        f"real={real:5.1f}%  "
        f"keepalive={synthetic:5.1f}%  "
        f"target={target:5.1f}%"
    )


def _synthetic_load_score(payload: dict[str, object]) -> float:
    values: list[float] = []
    for resource in RESOURCE_ORDER:
        sample = payload.get(resource)
        if isinstance(sample, dict):
            values.append(_safe_float(sample.get("synthetic_percent")))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_timestamp(timestamp: int) -> str:
    if timestamp <= 0:
        return "unknown"
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s up"

    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s up"

    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m up"

    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h up"
