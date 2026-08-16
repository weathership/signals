"""zndx.engine.v1.Engine — Status, Yield (+ stub Complete/Remediate)."""

from __future__ import annotations

import grpc

from signals.engine.generated.zndx.engine.v1 import engine_pb2, engine_pb2_grpc
from signals.engine.workloads import WorkloadTable
from signals.engine.yk_client import YkRestClient, YkRestError


class SignalsEngineServicer(engine_pb2_grpc.EngineServicer):
    def __init__(
        self,
        project: str,
        yk: YkRestClient,
        workloads: WorkloadTable | None = None,
    ):
        self.project = project
        self.yk = yk
        self.workloads = workloads if workloads is not None else WorkloadTable()

    def Status(self, request, context):  # noqa: N802
        healthy = False
        detail = "yunikorn REST unreachable"
        try:
            self.yk.partitions()
            healthy = True
            detail = "yunikorn ops proxy ready"
        except YkRestError as e:
            detail = str(e)[:200]
        return engine_pb2.StatusResponse(
            project=self.project,
            endpoints=[
                engine_pb2.Endpoint(
                    capability="scheduler",
                    model="yunikorn",
                    healthy=healthy,
                    gpu_ids=[],
                    detail=detail,
                )
            ],
            total_gpus=0,
        )

    def Complete(self, request, context):  # noqa: N802
        context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Signals engine Complete is not implemented; use peer capability engines "
            "(gaius/aegir/atelier) for inference.",
        )

    def Remediate(self, request, context):  # noqa: N802
        context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Remediate is served by Aegir (instruct / ontology). "
            "Signals engine capability is scheduler (lab backend: yunikorn).",
        )

    def Yield(self, request, context):  # noqa: N802
        ended, msg = self.workloads.yield_one(request.workload_id)
        return engine_pb2.YieldResponse(
            ok=True,
            process_ended=ended,
            restore_started=False,
            message=msg,
        )
