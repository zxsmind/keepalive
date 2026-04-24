# KeepAlive

KeepAlive is a Docker-native host activity controller for Linux servers. It keeps CPU, memory, disk, and network utilization near configurable target levels while the machine is idle, and it automatically backs off when real workloads appear.

The project is built for systems that must avoid looking permanently idle without competing with actual applications. A game server, panel, bot host, or low-traffic service can run normally; when real usage rises, KeepAlive yields and waits for the host to become quiet again.

## Why KeepAlive Exists

Many low-activity servers spend long periods with almost no CPU, disk, or network pressure. In some environments that is harmless. In others, it is operationally undesirable. KeepAlive exists to maintain a controlled baseline level of host activity without relying on brittle hacks or hardcoded workload tricks.

The design goals are:

- Keep utilization near a target instead of spiking aggressively
- Distinguish between synthetic activity and real application load
- Pause cleanly when the host is genuinely busy
- Resume automatically after the host becomes quiet again
- Run through Docker with a simple operational model

## Core Behavior

KeepAlive continuously samples host-wide resource usage and manages four independent synthetic generators:

- CPU
- Memory
- Disk
- Network

Each resource has a target percentage. When the host is quiet, KeepAlive pushes usage toward those targets. When real CPU, disk, or network activity exceeds the configured pause threshold, the service stops generating synthetic pressure and waits until the machine becomes idle again.

The result is a control loop rather than a fixed stress command.

The hardened default profile is CPU-first. Memory, disk, and network controllers are available, but they are opt-in rather than enabled by default.

## Features

- Adaptive control loop with pause and resume hysteresis
- Stable CPU-first default profile
- Optional generators for memory, disk, and network activity
- Process-tree based synthetic CPU attribution
- Atomic heartbeat file for status and health checks
- Docker health check support
- Human-friendly `keepalive` command wrapper

## Command-Line Experience

The host-side wrapper is designed for day-to-day operations:

```bash
keepalive status
keepalive start
keepalive stop
keepalive restart
keepalive logs
keepalive doctor
keepalive config
keepalive health
keepalive help
```

Typing `keepalive` without arguments is the same as `keepalive status`.

## Status Output

Example:

```text
KeepAlive Status
State      : active (fresh)
Reason     : -
Started    : 2026-04-04 13:40:21 UTC (2h 14m up)
Heartbeat  : 2026-04-04 15:54:52 UTC (4s ago)
Load Score : 20.9% synthetic

Resources
CPU      total= 22.7%  real=  1.8%  keepalive= 20.9%  target= 23.0%
Memory   disabled
Disk     disabled
Network  disabled
```

## Default Resource Targets

Repository defaults are intentionally aligned:

- CPU target: `23%`
- Memory target: `0%` by default, opt-in
- Disk target: `0%` by default, opt-in
- Network target: `0%` by default, opt-in

These values are configurable through environment variables in [`docker-compose.yml`](docker-compose.yml).

## Quick Start

### Local project deployment

```bash
git clone https://github.com/zxsmind/keepalive/
cd keepalive
sudo install -m 755 ./keepalive /usr/local/bin/keepalive
keepalive doctor
keepalive start
keepalive
```

### Docker Compose deployment

```bash
docker compose up -d --build
docker compose logs -f keepalive
```

## Configuration

All runtime settings are exposed as environment variables. The defaults live in [`docker-compose.yml`](docker-compose.yml).

| Variable | Default | Description |
|---|---:|---|
| `CPU_ENABLED` | `true` | Enables the CPU controller |
| `CPU_TARGET_PERCENT` | `23` | Target total CPU usage while the host is idle |
| `MEMORY_ENABLED` | `false` | Enables the memory controller |
| `MEMORY_TARGET_PERCENT` | `0` | Target total memory usage while the host is idle |
| `MEMORY_MAX_RESERVE_OF_AVAILABLE_PERCENT` | `50` | Upper safety cap for reserving currently free memory |
| `DISK_ENABLED` | `false` | Enables the disk controller |
| `DISK_TARGET_PERCENT` | `0` | Target disk throughput percentage while the host is idle |
| `NETWORK_ENABLED` | `false` | Enables the network controller |
| `NETWORK_TARGET_PERCENT` | `0` | Target network throughput percentage while the host is idle |
| `IDLE_PAUSE_PERCENT` | `12` | Real CPU, disk, or network usage above this pauses synthetic generation |
| `IDLE_RESUME_PERCENT` | `4` | Real CPU, disk, and network usage must fall below this to resume |
| `IDLE_RESUME_CYCLES` | `6` | Number of consecutive quiet loops required before resuming |
| `CONTROL_INTERVAL` | `10` | Seconds between control decisions |
| `DISK_CAPACITY_MIBPS` | `0` | Disk throughput ceiling; `0` means auto-calibrate at startup |
| `NETWORK_CAPACITY_MBIT` | `0` | NIC speed in Mbit; `0` means auto-detect or fall back |
| `NETWORK_INTERFACE` | empty | Specific NIC to monitor |
| `NETWORK_ENDPOINTS` | built-in list | Comma-separated URLs used for synthetic network activity |
| `WORK_DIR` | `/var/lib/keepalive` | Runtime directory for heartbeat and working files |

## Docker Requirements

For accurate host-level behavior, KeepAlive expects:

- Linux host environment
- `pid: host`
- `network_mode: host`
- Writable persistent storage for `/var/lib/keepalive`

Those defaults are already provided in [`docker-compose.yml`](docker-compose.yml).

## Verification

Local verification:

```bash
python -m unittest discover -s tests -v
python -m compileall keepalive.py keepalive_service tests
```

Operational verification:

```bash
keepalive doctor
keepalive status
keepalive logs
```

## Caveats

- CPU and memory control are the most directly measurable signals.
- Disk and network percentages depend on capacity calibration and are therefore inherently approximate.
- The CPU-first default profile is the recommended production mode.
- Docker Desktop can obscure true host behavior behind a Linux VM; a real Linux host is strongly preferred.
- Resource percentages should be tuned carefully for the environment where KeepAlive will run.
