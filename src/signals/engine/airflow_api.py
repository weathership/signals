"""Airflow 3 REST (API v2) client — the ONLY place Signals talks to Airflow.

Coordination Activities (specification/protocol/coordination_activities.md):
peers never hold this URL or these credentials. A peer ENGINE reaches Airflow
through ``zndx.scheduler.v1.Scheduler`` on this engine; this module is what
that servicer uses underneath.

Fail-fast: every failure is an ``AirflowError`` with a guru code and a
remediation. No placeholder runs, no cached-answer fallback.

Auth: ``POST /auth/token`` (JWT, 24 h at the lab default) then ``Bearer`` on
``/api/v2``; the token is cached and refreshed on 401 or after ``refresh_s``.
Verified against Airflow 3.1.7 on 2026-09-06 (``/openapi.json``):
``GET dagRuns`` filters include ``state`` (array), ``order_by`` (array,
``-run_after`` etc.), ``run_id_pattern`` (substring); ``PATCH dagRuns/{id}``
body ``{state: queued|success|failed, note}``; ``POST dagRuns`` requires the
``logical_date`` key (nullable).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("signals.engine.airflow_api")

GURU_UNREACHABLE = "#AF.00000001.UNREACHABLE"
GURU_AUTH = "#AF.00000002.AUTH"
GURU_DAGMISSING = "#AF.00000003.DAGMISSING"
GURU_API = "#AF.00000004.APIERROR"

DEFAULT_URL = "http://127.0.0.1:30800"
# Env names mirror the Knative sink secret (config/k8s/eventing/sink-deployment.yaml).
ENV_URL = "AIRFLOW_API_URL"
ENV_USER = "AIRFLOW_ADMIN_USER"
ENV_PASSWORD = "AIRFLOW_ADMIN_PASSWORD"


class AirflowError(RuntimeError):
    """Actionable Airflow failure: guru code + what happened + how to fix."""

    def __init__(self, guru: str, what: str, remedy: str):
        self.guru = guru
        self.what = what
        self.remedy = remedy
        super().__init__(f"{guru} {what}\n  Try: {remedy}")


@dataclass(frozen=True)
class AirflowConfig:
    url: str = DEFAULT_URL
    user: str = "admin"
    password: str = "admin"
    timeout_s: float = 20.0
    # Re-authenticate proactively well inside the lab token's 24 h lifetime.
    refresh_s: float = 6 * 3600.0

    @classmethod
    def from_env(cls) -> "AirflowConfig":
        return cls(
            url=(os.environ.get(ENV_URL) or DEFAULT_URL).rstrip("/"),
            user=os.environ.get(ENV_USER) or "admin",
            password=os.environ.get(ENV_PASSWORD) or "admin",
            timeout_s=float(os.environ.get("AIRFLOW_API_TIMEOUT_S", "20")),
        )


class AirflowClient:
    """Thin, synchronous, thread-safe (token cache under a lock)."""

    def __init__(self, cfg: AirflowConfig | None = None, client: httpx.Client | None = None):
        self.cfg = cfg or AirflowConfig.from_env()
        self._http = client or httpx.Client(base_url=self.cfg.url, timeout=self.cfg.timeout_s)
        self._mu = threading.Lock()
        self._token: str | None = None
        self._token_at: float = 0.0

    # ── auth ────────────────────────────────────────────────────────────────
    def _login(self) -> str:
        try:
            r = self._http.post(
                "/auth/token",
                json={"username": self.cfg.user, "password": self.cfg.password},
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise AirflowError(
                GURU_UNREACHABLE,
                f"Airflow API {self.cfg.url} unreachable during login: {e!r}",
                "kubectl -n airflow get pods; check NodePort 30800; "
                "scripts/airflow_platform_bootstrap.sh",
            ) from e
        if r.status_code >= 400:
            raise AirflowError(
                GURU_AUTH,
                f"Airflow login as {self.cfg.user!r} refused: HTTP {r.status_code} {r.text[:200]}",
                f"set {ENV_USER}/{ENV_PASSWORD} to the api-server admin (lab default admin/admin)",
            )
        tok = (r.json() or {}).get("access_token")
        if not tok:
            raise AirflowError(
                GURU_AUTH,
                "Airflow login answered without access_token",
                "check the api-server auth manager (SimpleAuthManager) configuration",
            )
        return str(tok)

    def token(self, *, force: bool = False) -> str:
        with self._mu:
            fresh = self._token and (time.monotonic() - self._token_at) < self.cfg.refresh_s
            if force or not fresh:
                self._token = self._login()
                self._token_at = time.monotonic()
            return self._token  # type: ignore[return-value]

    # ── transport ───────────────────────────────────────────────────────────
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        dag_id: str | None = None,
    ) -> httpx.Response:
        r: httpx.Response | None = None
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token(force=attempt == 2)}"}
            try:
                r = self._http.request(method, path, params=params, json=json, headers=headers)
            except httpx.HTTPError as e:
                raise AirflowError(
                    GURU_UNREACHABLE,
                    f"Airflow API {self.cfg.url} unreachable: {method} {path}: {e!r}",
                    "kubectl -n airflow get pods; check NodePort 30800",
                ) from e
            if r.status_code == 401 and attempt == 1:
                continue  # token expired/rotated → re-login once
            break
        assert r is not None  # the loop either returned a response or raised
        if r.status_code == 404 and dag_id is not None and self._dag_missing(r):
            raise AirflowError(
                GURU_DAGMISSING,
                f"Airflow DAG {dag_id!r} is not registered ({method} {path})",
                "add the DAG file to the signals-airflow-dags ConfigMap and its subPath "
                "mount (scripts/airflow_platform_bootstrap.sh DAG ConfigMap step), then "
                "wait for the dag-processor to parse it",
            )
        if r.status_code >= 400:
            raise AirflowError(
                GURU_API,
                f"Airflow API {method} {path} → HTTP {r.status_code}: {r.text[:300]}",
                "inspect the api-server log: kubectl -n airflow logs deploy/airflow-api-server",
            )
        return r

    @staticmethod
    def _dag_missing(r: httpx.Response) -> bool:
        try:
            detail = str((r.json() or {}).get("detail", ""))
        except ValueError:
            detail = r.text
        return "DAG" in detail and "not found" in detail.lower()

    # ── DAGs ────────────────────────────────────────────────────────────────
    def get_dag(self, dag_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v2/dags/{dag_id}", dag_id=dag_id).json()

    def set_paused(self, dag_id: str, paused: bool) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/v2/dags/{dag_id}",
            params={"update_mask": "is_paused"},
            json={"is_paused": bool(paused)},
            dag_id=dag_id,
        ).json()

    # ── pools ───────────────────────────────────────────────────────────────
    def get_pool(self, name: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"/api/v2/pools/{name}").json()
        except AirflowError as e:
            if e.guru == GURU_API and "HTTP 404" in e.what:
                return None
            raise

    def create_pool(
        self, name: str, *, slots: int, include_deferred: bool = True, description: str = ""
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "slots": int(slots),
            "include_deferred": bool(include_deferred),
            "description": description,
        }
        return self._request("POST", "/api/v2/pools", json=body).json()

    def ensure_pool(
        self, name: str, *, slots: int, include_deferred: bool = True, description: str = ""
    ) -> dict[str, Any]:
        """Create the pool once; an existing pool is left exactly as the operator set it."""
        cur = self.get_pool(name)
        if cur is not None:
            return cur
        log.info("airflow: creating pool %s slots=%s include_deferred=%s", name, slots, include_deferred)
        try:
            return self.create_pool(name, slots=slots, include_deferred=include_deferred, description=description)
        except AirflowError as e:
            if e.guru == GURU_API and "409" in e.what:  # raced with another creator
                got = self.get_pool(name)
                if got is not None:
                    return got
            raise

    # ── dag runs ────────────────────────────────────────────────────────────
    def trigger_dag_run(
        self,
        dag_id: str,
        run_id: str,
        conf: dict[str, Any],
        *,
        logical_date: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """POST a run; a 409 (run_id already exists) returns the existing run."""
        body: dict[str, Any] = {"dag_run_id": run_id, "logical_date": logical_date, "conf": conf}
        if note:
            body["note"] = note
        try:
            return self._request("POST", f"/api/v2/dags/{dag_id}/dagRuns", json=body, dag_id=dag_id).json()
        except AirflowError as e:
            if e.guru == GURU_API and "409" in e.what:
                return self.get_dag_run(dag_id, run_id)
            raise

    def get_dag_run(self, dag_id: str, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v2/dags/{dag_id}/dagRuns/{run_id}", dag_id=dag_id).json()

    def list_dag_runs(
        self,
        dag_id: str,
        *,
        states: list[str] | None = None,
        limit: int = 200,
        order_by: str = "-run_after",
        run_id_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": int(limit), "order_by": [order_by]}
        if states:
            params["state"] = list(states)
        if run_id_pattern:
            params["run_id_pattern"] = run_id_pattern
        data = self._request("GET", f"/api/v2/dags/{dag_id}/dagRuns", params=params, dag_id=dag_id).json()
        rows = data.get("dag_runs") if isinstance(data, dict) else None
        return list(rows or [])

    def patch_dag_run(
        self,
        dag_id: str,
        run_id: str,
        *,
        state: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        mask: list[str] = []
        if state is not None:
            body["state"] = state
            mask.append("state")
        if note is not None:
            body["note"] = note[:1000]
            mask.append("note")
        if not mask:
            raise ValueError("patch_dag_run: nothing to patch")
        return self._request(
            "PATCH",
            f"/api/v2/dags/{dag_id}/dagRuns/{run_id}",
            params={"update_mask": mask},
            json=body,
            dag_id=dag_id,
        ).json()
