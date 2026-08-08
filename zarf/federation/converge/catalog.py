"""Invariant catalog for signals-federation (stubs → fill as components land).

Tiers mirror minifi_sentinels.md implementation phases and cybersec converge
discipline. detect() callables are placeholders until kube helpers land.
"""

from __future__ import annotations

from typing import List

from .model import Cost, Invariant, Layer, Probe


def _todo(ctx) -> Probe:
    return Probe(ok=False, detail="not implemented — scaffold only")


def _ok_scaffold(ctx) -> Probe:
    """Scaffold: package tree present (not cluster state)."""
    return Probe(ok=True, detail="scaffold invariant — replace with real detect")


def build_catalog() -> List[Invariant]:
    """Ordered catalog; engine will topo-sort on depends_on when full."""
    return [
        # ── T0 node / zarf substrate ─────────────────────────────────────
        Invariant(
            id="T0.node-ready",
            tier="T0",
            title="RKE2 node Ready",
            layer=Layer.B,
            detect=_todo,
            depends_on=(),
            manual_hint="kubectl get nodes; fix RKE2 before federation deploy",
        ),
        Invariant(
            id="T0.zarf-registry",
            tier="T0",
            title="Zarf registry healthy (shared with other packages)",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T0.node-ready",),
            manual_hint="zarf init / registry PVC — do not delete Layer-A packages",
        ),
        # ── T1 package artifacts (Layer A) ───────────────────────────────
        Invariant(
            id="T1.package-present",
            tier="T1",
            title="signals-federation Zarf package on node (Layer A)",
            layer=Layer.A,
            detect=_todo,
            depends_on=("T0.node-ready",),
            manual_hint="Transport zarf-package-signals-federation-amd64-*.tar.zst",
        ),
        # ── T2 Knative ───────────────────────────────────────────────────
        Invariant(
            id="T2.knative-crds",
            tier="T2",
            title="Knative Serving CRDs installed",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T0.zarf-registry", "T1.package-present"),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T2.knative-serving-ready",
            tier="T2",
            title="Knative Serving controllers Ready",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T2.knative-crds",),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T2.scale-to-zero-enabled",
            tier="T2",
            title="config-autoscaler enable-scale-to-zero=true (KPA)",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T2.knative-serving-ready",),
            manual_hint="https://knative.dev/docs/serving/autoscaling/scale-to-zero/",
        ),
        # ── T3 YuniKorn ──────────────────────────────────────────────────
        Invariant(
            id="T3.yunikorn-ready",
            tier="T3",
            title="YuniKorn scheduler Ready",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T0.zarf-registry", "T1.package-present"),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T3.queues-federation",
            tier="T3",
            title="Queues root.{aegir,atelier,gaius,signals,hermes}",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T3.yunikorn-ready",),
        ),
        # ── T4 MiNiFi sentinels ──────────────────────────────────────────
        Invariant(
            id="T4.sentinel-image",
            tier="T4",
            title="minifi-sentinel image in Zarf registry",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T0.zarf-registry", "T1.package-present"),
            cost=Cost.EXPENSIVE,
        ),
        Invariant(
            id="T4.ksvc-present",
            tier="T4",
            title="Knative Services for minifi-sentinel exist",
            layer=Layer.B,
            detect=_todo,
            depends_on=(
                "T2.scale-to-zero-enabled",
                "T3.queues-federation",
                "T4.sentinel-image",
            ),
        ),
        Invariant(
            id="T4.scale-to-zero-smoke",
            tier="T4",
            title="Idle sentinel Service scales to zero pods",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T4.ksvc-present",),
        ),
        # ── T5 coordination ──────────────────────────────────────────────
        Invariant(
            id="T5.c2-heartbeat",
            tier="T5",
            title="MiNiFi C2 heartbeat when sentinel activated",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T4.ksvc-present",),
        ),
        Invariant(
            id="T5.otel-phase",
            tier="T5",
            title="OTel federation.phase attributes present under load",
            layer=Layer.B,
            detect=_todo,
            depends_on=("T5.c2-heartbeat",),
        ),
        # Scaffold self-check (package tree)
        Invariant(
            id="T0.scaffold-package-tree",
            tier="T0",
            title="zarf/federation tree present in repo (dev)",
            layer=Layer.B,
            detect=_ok_scaffold,
            depends_on=(),
        ),
    ]
