"""Multi-service gRPC server: zndx.engine.v1.Engine + zndx.scheduler.v1.Scheduler."""

from __future__ import annotations

import json
import logging
import threading
from concurrent import futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import grpc
from grpc_reflection.v1alpha import reflection

from signals.engine.config import EngineConfig
from signals.engine.generated.zndx.engine.v1 import engine_pb2, engine_pb2_grpc
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2, scheduler_pb2_grpc
from signals.engine.projection import ProjectionStore
from signals.engine.servicers.engine_status import SignalsEngineServicer
from signals.engine.servicers.scheduler import SchedulerServicer
from signals.engine.workloads import WorkloadTable
from signals.engine.yk_client import YkRestClient

log = logging.getLogger("signals.engine.server")


def _start_control_http(cfg: EngineConfig, table: WorkloadTable) -> ThreadingHTTPServer:
    """Loopback attach/list for the lab proof process (not C2, not lattice)."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            log.info("control: " + fmt, *args)

        def _json(self, code: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/healthz", "/"):
                self._json(200, {"ok": True, "service": "signals-engine-control"})
                return
            if path == "/workloads":
                rows = [
                    {"workload_id": r.workload_id, "pid": r.pid}
                    for r in table.list()
                ]
                self._json(200, {"workloads": rows})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            if path == "/workloads":
                wid = str(payload.get("workload_id") or "")
                try:
                    row = table.attach(wid)
                except ValueError as e:
                    self._json(400, {"error": str(e)})
                    return
                self._json(
                    200,
                    {"workload_id": row.workload_id, "pid": row.pid},
                )
                return
            self._json(404, {"error": "not found"})

    try:
        httpd = ThreadingHTTPServer((cfg.control_host, cfg.control_port), Handler)
    except OSError as e:
        # A restart race can leave the prior control socket briefly held. The
        # lattice Engine + Scheduler serving does not depend on this control HTTP,
        # so a bind failure must not crash or degrade the engine — log and skip.
        log.warning(
            "engine control HTTP bind on %s failed (%s) — continuing without it",
            cfg.control_addr, e,
        )
        return None
    threading.Thread(target=httpd.serve_forever, name="engine-control", daemon=True).start()
    log.info("engine control HTTP on %s (POST /workloads)", cfg.control_addr)
    return httpd


def _start_telemetry_http() -> None:
    """LAN pull of live DCGM as OTLP. No retain. 503 if exporter is down."""
    import os

    from signals.telemetry.dcgm_otel import serve as otel_serve

    host = os.environ.get("SIGNALS_DCGM_OTEL_HOST", "0.0.0.0")
    port = int(os.environ.get("SIGNALS_DCGM_OTEL_PORT", "9410"))
    httpd = otel_serve(host, port)
    threading.Thread(target=httpd.serve_forever, name="dcgm-otel", daemon=True).start()
    log.info("dcgm otel pull on %s:%s GET /v1/metrics (no store)", host, port)
    return httpd


def serve(cfg: EngineConfig | None = None) -> None:
    cfg = cfg or EngineConfig.from_env()
    yk = YkRestClient(cfg.yk_rest_url, timeout_s=cfg.yk_request_timeout_s)
    store = ProjectionStore(cfg.projection_root)
    workloads = WorkloadTable()
    _start_control_http(cfg, workloads)
    _start_telemetry_http()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    engine_pb2_grpc.add_EngineServicer_to_server(
        SignalsEngineServicer(cfg.project, yk, workloads=workloads), server
    )
    scheduler_pb2_grpc.add_SchedulerServicer_to_server(
        SchedulerServicer(yk, store, apply_cfg=cfg.apply), server
    )

    SERVICE_NAMES = (
        engine_pb2.DESCRIPTOR.services_by_name["Engine"].full_name,
        scheduler_pb2.DESCRIPTOR.services_by_name["Scheduler"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    addr = cfg.listen_addr
    server.add_insecure_port(addr)
    server.start()
    log.info(
        "signals-engine listening on %s (Engine + Scheduler + reflection); "
        "backend=%s projection=%s",
        addr,
        cfg.yk_rest_url,
        cfg.projection_root,
    )
    server.wait_for_termination()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    serve()


if __name__ == "__main__":
    main()
