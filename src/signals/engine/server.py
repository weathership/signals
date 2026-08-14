"""Multi-service gRPC server: zndx.engine.v1.Engine + zndx.scheduler.v1.Scheduler."""

from __future__ import annotations

import logging
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

from signals.engine.config import EngineConfig
from signals.engine.generated.zndx.engine.v1 import engine_pb2, engine_pb2_grpc
from signals.engine.generated.zndx.scheduler.v1 import scheduler_pb2, scheduler_pb2_grpc
from signals.engine.projection import ProjectionStore
from signals.engine.servicers.engine_status import SignalsEngineServicer
from signals.engine.servicers.scheduler import SchedulerServicer
from signals.engine.yk_client import YkRestClient

log = logging.getLogger("signals.engine.server")


def serve(cfg: EngineConfig | None = None) -> None:
    cfg = cfg or EngineConfig.from_env()
    yk = YkRestClient(cfg.yk_rest_url, timeout_s=cfg.yk_request_timeout_s)
    store = ProjectionStore(cfg.projection_root)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    engine_pb2_grpc.add_EngineServicer_to_server(
        SignalsEngineServicer(cfg.project, yk), server
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
