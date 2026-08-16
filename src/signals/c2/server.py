"""Minimal MiNiFi C2 HTTP: heartbeat / last-gasp → Engine/Yield gRPC."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

from signals.c2.parse import parse_heartbeat
from signals.c2.peers import lattice_target
from signals.c2.yield_client import yield_workload

log = logging.getLogger("signals.c2.server")

YieldFn = Callable[..., dict]


class C2State:
    def __init__(
        self,
        *,
        yield_fn: YieldFn | None = None,
        orphan_after_s: float = 20.0,
    ):
        self.yield_fn = yield_fn or yield_workload
        self.orphan_after_s = orphan_after_s
        self._mu = threading.Lock()
        # workload_id -> last seen monotonic + meta
        self._seen: dict[str, dict[str, Any]] = {}

    def note(self, meta: dict[str, str]) -> None:
        wid = meta.get("workload_id") or ""
        if not wid:
            return
        with self._mu:
            self._seen[wid] = {
                "meta": meta,
                "at": time.monotonic(),
            }

    def maybe_yield(self, meta: dict[str, str], reason: str, detail: str) -> dict:
        wid = meta.get("workload_id") or ""
        if not wid:
            return {"ok": False, "message": "missing workload_id", "skipped": True}
        project = meta.get("project") or "signals"
        target = lattice_target(project)
        log.info(
            "C2 Yield reason=%s project=%s workload_id=%s target=%s",
            reason,
            project,
            wid,
            target,
        )
        result = self.yield_fn(
            target,
            workload_id=wid,
            reason=reason,
            sentinel_id=meta.get("sentinel_id") or "",
            detail=detail,
        )
        with self._mu:
            self._seen.pop(wid, None)
        return result

    def sweep_orphans(self) -> list[dict]:
        now = time.monotonic()
        due: list[dict[str, str]] = []
        with self._mu:
            for wid, rec in list(self._seen.items()):
                if now - float(rec["at"]) >= self.orphan_after_s:
                    due.append(rec["meta"])
                    self._seen.pop(wid, None)
        out = []
        for meta in due:
            out.append(self.maybe_yield(meta, "ORPHAN", "heartbeat timeout"))
        return out


def make_handler(state: C2State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            log.info(fmt, *args)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode())
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _write(self, code: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/healthz", "/"):
                self._write(200, {"ok": True, "service": "signals-c2"})
                return
            self._write(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            body = self._read_json()
            meta = parse_heartbeat(body)
            if path.endswith("/c2-protocol/heartbeat"):
                state.note(meta)
                if meta["phase"] in ("preempted", "complete", "failed"):
                    reason = (
                        "PREEMPTED" if meta["phase"] == "preempted" else "COMPLETED"
                    )
                    result = state.maybe_yield(
                        meta, reason, f"heartbeat phase={meta['phase']}"
                    )
                    self._write(
                        200,
                        {"requestedoperations": [], "yield": result},
                    )
                    return
                self._write(200, {"requestedoperations": []})
                return
            if path.endswith("/c2-protocol/acknowledge"):
                self._write(200, {"ok": True})
                return
            if path.endswith("/c2-protocol/last-gasp"):
                if not meta.get("phase") or meta["phase"] == "running":
                    meta["phase"] = "preempted"
                result = state.maybe_yield(
                    meta, "PREEMPTED", "last-gasp (preStop / SIGTERM)"
                )
                self._write(200, {"ok": True, "yield": result})
                return
            self._write(404, {"error": "not found"})

    return Handler


def serve(
    host: str | None = None,
    port: int | None = None,
    *,
    state: C2State | None = None,
) -> None:
    host = host or os.environ.get("SIGNALS_C2_BIND_HOST", "0.0.0.0")
    port = int(port or os.environ.get("SIGNALS_C2_HTTP_PORT", "50561"))
    orphan = float(os.environ.get("SIGNALS_C2_ORPHAN_AFTER_S", "20"))
    st = state or C2State(orphan_after_s=orphan)

    def _orphans() -> None:
        while True:
            time.sleep(min(5.0, max(1.0, st.orphan_after_s / 2)))
            try:
                st.sweep_orphans()
            except Exception:  # noqa: BLE001
                log.exception("orphan sweep failed")

    threading.Thread(target=_orphans, name="c2-orphan", daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), make_handler(st))
    log.info("signals-c2 listening on %s:%s (C2 HTTP; Yield via gRPC)", host, port)
    httpd.serve_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    serve()


if __name__ == "__main__":
    main()
