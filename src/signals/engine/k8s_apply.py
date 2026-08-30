"""Engine-private ConfigMap apply for YuniKorn queues.yaml (kubectl).

Product clients never call this — only PromoteScratch does.

Lab/RKE2: ``yunikorn-configs`` overrides ``yunikorn-defaults`` at runtime
(see zarf federation values). Prefer configs; fall back to defaults when
configs is missing.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("signals.engine.k8s_apply")


class ApplyError(Exception):
    """ConfigMap apply failed or kubectl unavailable."""


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    message: str
    target: str = ""  # namespace/name
    dry_run: bool = False


@dataclass(frozen=True)
class ApplyConfig:
    enabled: bool = True
    namespace: str = "yunikorn"
    configmap: str = "yunikorn-configs"
    fallback_configmap: str = "yunikorn-defaults"
    key: str = "queues.yaml"
    kubeconfig: str | None = None
    context: str | None = None
    kubectl: str = "kubectl"

    @classmethod
    def from_env(cls) -> "ApplyConfig":
        enabled_raw = os.environ.get("SIGNALS_YK_APPLY_ENABLED", "1").strip().lower()
        enabled = enabled_raw not in ("0", "false", "no", "off")
        return cls(
            enabled=enabled,
            namespace=os.environ.get("SIGNALS_YK_CM_NAMESPACE", "yunikorn"),
            configmap=os.environ.get("SIGNALS_YK_CM_NAME", "yunikorn-configs"),
            fallback_configmap=os.environ.get(
                "SIGNALS_YK_CM_FALLBACK", "yunikorn-defaults"
            ),
            key=os.environ.get("SIGNALS_YK_CM_KEY", "queues.yaml"),
            kubeconfig=resolve_kubeconfig(),
            context=os.environ.get("SIGNALS_YK_KUBE_CONTEXT"),
            kubectl=os.environ.get("SIGNALS_YK_KUBECTL", "kubectl"),
        )


def resolve_kubeconfig() -> str | None:
    """First READABLE of SIGNALS_YK_KUBECONFIG, KUBECONFIG, ~/.kube/{rke2.yaml,config}.

    An unreadable path must never win: a root-only /etc/rancher/rke2/rke2.yaml
    leaked into the devenv daemon's environment silently broke every
    PromoteScratch (and with it queue-share APPLIED) from 2026-08-28 to
    2026-08-30. The explicit SIGNALS_YK_KUBECONFIG outranks the ambient
    KUBECONFIG; both are skipped, loudly, when not readable.
    """
    candidates = (
        ("SIGNALS_YK_KUBECONFIG", os.environ.get("SIGNALS_YK_KUBECONFIG")),
        ("KUBECONFIG", os.environ.get("KUBECONFIG")),
        ("default", os.path.expanduser("~/.kube/rke2.yaml")),
        ("default", os.path.expanduser("~/.kube/config")),
    )
    for source, cand in candidates:
        if not cand:
            continue
        if os.access(cand, os.R_OK):
            return cand
        if source != "default":
            log.warning("%s=%s is not readable — skipping", source, cand)
    return None  # let kubectl resolve; --kubeconfig is simply omitted


def _kubectl_base(cfg: ApplyConfig) -> list[str]:
    exe = cfg.kubectl
    if not shutil.which(exe) and exe == "kubectl":
        raise ApplyError("kubectl not found on PATH")
    cmd = [exe]
    if cfg.kubeconfig:
        cmd += ["--kubeconfig", cfg.kubeconfig]
    if cfg.context:
        cmd += ["--context", cfg.context]
    return cmd


def _run(cmd: list[str], *, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    log.debug("k8s: %s", " ".join(cmd))
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ApplyError(f"kubectl timed out: {' '.join(cmd)}") from e
    except OSError as e:
        raise ApplyError(f"kubectl failed to start: {e}") from e


def _get_cm_yaml(cfg: ApplyConfig, name: str) -> dict[str, Any] | None:
    cmd = _kubectl_base(cfg) + [
        "get",
        "configmap",
        name,
        "-n",
        cfg.namespace,
        "-o",
        "yaml",
    ]
    r = _run(cmd)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "NotFound" in err or "not found" in err.lower():
            return None
        raise ApplyError(f"get configmap/{name}: {err[:500]}")
    try:
        doc = yaml.safe_load(r.stdout)
    except yaml.YAMLError as e:
        raise ApplyError(f"parse configmap/{name} yaml: {e}") from e
    if not isinstance(doc, dict):
        raise ApplyError(f"configmap/{name}: unexpected document type")
    return doc


def resolve_target_configmap(cfg: ApplyConfig) -> str:
    """Prefer primary CM; fall back if missing."""
    if _get_cm_yaml(cfg, cfg.configmap) is not None:
        return cfg.configmap
    if cfg.fallback_configmap and _get_cm_yaml(cfg, cfg.fallback_configmap) is not None:
        log.warning(
            "configmap/%s not found; using fallback %s",
            cfg.configmap,
            cfg.fallback_configmap,
        )
        return cfg.fallback_configmap
    raise ApplyError(
        f"neither configmap/{cfg.configmap} nor "
        f"configmap/{cfg.fallback_configmap} found in ns/{cfg.namespace}"
    )


def apply_queues_yaml(
    yaml_body: str,
    cfg: ApplyConfig | None = None,
    *,
    dry_run: bool = False,
) -> ApplyResult:
    """Patch ConfigMap data[queues.yaml] and apply.

    Preserves other keys (e.g. admissionController.*). Strips resourceVersion
    conflict fields via server-side apply of a cleaned object.
    """
    cfg = cfg or ApplyConfig.from_env()
    if not cfg.enabled:
        return ApplyResult(
            ok=True,
            message="apply disabled (SIGNALS_YK_APPLY_ENABLED=0); local projection only",
            dry_run=dry_run,
        )

    name = resolve_target_configmap(cfg)
    doc = _get_cm_yaml(cfg, name)
    if doc is None:
        raise ApplyError(f"configmap/{name} disappeared during apply")

    data = doc.get("data")
    if not isinstance(data, dict):
        data = {}
        doc["data"] = data
    data[cfg.key] = yaml_body if yaml_body.endswith("\n") else yaml_body + "\n"

    # Drop fields that confuse client apply / ownership
    meta = doc.setdefault("metadata", {})
    if isinstance(meta, dict):
        for k in (
            "resourceVersion",
            "uid",
            "creationTimestamp",
            "managedFields",
            "generation",
            "selfLink",
        ):
            meta.pop(k, None)
    doc.pop("status", None)
    # Ensure identity
    meta["name"] = name
    meta["namespace"] = cfg.namespace
    doc["apiVersion"] = doc.get("apiVersion") or "v1"
    doc["kind"] = "ConfigMap"

    with tempfile.TemporaryDirectory(prefix="signals-yk-apply-") as td:
        path = Path(td) / "cm.yaml"
        path.write_text(
            yaml.safe_dump(doc, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        cmd = _kubectl_base(cfg) + ["apply", "-f", str(path), "-n", cfg.namespace]
        if dry_run:
            cmd.append("--dry-run=server")
        r = _run(cmd, timeout=90.0)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        target = f"{cfg.namespace}/{name}"
        if r.returncode != 0:
            raise ApplyError(f"kubectl apply {target}: {out[:800]}")
        msg = out or (
            f"{'dry-run ' if dry_run else ''}applied queues.yaml → configmap/{name}"
        )
        return ApplyResult(ok=True, message=msg, target=target, dry_run=dry_run)
