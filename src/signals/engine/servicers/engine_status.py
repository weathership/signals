"""zndx.engine.v1.Engine — Status, Yield, ServerQuery, RecordLineage."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import grpc

from signals.engine.generated.zndx.engine.v1 import engine_pb2, engine_pb2_grpc
from signals.engine.s2s import local_response, local_surfaces
from signals.engine.workloads import WorkloadTable
from signals.engine.yk_client import YkRestClient, YkRestError

GURU_NOATLAS = "#LN.00000001.NOATLAS"


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
        resp = engine_pb2.StatusResponse(
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
            surfaces=local_surfaces(),
        )
        return resp

    def ServerQuery(self, request, context):  # noqa: N802
        resp = local_response(int(request.kind or 0))
        if self.project:
            resp.project = self.project
        return resp

    def RecordLineage(self, request, context):  # noqa: N802
        raw = (request.event_json or "").strip()
        if not raw:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{GURU_NOATLAS} LineageRequest.event_json is empty.",
            )
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{GURU_NOATLAS} event_json is not JSON: {e}",
            )
        want = (request.event_type or "").strip().upper()
        got = str(body.get("eventType") or "").upper()
        if want and got and want != got:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"{GURU_NOATLAS} event_type={want!r} != event_json.eventType={got!r}",
            )
        url = (
            os.environ.get("SIGNALS_ATLAS_OL_URL") or "http://127.0.0.1:21010/api/v1/lineage"
        ).rstrip("/")
        if not url.endswith("/lineage"):
            url = url + "/lineage"
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=payload, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status >= 400:
                    snippet = resp.read()[:300].decode("utf-8", errors="replace")
                    return engine_pb2.LineageResponse(
                        accepted=False,
                        error=f"{GURU_NOATLAS} Atlas HTTP {resp.status}: {snippet}",
                    )
        except urllib.error.HTTPError as e:
            snippet = e.read()[:300].decode("utf-8", errors="replace")
            return engine_pb2.LineageResponse(
                accepted=False,
                error=f"{GURU_NOATLAS} Atlas HTTP {e.code}: {snippet}",
            )
        except Exception as e:
            return engine_pb2.LineageResponse(
                accepted=False,
                error=f"{GURU_NOATLAS} Atlas POST {url} failed: {e}",
            )
        return engine_pb2.LineageResponse(accepted=True, error="")

    def Complete(self, request, context):  # noqa: N802
        context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Signals engine Complete is not implemented; use peer capability engines "
            "(gaius/aegir/atelier) for inference.",
        )

    def Remediate(self, request, context):  # noqa: N802
        context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Remediate is served by Aegir (ontology adaptation). "
            "Signals engine capability is scheduler (lab backend: yunikorn).",
        )

    def Announce(self, request, context):  # noqa: N802
        # The protocol says engines that are not a directory answer UNIMPLEMENTED
        # (honest). Answer it explicitly: the generated default raises
        # NotImplementedError, which grpc logs as an ERROR traceback on every
        # peer announce (Hermes announces every ~30 s) — noise in this log.
        context.abort(
            grpc.StatusCode.UNIMPLEMENTED,
            "Signals engine is not a peer directory (Announce is served by Aegir); "
            f"peer {request.project or '?'} at {request.engine_target or '?'} not recorded.",
        )

    def Yield(self, request, context):  # noqa: N802
        ended, msg = self.workloads.yield_one(request.workload_id)
        return engine_pb2.YieldResponse(
            ok=True,
            process_ended=ended,
            restore_started=False,
            message=msg,
        )
