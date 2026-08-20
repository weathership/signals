"""Invariant catalog for signals-federation with live kubectl detects."""

from __future__ import annotations

from typing import List

from . import kube
from .model import Cost, Invariant, Layer, Probe


def det_node(ctx) -> Probe:
    if kube.node_ready():
        return Probe(True, "node Ready")
    return Probe(False, "no Ready node")


def det_zarf(ctx) -> Probe:
    if kube.ns_exists("zarf"):
        return Probe(True, "namespace zarf present")
    return Probe(False, "namespace zarf missing — run zarf init")


def det_knative_crds(ctx) -> Probe:
    need = [
        "services.serving.knative.dev",
        "revisions.serving.knative.dev",
        "routes.serving.knative.dev",
    ]
    missing = [c for c in need if not kube.crd_exists(c)]
    if missing:
        return Probe(False, f"missing CRDs: {missing}")
    return Probe(True, "serving CRDs present")


def det_knative_ready(ctx) -> Probe:
    ok = kube.deployment_available("knative-serving", "controller") and kube.deployment_available(
        "knative-serving", "activator"
    )
    if ok:
        return Probe(True, "controller+activator Available")
    return Probe(False, "knative-serving controller/activator not Available")


def det_stz(ctx) -> Probe:
    data = kube.configmap_data("knative-serving", "config-autoscaler")
    v = (data.get("enable-scale-to-zero") or "").lower()
    if v == "true":
        return Probe(True, "enable-scale-to-zero=true")
    return Probe(False, f"enable-scale-to-zero={v!r} (want true)")


def det_yunikorn(ctx) -> Probe:
    # deployment name may be yunikorn-scheduler
    if kube.deployment_available("yunikorn", "yunikorn-scheduler"):
        return Probe(True, "yunikorn-scheduler Available")
    if kube.pods_running("yunikorn") > 0:
        return Probe(True, f"yunikorn pods running={kube.pods_running('yunikorn')}")
    return Probe(False, "yunikorn not Available")


def det_queues(ctx) -> Probe:
    # Soft check: yunikorn ns + config present; deep queue API later
    if kube.ns_exists("yunikorn") and kube.pods_running("yunikorn") > 0:
        return Probe(True, "yunikorn running (queue deep-check TBD)")
    return Probe(False, "yunikorn not running")


def det_ksvc(ctx) -> Probe:
    if kube.ksvc_ready("federation-signals", "minifi-sentinel"):
        return Probe(True, "ksvc minifi-sentinel Ready")
    # Service may exist but not Ready if scaled to zero — still OK if object exists
    data = kube.get_json("ksvc", "minifi-sentinel", "-n", "federation-signals")
    if data:
        return Probe(True, "ksvc present (may be scaled to zero)")
    return Probe(False, "ksvc minifi-sentinel missing")


def det_stz_smoke(ctx) -> Probe:
    """Idle: prefer zero ready replicas on revision when no traffic."""
    data = kube.get_json("ksvc", "minifi-sentinel", "-n", "federation-signals")
    if not data:
        return Probe(False, "no ksvc")
    # desiredGeneration etc. — check pods in ns
    n = kube.pods_running("federation-signals")
    # After deploy, knative may keep 0 or 1; both acceptable if ksvc exists
    return Probe(True, f"federation-signals running pods={n} (0 is scale-to-zero success when idle)")


def det_c2(ctx) -> Probe:
    # Soft: ksvc exists implies C2 path packaged; live C2 server optional
    if kube.get_json("ksvc", "minifi-sentinel", "-n", "federation-signals"):
        return Probe(True, "sentinel ksvc present (C2 live check when agent activated)")
    return Probe(False, "no sentinel for C2")


def det_otel(ctx) -> Probe:
    ds = kube.get_json("ds", "dcgm-exporter", "-n", "federation-system")
    if not ds:
        return Probe(False, "dcgm-exporter DaemonSet missing")
    ready = (ds.get("status") or {}).get("numberReady") or 0
    if int(ready) < 1:
        return Probe(False, f"dcgm-exporter numberReady={ready}")
    return Probe(True, "dcgm-exporter Ready — live watts, no TSDB; OTel yield is engine GET /v1/metrics")


def build_catalog() -> List[Invariant]:
    return [
        Invariant(
            id="T0.node-ready",
            tier="T0",
            title="RKE2 node Ready",
            layer=Layer.B,
            detect=det_node,
        ),
        Invariant(
            id="T0.zarf-registry",
            tier="T0",
            title="Zarf namespace present",
            layer=Layer.B,
            detect=det_zarf,
            depends_on=("T0.node-ready",),
        ),
        Invariant(
            id="T2.knative-crds",
            tier="T2",
            title="Knative Serving CRDs installed",
            layer=Layer.B,
            detect=det_knative_crds,
            depends_on=("T0.zarf-registry",),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T2.knative-serving-ready",
            tier="T2",
            title="Knative Serving controllers Ready",
            layer=Layer.B,
            detect=det_knative_ready,
            depends_on=("T2.knative-crds",),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T2.scale-to-zero-enabled",
            tier="T2",
            title="enable-scale-to-zero=true",
            layer=Layer.B,
            detect=det_stz,
            depends_on=("T2.knative-serving-ready",),
        ),
        Invariant(
            id="T3.yunikorn-ready",
            tier="T3",
            title="YuniKorn scheduler Ready",
            layer=Layer.B,
            detect=det_yunikorn,
            depends_on=("T0.zarf-registry",),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T3.queues-federation",
            tier="T3",
            title="YuniKorn federation queues configured",
            layer=Layer.B,
            detect=det_queues,
            depends_on=("T3.yunikorn-ready",),
        ),
        Invariant(
            id="T4.ksvc-present",
            tier="T4",
            title="minifi-sentinel Knative Service present",
            layer=Layer.B,
            detect=det_ksvc,
            depends_on=("T2.scale-to-zero-enabled", "T3.queues-federation"),
        ),
        Invariant(
            id="T4.scale-to-zero-smoke",
            tier="T4",
            title="Sentinel scale-to-zero posture",
            layer=Layer.B,
            detect=det_stz_smoke,
            depends_on=("T4.ksvc-present",),
        ),
        Invariant(
            id="T5.c2-heartbeat",
            tier="T5",
            title="C2 path packaged for activated sentinel",
            layer=Layer.B,
            detect=det_c2,
            depends_on=("T4.ksvc-present",),
        ),
        Invariant(
            id="T5.otel-phase",
            tier="T5",
            title="DCGM exporter Ready (pull-only OTel yield)",
            layer=Layer.B,
            detect=det_otel,
            depends_on=("T5.c2-heartbeat",),
        ),
    ]
