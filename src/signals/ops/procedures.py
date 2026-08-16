"""Named methods. First: k8s.product-redeploy."""

from __future__ import annotations

from collections.abc import Callable

from signals.ops.fsm import ProcedureFSM

K8S_PRODUCT_REDEPLOY = "k8s.product-redeploy"
DATA_PRODUCT_HISTORY_REVIEW = "data-product.history-review"
DATA_PRODUCT_TIER_UPKEEP = "data-product.tier-upkeep"

# Holding: identity is still owned; do not start the next epoch.
# Completing (YK) is holding even when pods are gone.
_HOLDING = frozenset(
    {"scaling", "desired_zero", "pods_draining", "apps_completing"}
)

_STATES = (
    "start",
    "substrate_ready",
    "scaling",
    "desired_zero",
    "pods_draining",
    "pods_quiet",
    "apps_completing",
    "apps_completed",
    "applying",
    "verifying",
    "placed",
    "failed",
)

_TRANSITIONS = {
    "start": ("substrate_ready", "failed"),
    "substrate_ready": ("scaling", "failed"),
    "scaling": ("desired_zero", "failed"),
    "desired_zero": ("pods_draining", "pods_quiet", "failed"),
    "pods_draining": ("pods_quiet", "failed"),
    "pods_quiet": ("apps_completing", "apps_completed", "failed"),
    "apps_completing": ("apps_completed", "failed"),
    "apps_completed": ("applying", "failed"),
    "applying": ("verifying", "failed"),
    "verifying": ("placed", "failed"),
    "placed": (),
    "failed": (),
}

# Probes: which FSM states make their proposition well-posed.
PROBE_WELL_POSED: dict[str, frozenset[str]] = {
    "probe:substrate-ready": frozenset({"start", "substrate_ready"}),
    "probe:desired-zero": frozenset({"scaling", "desired_zero"}),
    "probe:pods-quiet": frozenset({"desired_zero", "pods_draining", "pods_quiet"}),
    "probe:yk-completed": frozenset(
        {"pods_quiet", "apps_completing", "apps_completed"}
    ),
    "probe:placed-on-platform": frozenset({"verifying", "placed"}),
    "probe:jobs-quiet": frozenset(
        {"scaling", "desired_zero", "pods_draining", "pods_quiet"}
    ),
    "probe:tier-next-week-added": frozenset({"adding"}),
    "probe:tier-copy-complete": frozenset({"copying"}),
    "probe:tier-verify-ok": frozenset({"verifying"}),
    "probe:tier-range-dropped": frozenset({"dropping", "settled"}),
}

PRODUCT_NS = ("metaflow", "airflow", "signals-events")
STALE_YK_APPS = (
    "yunikorn-metaflow-platform",
    "yunikorn-airflow-platform",
    "yunikorn-airflow-autogen",
    "yunikorn-eventing-platform",
    "yunikorn-signals-events-autogen",
    "minifi-sentinel-signals",
)
YK_BLOCKING = frozenset(
    {
        "new",
        "accepted",
        "starting",
        "running",
        "completing",
        "failing",
        "resuming",
        "unknown",
    }
)
YK_DONE = frozenset({"missing", "completed", "failed", "rejected"})

SUBSTRATE_FILES = (
    "zarf/federation/manifests/yunikorn/values.yaml",
    "zarf/federation/manifests/yunikorn/yunikorn-rendered.yaml",
    "zarf/federation/manifests/knative/serving-crds.yaml",
    "zarf/federation/manifests/knative/serving-core.yaml",
    "zarf/federation/manifests/knative/config-autoscaler-scale-to-zero.yaml",
    "zarf/federation/manifests/knative/kourier.yaml",
    "zarf/federation/manifests/knative/config-network-kourier.yaml",
    "zarf/federation/manifests/knative/eventing-crds.yaml",
    "zarf/federation/manifests/knative/eventing-core.yaml",
    "zarf/federation/manifests/knative/in-memory-channel.yaml",
    "zarf/federation/manifests/knative/mt-channel-broker.yaml",
)

SCALE_WAIT_S = 90
YK_WAIT_S = 180


def k8s_product_redeploy() -> ProcedureFSM:
    return ProcedureFSM(
        name=K8S_PRODUCT_REDEPLOY,
        states=_STATES,
        transitions=_TRANSITIONS,
        holding=_HOLDING,
        terminals=frozenset({"placed", "failed"}),
        start="start",
        current="start",
    )


def describe_method(fsm: ProcedureFSM) -> dict:
    """Full method document: FSM + which probes are well-posed where."""
    from signals.ops.implicit import MACHINES

    doc = fsm.as_method()
    doc["probes"] = {k: sorted(v) for k, v in PROBE_WELL_POSED.items()}
    doc["implicit"] = {
        name: {
            "states": list(m.states),
            "holding": sorted(m.holding),
            "terminals": sorted(m.terminals),
        }
        for name, m in MACHINES.items()
    }
    return doc


def data_product_history_review() -> ProcedureFSM:
    """Agent review of a data-product update (quality, lineage, delta, nominal)."""
    return ProcedureFSM(
        name=DATA_PRODUCT_HISTORY_REVIEW,
        states=(
            "start",
            "event_received",
            "reviewing",
            "understood",
            "failed",
        ),
        transitions={
            "start": ("event_received", "failed"),
            "event_received": ("reviewing", "failed"),
            "reviewing": ("understood", "failed"),
            "understood": (),
            "failed": (),
        },
        holding=frozenset({"event_received", "reviewing"}),
        terminals=frozenset({"understood", "failed"}),
        start="start",
        current="start",
    )


def data_product_tier_upkeep() -> ProcedureFSM:
    """Weekly ADD + 4-week settle. Do not DROP from a holding verify."""
    return ProcedureFSM(
        name=DATA_PRODUCT_TIER_UPKEEP,
        states=(
            "start",
            "adding",
            "copying",
            "verifying",
            "dropping",
            "settled",
            "failed",
        ),
        transitions={
            "start": ("adding", "failed"),
            "adding": ("copying", "settled", "failed"),
            "copying": ("verifying", "failed"),
            "verifying": ("dropping", "failed"),
            "dropping": ("settled", "failed"),
            "settled": (),
            "failed": (),
        },
        holding=frozenset({"adding", "copying", "verifying", "dropping"}),
        terminals=frozenset({"settled", "failed"}),
        start="start",
        current="start",
    )


METHODS: dict[str, Callable[[], ProcedureFSM]] = {
    K8S_PRODUCT_REDEPLOY: k8s_product_redeploy,
    DATA_PRODUCT_HISTORY_REVIEW: data_product_history_review,
    DATA_PRODUCT_TIER_UPKEEP: data_product_tier_upkeep,
}


def get_method(name: str) -> ProcedureFSM:
    factory = METHODS.get(name)
    if factory is None:
        known = ", ".join(sorted(METHODS))
        raise KeyError(f"unknown method {name!r} (have {known})")
    return factory()
