"""Walk k8s.product-redeploy. Fail closed. Score every probe."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

from signals.ops.fsm import IllegalTransition, ProcedureFSM
from signals.ops.kube import kubectl, pick_kubeconfig, yk_app_state, yk_queue_apps
from signals.ops.ledger import ObservationLedger
from signals.ops.probes import claim, risk_line
from signals.ops.procedures import (
    PRODUCT_NS,
    SCALE_WAIT_S,
    STALE_YK_APPS,
    SUBSTRATE_FILES,
    YK_BLOCKING,
    YK_DONE,
    YK_WAIT_S,
    k8s_product_redeploy,
)

STATE_NS = "federation-system"
STATE_CM = "signals-redeploy-state"


class RedeployError(Exception):
    pass


def _log(msg: str) -> None:
    print(f"redeploy: {msg}", flush=True)


def _tagged_claim(ledger, fsm, observer, proposition, observe, **kwargs):
    """claim() plus implicit K8s/YK cell at this instant."""
    snap = {
        "probe:yk-completed": ("yk.application", _implicit_yk),
        "probe:placed-on-platform": ("yk.application", _implicit_yk),
        "probe:desired-zero": ("k8s.deploy", _implicit_deploy),
        "probe:pods-quiet": ("k8s.pod", _implicit_pod),
        "probe:jobs-quiet": ("k8s.job", _implicit_job),
    }.get(observer)
    impl_fsm, impl_state = "", ""
    if snap:
        impl_fsm, fn = snap
        impl_state, hint = fn()
        _log(f"  implicit {impl_fsm}={impl_state} ({hint[:120]})")
    return claim(
        ledger,
        fsm,
        observer,
        proposition,
        observe,
        implicit_fsm=impl_fsm,
        implicit_state=impl_state,
        **kwargs,
    )


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _yk_url() -> str:
    return os.environ.get("SIGNALS_YK_API_URL", "http://127.0.0.1:30080").rstrip("/")


def _fail(fsm: ProcedureFSM, msg: str) -> None:
    if fsm.allowed("failed"):
        fsm.step("failed")
    raise RedeployError(msg)


def _ns_exists(ns: str) -> bool:
    return kubectl("get", "ns", ns).returncode == 0


def _deploy_names(ns: str) -> list[str]:
    r = kubectl("get", "deploy", "-n", ns, "-o", "name")
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _desired_replicas(ns: str, deploy: str) -> int:
    r = kubectl("get", deploy, "-n", ns, "-o", "jsonpath={.spec.replicas}")
    if r.returncode != 0 or not r.stdout.strip():
        return 1
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 1


def _ns_desired_zero(ns: str) -> bool:
    names = _deploy_names(ns)
    if not names:
        return True
    return all(_desired_replicas(ns, d) == 0 for d in names)


def _product_pod_names(ns: str) -> list[str]:
    r = kubectl("get", "pods", "-n", ns, "-o", "json")
    if r.returncode != 0 or not r.stdout.strip():
        return []
    import json

    try:
        data = json.loads(r.stdout)
    except ValueError:
        return []
    out: list[str] = []
    for p in data.get("items") or []:
        phase = (p.get("status") or {}).get("phase") or ""
        if phase in ("Succeeded", "Failed"):
            continue
        refs = (p.get("metadata") or {}).get("ownerReferences") or []
        kinds = {x.get("kind") for x in refs}
        if kinds & {"ReplicaSet", "Deployment", "Job"}:
            out.append(p["metadata"]["name"])
    return out


def _implicit_yk() -> tuple[str, str]:
    from signals.ops.implicit import YK_APPLICATION

    states = [yk_app_state(app, _yk_url()) for app in STALE_YK_APPS]
    cell = YK_APPLICATION.reduce(states)
    ev = ",".join(f"{a}={s}" for a, s in zip(STALE_YK_APPS, states, strict=False))
    return cell, ev or "none"


def _implicit_deploy() -> tuple[str, str]:
    from signals.ops.implicit import K8S_DEPLOY

    cells: list[str] = []
    bits: list[str] = []
    for ns in PRODUCT_NS:
        if not _ns_exists(ns):
            cells.append("absent")
            continue
        names = _deploy_names(ns)
        if not names:
            cells.append("absent")
            continue
        if _ns_desired_zero(ns):
            cells.append("desired_zero")
        else:
            cells.append("desired_positive")
        bits.append(f"{ns}={cells[-1]}")
    return K8S_DEPLOY.reduce(cells), ",".join(bits)


def _implicit_pod() -> tuple[str, str]:
    from signals.ops.implicit import K8S_POD

    cells: list[str] = []
    bits: list[str] = []
    for ns in PRODUCT_NS:
        if not _ns_exists(ns):
            continue
        names = _product_pod_names(ns)
        if not names:
            cells.append("absent")
        else:
            cells.append("running")
            bits.append(f"{ns}={len(names)}")
    if not cells:
        return "absent", "no-ns"
    return K8S_POD.reduce(cells), ",".join(bits) or "absent"


def _implicit_job() -> tuple[str, str]:
    from signals.ops.implicit import K8S_JOB

    cells: list[str] = []
    bits: list[str] = []
    for ns in PRODUCT_NS:
        if not _ns_exists(ns):
            continue
        r = kubectl("get", "job", "-n", ns, "-o", "jsonpath={.items[*].metadata.name}")
        names = [x for x in (r.stdout or "").split() if x]
        if names:
            cells.append("active")
            bits.extend(f"{ns}/{n}" for n in names)
        else:
            cells.append("absent")
    if not cells:
        return "absent", "no-ns"
    return K8S_JOB.reduce(cells), ",".join(bits) or "absent"


def _substrate_hash(root: Path) -> str:
    h = hashlib.sha256()
    for rel in SUBSTRATE_FILES:
        p = root / rel
        if not p.is_file():
            continue
        h.update(p.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


def _stored_hash() -> str:
    r = kubectl(
        "get",
        "cm",
        STATE_CM,
        "-n",
        STATE_NS,
        "-o",
        "jsonpath={.data.substrate-hash}",
    )
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _save_hash(digest: str) -> None:
    if kubectl("get", "ns", STATE_NS).returncode != 0:
        return
    spec = (
        "apiVersion: v1\nkind: ConfigMap\n"
        f"metadata:\n  name: {STATE_CM}\n  namespace: {STATE_NS}\n"
        f"data:\n  substrate-hash: {digest}\n"
    )
    subprocess.run(
        ["kubectl", "--kubeconfig", pick_kubeconfig(), "apply", "-f", "-"],
        input=spec,
        text=True,
        check=False,
        capture_output=True,
    )


def _maybe_substrate(root: Path, fsm: ProcedureFSM, ledger: ObservationLedger) -> None:
    missing = (
        kubectl("get", "deploy", "yunikorn-scheduler", "-n", "yunikorn").returncode != 0
        or kubectl("get", "deploy", "controller", "-n", "knative-serving").returncode != 0
    )
    now = _substrate_hash(root)
    prev = _stored_hash()

    def observe() -> tuple[bool, str]:
        if missing:
            return False, "YK or Knative Serving deploy missing"
        if now and now != prev:
            return False, "substrate manifests changed"
        return True, "unchanged"

    ok, ev = _tagged_claim(
        ledger, fsm, "probe:substrate-ready", "substrate-ready", observe
    )
    _log(risk_line(ledger, fsm, "probe:substrate-ready"))
    if ok:
        _log(f"substrate unchanged — skip YK/Knative ({ev})")
        return
    if missing:
        _log("substrate missing — federation-ready")
        subprocess.run(
            ["bash", str(root / "scripts" / "federation_preflight.sh")],
            cwd=root,
            check=True,
        )
    else:
        _log("substrate manifests changed — apply")
        files = [
            root / "zarf/federation/manifests/knative" / name
            for name in (
                "serving-crds.yaml",
                "serving-core.yaml",
                "config-autoscaler-scale-to-zero.yaml",
                "kourier.yaml",
                "config-network-kourier.yaml",
                "eventing-crds.yaml",
                "eventing-core.yaml",
                "in-memory-channel.yaml",
                "mt-channel-broker.yaml",
            )
        ]
        for f in files:
            if f.is_file():
                _log(f"  apply {f.relative_to(root)}")
                kubectl("apply", "-f", str(f))
        if (
            kubectl("get", "deploy", "yunikorn-scheduler", "-n", "yunikorn").returncode
            != 0
        ):
            subprocess.run(
                ["bash", str(root / "scripts" / "federation_preflight.sh")],
                cwd=root,
                check=True,
            )
    _save_hash(now)


def _scale_ns_zero(ns: str, fsm: ProcedureFSM, ledger: ObservationLedger) -> None:
    if not _ns_exists(ns):
        _log(f"ns/{ns} absent — skip scale")
        return
    _log(f"scale {ns} deployments → 0")
    for d in _deploy_names(ns):
        kubectl("scale", d, "-n", ns, "--replicas=0")
    _hold_product_zero()

    deadline = time.monotonic() + SCALE_WAIT_S
    while time.monotonic() < deadline:
        _hold_product_zero()
        desired_ok = _ns_desired_zero(ns)
        pods = _product_pod_names(ns)
        if desired_ok and not pods:
            _tagged_claim(
                ledger,
                fsm,
                "probe:desired-zero",
                "desired-zero",
                lambda: (True, f"{ns} desired=0"),
            )
            return
        time.sleep(2)

    if _ns_desired_zero(ns):
        leftover = _product_pod_names(ns)
        if leftover:
            _log(f"  force-delete leftover pods in {ns}")
            kubectl(
                "delete",
                "pod",
                *leftover,
                "-n",
                ns,
                "--grace-period=0",
                "--force",
            )
            time.sleep(2)
            if not _product_pod_names(ns):
                _tagged_claim(
                    ledger,
                    fsm,
                    "probe:desired-zero",
                    "desired-zero",
                    lambda: (True, f"{ns} desired=0 after force-delete"),
                )
                return

    truth, ev = _tagged_claim(
        ledger,
        fsm,
        "probe:desired-zero",
        "desired-zero",
        lambda: (False, f"{ns} not quiet: pods={_product_pod_names(ns)}"),
    )
    _ = truth
    _fail(fsm, f"ns/{ns} not at zero ({ev})")


def _yk_blocking() -> list[str]:
    left = []
    for app in STALE_YK_APPS:
        st = yk_app_state(app, _yk_url()).lower()
        if st in YK_DONE:
            continue
        if st in YK_BLOCKING or st not in YK_DONE:
            left.append(f"{app}:{st}")
    return left


def _hold_product_zero() -> None:
    """Re-assert replicas=0 and delete Jobs. Helm hooks keep YK Running."""
    for ns in PRODUCT_NS:
        if not _ns_exists(ns):
            continue
        for d in _deploy_names(ns):
            if _desired_replicas(ns, d) != 0:
                _log(f"  {d} drifted — scale 0 again")
                kubectl("scale", d, "-n", ns, "--replicas=0")
        jobs = kubectl("get", "job", "-n", ns, "-o", "name")
        if jobs.returncode == 0:
            for job in jobs.stdout.splitlines():
                job = job.strip()
                if job:
                    _log(f"  delete {job}")
                    kubectl("delete", job, "-n", ns, "--wait=false")


def _wait_yk(fsm: ProcedureFSM, ledger: ObservationLedger) -> None:
    deadline = time.monotonic() + YK_WAIT_S
    while time.monotonic() < deadline:
        _hold_product_zero()
        left = _yk_blocking()
        if not left:
            ok, ev = _tagged_claim(
                ledger,
                fsm,
                "probe:yk-completed",
                "yk-apps-completed",
                lambda: (True, "no blocking Applications"),
            )
            if not ok:
                _fail(fsm, ev)
            _log("YK product Applications completed")
            return
        _log(f"waiting YK complete: {' '.join(left)}")
        if any(x.endswith(":completing") for x in left) and fsm.current == "pods_quiet":
            if fsm.allowed("apps_completing"):
                fsm.step("apps_completing")
                _log("FSM → apps_completing (holding; do not resubmit)")
        time.sleep(4)

    _tagged_claim(
        ledger,
        fsm,
        "probe:yk-completed",
        "yk-apps-completed",
        lambda: (False, f"still blocking: {_yk_blocking()}"),
    )
    _fail(
        fsm,
        f"YK Applications still blocking after {YK_WAIT_S}s: {_yk_blocking()}. "
        "Refusing to resubmit same app-id.",
    )


def _apply_product(root: Path) -> None:
    _log("Metaflow")
    subprocess.run(
        ["bash", str(root / "scripts" / "metaflow_platform_bootstrap.sh")],
        cwd=root,
        check=True,
    )
    _log("Airflow")
    subprocess.run(
        ["bash", str(root / "scripts" / "airflow_platform_bootstrap.sh")],
        cwd=root,
        check=True,
    )
    _log("platform Eventing (signals-events)")
    if kubectl("get", "ns", "knative-eventing").returncode == 0:
        ev = root / "config" / "k8s" / "eventing"
        kubectl("apply", "-f", str(ev / "namespace.yaml"))
        kubectl(
            "annotate",
            "ns",
            "signals-events",
            "zarf.dev/agent=ignore",
            "--overwrite",
        )
        kubectl("apply", "-f", str(ev / "sink-configmap.yaml"))
        kubectl("apply", "-f", str(ev / "sink-deployment.yaml"))
        kubectl("apply", "-f", str(ev / "broker-trigger.yaml"))
        kubectl(
            "-n",
            "signals-events",
            "rollout",
            "status",
            "deploy/airflow-dag-trigger",
            "--timeout=180s",
        )
    else:
        _log("knative-eventing missing — eventing bootstrap")
        subprocess.run(
            ["bash", str(root / "scripts" / "knative_eventing_bootstrap.sh")],
            cwd=root,
            check=True,
        )
    ksvc = root / "zarf/federation/manifests/sentinels/minifi-ksvc-signals.yaml"
    if kubectl("get", "ns", "knative-serving").returncode == 0 and ksvc.is_file():
        if "###ZARF_REGISTRY###" in ksvc.read_text(encoding="utf-8"):
            _log("sentinel ksvc still Zarf-templated — skip apply")
        else:
            _log("sentinel ksvc")
            kubectl("apply", "-f", str(ksvc))


def _verify_placed(fsm: ProcedureFSM, ledger: ObservationLedger) -> None:
    def observe() -> tuple[bool, str]:
        apps = yk_queue_apps("root.platform", _yk_url())
        ids = [
            str(a.get("applicationID") or a.get("applicationId") or "")
            for a in apps
        ]
        want = {
            "yunikorn-metaflow-platform",
            "yunikorn-airflow-platform",
            "yunikorn-eventing-platform",
        }
        have = want.intersection(ids)
        return bool(have), "platform=" + ",".join(sorted(ids))

    ok, ev = _tagged_claim(
        ledger, fsm, "probe:placed-on-platform", "placed-on-platform", observe
    )
    _log(ev)
    if not ok:
        _fail(fsm, "no product Application on root.platform after apply")
    mf = yk_app_state("yunikorn-metaflow-platform", _yk_url())
    qapps = yk_queue_apps("root.default", _yk_url())
    default_ids = {
        str(a.get("applicationID") or a.get("applicationId")) for a in qapps
    }
    if (
        "yunikorn-metaflow-platform" in default_ids
        and mf.lower() not in YK_DONE
        and mf.lower() != "completed"
    ):
        # Running on default after apply = reattach; that probe was wrong.
        _tagged_claim(
            ledger,
            fsm,
            "probe:placed-on-platform",
            "metaflow-on-platform",
            lambda: (False, f"metaflow still {mf} on default"),
        )
        _log("WARN: metaflow Application still on root.default (reattach)")


def run(ledger: ObservationLedger | None = None) -> int:
    root = _root()
    os.chdir(root)
    os.environ["KUBECONFIG"] = pick_kubeconfig()
    _log(f"KUBECONFIG={os.environ['KUBECONFIG']}")

    if kubectl("get", "ns").returncode != 0:
        print("ERROR: redeploy: cannot reach cluster", file=sys.stderr)
        return 1

    fsm = k8s_product_redeploy()
    led = ledger or ObservationLedger()
    try:
        _maybe_substrate(root, fsm, led)
        fsm.step("substrate_ready")

        fsm.step("scaling")
        for ns in PRODUCT_NS:
            _scale_ns_zero(ns, fsm, led)
        fsm.step("desired_zero")

        quiet = all(not _product_pod_names(ns) for ns in PRODUCT_NS if _ns_exists(ns))
        ok, ev = _tagged_claim(
            led,
            fsm,
            "probe:pods-quiet",
            "pods-quiet",
            lambda: (quiet, "quiet" if quiet else "pods remain"),
        )
        if not ok:
            fsm.step("pods_draining")
            deadline = time.monotonic() + SCALE_WAIT_S
            while time.monotonic() < deadline:
                _hold_product_zero()
                if all(
                    not _product_pod_names(ns)
                    for ns in PRODUCT_NS
                    if _ns_exists(ns)
                ):
                    break
                time.sleep(2)
            quiet = all(
                not _product_pod_names(ns) for ns in PRODUCT_NS if _ns_exists(ns)
            )
            desired = all(
                _ns_desired_zero(ns) for ns in PRODUCT_NS if _ns_exists(ns)
            )
            ok, ev = _tagged_claim(
                led,
                fsm,
                "probe:pods-quiet",
                "pods-quiet",
                lambda: (
                    quiet,
                    "quiet" if quiet else f"pods remain desired0={desired}",
                ),
            )
            # Desired=0 is enough to enter Completing. Residual Terminating
            # pods are not a failed forecast of "will stay empty forever."
            if not desired:
                _fail(fsm, ev)
        fsm.step("pods_quiet")
        _log(risk_line(led, fsm, "probe:yk-completed"))

        _wait_yk(fsm, led)
        if fsm.current != "apps_completed":
            fsm.step("apps_completed")

        fsm.step("applying")
        _apply_product(root)
        gpu = root / "scripts" / "advertise_federation_gpu.sh"
        if gpu.is_file():
            _log("advertise federation.zndx.org/gpu")
            subprocess.run(["bash", str(gpu)], cwd=root, check=False)

        fsm.step("verifying")
        _verify_placed(fsm, led)
        fsm.step("placed")
        _log("OK — k8s.product-redeploy placed")
        for r in led.report(axis="both"):
            if r.get("procedure") != fsm.name:
                continue
            brier = "—" if r["brier"] is None else f"{r['brier']:.3f}"
            impl = ""
            if r.get("implicit_fsm"):
                impl = f" {r['implicit_fsm']}={r.get('implicit_state') or '—'}"
            _log(
                f"brier {r['observer']} @{r['fsm_state']}{impl} "
                f"n={r['resolved']} {brier}"
            )
        return 0
    except (RedeployError, IllegalTransition, subprocess.CalledProcessError) as e:
        print(f"ERROR: redeploy: {e}", file=sys.stderr)
        return 1
