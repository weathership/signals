#!/usr/bin/env python3
"""Preflight check: verify all service ports are free before starting the stack.

Run this before `devenv test` or CI to fail fast if a previous stack is still
running. Not needed for `devenv up` (which attaches to an existing stack).

Usage:
    python scripts/preflight.py          # check all ports
    python scripts/preflight.py --kill   # kill processes holding our ports

Exit codes:
    0 = all ports free
    1 = ports in use (shows what's holding them)
"""

import argparse
import re
import subprocess
import sys

# (port, protocol, service description)
REQUIRED_PORTS = [
    (5455, "tcp", "PostgreSQL"),
    (8848, "udp", "Kerberos KDC"),
    (21000, "tcp", "Atlas"),
    (7051, "tcp", "Kudu Master RPC"),
    (8051, "tcp", "Kudu Master Web UI"),
    (7050, "tcp", "Kudu TServer RPC"),
    (8050, "tcp", "Kudu TServer Web UI"),
    (24000, "tcp", "Impala Statestore"),
    (25010, "tcp", "Impala Statestore Web UI"),
    (26000, "tcp", "Impala Catalogd"),
    (25020, "tcp", "Impala Catalogd Web UI"),
    (21050, "tcp", "Impala Daemon HS2"),
    (21001, "tcp", "Impala Daemon Beeswax"),
    (25000, "tcp", "Impala Daemon Web UI"),
    (27000, "tcp", "Impala Daemon KRPC"),
]


def check_port(port: int, proto: str) -> tuple[bool, int | None, str | None]:
    """Check if a port is in use. Returns (in_use, pid, process_name)."""
    flag = "-tlnp" if proto == "tcp" else "-ulnp"
    try:
        result = subprocess.run(
            ["ss", flag], capture_output=True, text=True, timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None, None

    for line in result.stdout.splitlines():
        # Match port in the local address column
        # ss output: LISTEN 0 128 127.0.0.1:5455 0.0.0.0:* users:(("postgres",pid=1234,fd=5))
        if f":{port}" not in line:
            continue
        # Verify it's an exact port match (not :54550)
        parts = line.split()
        for part in parts:
            if re.search(rf":{port}\b", part):
                # Extract PID and process name from users:((... ))
                pid_match = re.search(r"pid=(\d+)", line)
                name_match = re.search(r'users:\(\("([^"]+)"', line)
                pid = int(pid_match.group(1)) if pid_match else None
                name = name_match.group(1) if name_match else "unknown"
                return True, pid, name

    return False, None, None


def main():
    parser = argparse.ArgumentParser(
        description="Check that all service ports are free"
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="Kill processes holding our ports (use with caution)",
    )
    args = parser.parse_args()

    conflicts = []
    for port, proto, desc in REQUIRED_PORTS:
        in_use, pid, proc_name = check_port(port, proto)
        if in_use:
            conflicts.append((port, proto, desc, pid, proc_name))

    if not conflicts:
        print(f"Preflight OK: all {len(REQUIRED_PORTS)} ports free")
        return 0

    print(f"Preflight FAILED: {len(conflicts)} port(s) in use\n")
    print(f"  {'Port':<8} {'Proto':<6} {'PID':<10} {'Process':<20} {'Service'}")
    print(f"  {'─'*8} {'─'*6} {'─'*10} {'─'*20} {'─'*30}")
    for port, proto, desc, pid, proc_name in conflicts:
        pid_str = str(pid) if pid else "?"
        proc_str = proc_name or "?"
        print(f"  {port:<8} {proto:<6} {pid_str:<10} {proc_str:<20} {desc}")

    if args.kill:
        pids = {c[3] for c in conflicts if c[3]}
        if pids:
            print(f"\nKilling {len(pids)} process(es): {', '.join(str(p) for p in sorted(pids))}")
            for pid in pids:
                try:
                    subprocess.run(["kill", str(pid)], timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            print("Done. Re-run preflight to verify.")
        return 0

    print("\nTo fix:")
    print("  1. Stop the running stack:  devenv processes stop")
    print("  2. Or kill stale processes: python scripts/preflight.py --kill")
    return 1


if __name__ == "__main__":
    sys.exit(main())
