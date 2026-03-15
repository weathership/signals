#!/usr/bin/env python3
"""Wait for all devenv processes to be healthy, with progress tracking.

Instead of a fixed timeout, tracks progress: as long as any process changes
state (starts, becomes ready, restarts), the staleness timer resets. Only
fails if NO progress is made for --stale-timeout seconds, or if a process
crash-loops beyond --max-restarts.

Usage:
    python scripts/wait_for_stack.py                  # auto-discover socket
    python scripts/wait_for_stack.py --stale-timeout 600  # patient (GPU loading)
    python scripts/wait_for_stack.py --max-restarts 3     # strict crash detection

Exit codes:
    0 = all processes healthy
    1 = failure (crash-loop or stale)
    2 = process-compose not reachable
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _socket_alive(path: str) -> bool:
    """Test if a Unix socket is accepting connections."""
    import socket
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(path)
        s.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


def find_socket() -> str | None:
    """Discover the process-compose Unix socket path for this project.

    Checks that the socket is actually accepting connections, not just
    that the file exists (stale sockets from crashed processes linger).

    Only checks project-scoped paths to avoid connecting to a different
    project's process-compose instance.
    """
    candidates: list[str] = []

    # 1. Explicit env var (set by devenv for the current project)
    sock = os.environ.get("PC_SOCKET_PATH")
    if sock:
        candidates.append(sock)

    # 2. Project-local .devenv state directories
    for state_dir in [".devenv/test-state", ".devenv/state"]:
        candidate = Path(state_dir) / "pc.sock"
        if candidate.exists():
            candidates.append(str(candidate))

    # Return the first socket that's actually alive
    for c in candidates:
        if _socket_alive(c):
            return c

    return None


def get_processes(socket_path: str) -> list[dict] | None:
    """Query process-compose for current process states."""
    cmd = [
        "process-compose", "process", "list",
        "-o", "json", "-U", "-u", socket_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def wait_for_healthy(
    socket_path: str,
    stale_timeout: int = 300,
    max_restarts: int = 5,
    poll_interval: float = 2.0,
) -> bool:
    """Wait until all processes with readiness probes report Ready.

    Progress is defined as any process changing state, becoming ready,
    or restarting. The stale timer only fires when nothing has changed.
    Crash-loops (restarts > max_restarts) cause immediate failure.
    """
    last_progress = time.time()
    prev_snapshot: dict[str, tuple[str, bool, int]] = {}
    connect_reported = False

    while True:
        procs = get_processes(socket_path)

        if procs is None:
            if not connect_reported:
                print("  Waiting for process-compose...", flush=True)
                connect_reported = True
            if time.time() - last_progress > stale_timeout:
                print(
                    f"FAIL: process-compose not reachable after {stale_timeout}s",
                    file=sys.stderr,
                )
                return False
            time.sleep(poll_interval)
            continue

        snapshot: dict[str, tuple[str, bool, int]] = {}
        all_healthy = True
        unhealthy: list[str] = []

        for p in procs:
            name = p["name"]
            status = p.get("status", "Unknown")
            ready = p.get("is_ready", "") == "Ready"
            restarts = p.get("restarts", 0)
            has_probe = p.get("has_ready_probe", False)

            snapshot[name] = (status, ready, restarts)

            # Crash-loop detection
            if restarts > max_restarts:
                print(
                    f"FAIL: {name} crash-looping ({restarts} restarts, "
                    f"exit_code={p.get('exit_code', '?')})",
                    file=sys.stderr,
                )
                return False

            # Health check: processes with probes must be Ready,
            # others just need to be Running
            if has_probe and not ready:
                all_healthy = False
                unhealthy.append(name)
            elif not has_probe and status != "Running":
                all_healthy = False
                unhealthy.append(name)

        # Detect progress by comparing to previous snapshot
        changed = False
        for name, (status, ready, restarts) in snapshot.items():
            prev = prev_snapshot.get(name)
            if prev is None:
                # First time seeing this process
                changed = True
                marker = " [ready]" if ready else ""
                print(f"  {name}: {status}{marker}", flush=True)
            elif prev != (status, ready, restarts):
                changed = True
                prev_status, prev_ready, prev_restarts = prev
                old = f"{prev_status}{'[ready]' if prev_ready else ''}"
                new = f"{status}{'[ready]' if ready else ''}"
                extra = f" (restart #{restarts})" if restarts > prev_restarts else ""
                print(f"  {name}: {old} -> {new}{extra}", flush=True)

        if changed:
            last_progress = time.time()
        prev_snapshot = snapshot

        if all_healthy:
            print(f"All {len(procs)} processes healthy.", flush=True)
            return True

        # Staleness check
        stale_secs = time.time() - last_progress
        if stale_secs > stale_timeout:
            print(
                f"FAIL: No progress for {stale_timeout}s. "
                f"Not ready: {', '.join(unhealthy)}",
                file=sys.stderr,
            )
            return False

        time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(
        description="Wait for all devenv processes to be healthy"
    )
    parser.add_argument(
        "--stale-timeout",
        type=int,
        default=300,
        help="Fail after this many seconds with no progress (default: 300)",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=5,
        help="Fail if any process restarts more than this (default: 5)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between health checks (default: 2.0)",
    )
    parser.add_argument(
        "--socket",
        type=str,
        default=None,
        help="Path to process-compose Unix socket (auto-discovered if omitted)",
    )
    args = parser.parse_args()

    socket_path = args.socket or find_socket()
    if not socket_path:
        print("FAIL: Cannot find process-compose socket", file=sys.stderr)
        print(
            "Is devenv up running? Set PC_SOCKET_PATH or pass --socket.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Waiting for stack health (socket: {socket_path})", flush=True)
    ok = wait_for_healthy(
        socket_path,
        stale_timeout=args.stale_timeout,
        max_restarts=args.max_restarts,
        poll_interval=args.poll_interval,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
