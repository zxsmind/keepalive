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

## Features

- Adaptive control loop with pause and resume hysteresis
- Separate generators for CPU, memory, disk, and network activity
- Process-tree based synthetic CPU attribution
- Atomic heartbeat file for status and health checks
- Docker health check support
- Human-friendly `keepalive` command wrapper
- GitHub Actions workflow for automatic GHCR image publishing

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
Load Score : 14.5% synthetic

Resources
CPU      total= 22.7%  real=  1.8%  keepalive= 20.9%  target= 23.0%
Memory   total= 31.4%  real=  8.4%  keepalive= 23.0%  target= 23.0%
Disk     total= 23.1%  real=  0.3%  keepalive= 22.8%  target= 23.0%
Network  total= 23.0%  real=  0.4%  keepalive= 22.6%  target= 23.0%
```

## Default Resource Targets

Repository defaults are intentionally aligned:

- CPU target: `23%`
- Memory target: `23%`
- Disk target: `23%`
- Network target: `23%`

These values are configurable through environment variables in [`docker-compose.yml`](docker-compose.yml).

## Quick Start

### Local project deployment

```bash
git clone <your-repo-url>
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
| `CPU_TARGET_PERCENT` | `23` | Target total CPU usage while the host is idle |
| `MEMORY_TARGET_PERCENT` | `23` | Target total memory usage while the host is idle |
| `MEMORY_MAX_RESERVE_OF_AVAILABLE_PERCENT` | `50` | Upper safety cap for reserving currently free memory |
| `DISK_TARGET_PERCENT` | `23` | Target disk throughput percentage while the host is idle |
| `NETWORK_TARGET_PERCENT` | `23` | Target network throughput percentage while the host is idle |
| `IDLE_PAUSE_PERCENT` | `5` | Real CPU, disk, or network usage above this pauses synthetic generation |
| `IDLE_RESUME_PERCENT` | `2` | Real CPU, disk, and network usage must fall below this to resume |
| `IDLE_RESUME_CYCLES` | `3` | Number of consecutive quiet loops required before resuming |
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

## GitHub Publishing

Pushing the repository to GitHub does not automatically run KeepAlive on a server. What it can do is automatically build and publish a container image.

This repository includes a GitHub Actions workflow at [`.github/workflows/publish-ghcr.yml`](.github/workflows/publish-ghcr.yml). It publishes an image to:

```text
ghcr.io/<github-username>/keepalive
```

Workflow behavior:

- Push to `main`: publishes `latest`
- Push a tag such as `v1.0.0`: publishes a versioned image tag
- Manual run from the Actions tab: also supported

After the image is published, a server can run it directly:

```bash
docker run -d \
  --name keepalive \
  --restart unless-stopped \
  --init \
  --pid host \
  --network host \
  -v keepalive-data:/var/lib/keepalive \
  ghcr.io/<github-username>/keepalive:latest
```

## How to Publish This Repository to GitHub

If this folder is not yet a Git repository:

```bash
git init
git add .
git commit -m "Initial KeepAlive release"
git branch -M main
git remote add origin https://github.com/<your-username>/keepalive.git
git push -u origin main
```

If the GitHub repository already exists and this folder is already initialized:

```bash
git add .
git commit -m "Prepare repository for GitHub release"
git push
```

After the first push:

1. Open the GitHub repository page.
2. Confirm that Actions are enabled.
3. Wait for the `Publish GHCR Image` workflow to finish.
4. Verify that the package appears under your GitHub account packages or repository packages.

## Suggested Repository Setup

For a clean public release, it is worth setting:

- Repository description
- Topics such as `docker`, `linux`, `server`, `monitoring`, `automation`
- A proper license
- A first release tag such as `v1.0.0`

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
- Docker Desktop can obscure true host behavior behind a Linux VM; a real Linux host is strongly preferred.
- Resource percentages should be tuned carefully for the environment where KeepAlive will run.
