"""Local process table for Engine/Yield (lab proof + future host work)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from threading import Lock

log = logging.getLogger("signals.engine.workloads")


@dataclass
class AttachedWorkload:
    workload_id: str
    pid: int
    started_at: float = field(default_factory=time.time)
    proc: subprocess.Popen | None = field(default=None, repr=False)


class WorkloadTable:
    """Engine-owned pids keyed by workload_id (shared with C2 / YK)."""

    def __init__(self) -> None:
        self._mu = Lock()
        self._rows: dict[str, AttachedWorkload] = {}

    def attach(self, workload_id: str) -> AttachedWorkload:
        wid = (workload_id or "").strip()
        if not wid:
            raise ValueError("workload_id required")
        with self._mu:
            existing = self._rows.get(wid)
            if existing and _pid_alive(existing.pid):
                return existing
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(864000)"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.poll() is not None:
                raise RuntimeError(
                    f"proof process exited immediately code={proc.returncode}"
                )
            row = AttachedWorkload(workload_id=wid, pid=proc.pid, proc=proc)
            self._rows[wid] = row
            log.info("attached workload_id=%s pid=%s", wid, proc.pid)
            return row

    def get(self, workload_id: str) -> AttachedWorkload | None:
        with self._mu:
            return self._rows.get(workload_id)

    def list(self) -> list[AttachedWorkload]:
        with self._mu:
            return list(self._rows.values())

    def yield_one(self, workload_id: str) -> tuple[bool, str]:
        """End the process. Returns (process_ended, message). Idempotent."""
        wid = (workload_id or "").strip()
        with self._mu:
            row = self._rows.pop(wid, None) if wid else None
        if row is None:
            return False, f"no local process for workload_id={wid or '(empty)'}"
        ended = _terminate(row.pid, proc=row.proc)
        msg = (
            f"ended pid={row.pid} workload_id={wid}"
            if ended
            else f"pid={row.pid} already gone workload_id={wid}"
        )
        log.info("yield %s", msg)
        return ended, msg


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _reap(pid: int, proc: subprocess.Popen | None) -> bool:
    if proc is not None:
        try:
            proc.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            return False
        return proc.returncode is not None
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return not _pid_alive(pid)
    return not _pid_alive(pid)


def _terminate(pid: int, proc: subprocess.Popen | None = None) -> bool:
    if proc is not None and proc.poll() is not None:
        return True
    if not _pid_alive(pid) and _reap(pid, proc):
        return True
    if not _pid_alive(pid) and proc is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return _reap(pid, proc)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if _reap(pid, proc):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if _reap(pid, proc):
            return True
        time.sleep(0.05)
    return proc is not None and proc.poll() is not None
