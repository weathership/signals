"""coord_lease — read a Coordination Activity's LEASE from the Signals engine.

Pure stdlib (urllib + json) so the same module runs inside the Airflow
triggerer, the task runner and the Signals test-suite. The Signals engine's
control HTTP serves ``GET /coord/activities/<activity_id>`` →
``{"state": "alive" | "released" | "lapsed", ...}`` (404 + ``"unknown"`` when
it has no such lease). Airflow OBSERVES that state; it is never told it.

The verdict the sensor rests on:
  released → the owner released the activity   → outcome "released"
  lapsed   → heartbeats stopped for the TTL, or the horizon passed → "lapsed"
  alive    → keep waiting
  unknown / unreachable → keep waiting and say so — a dark Signals is NOT a
             lapse; the sensor's own timeout is the outer net.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

ALIVE = "alive"
RELEASED = "released"
LAPSED = "lapsed"
UNKNOWN = "unknown"

TERMINAL = (RELEASED, LAPSED)
GURU_LAPSED = "#CO.0000000E.LAPSED"  # hold ended because the peer never released
GURU_NOEFFECT = "#CO.0000000F.NOEFFECT"  # owner released without the intended effect
# Owner ReleaseActivity outcomes that are not the workload's real-world effect.
# A "skipped" gate is a fail: calling skip success lets error conditions
# pass as silent, masked failures (gaius_prospects_check 12–15 Sep 2026).
INEFFECTIVE_HEADS = frozenset({"skipped", "failed", "error", "stalled"})

# Temporal window of this DAG run. Not a hold-uptime posture: Theta (and other
# windowed workloads) read it on WatchActivities to bound the slice to this
# logical date. Airflow catchup=False stays; historical weeks are Airflow
# backfill, one Monday at a time.
LOGICAL_DATE_POSTURE = "zndx.logical_date"


def isoformat_logical_date(dt: Any) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "isoformat"):
        return str(dt.isoformat())
    return str(dt).strip()


def postures_with_logical_date(
    postures: dict[str, str] | None, logical_date: Any
) -> dict[str, str]:
    """Stamp the run's logical date onto postures without clobbering holds."""
    out = {str(k): str(v) for k, v in (postures or {}).items()}
    iso = isoformat_logical_date(logical_date)
    if iso:
        out[LOGICAL_DATE_POSTURE] = iso
    return out


class LapsedLease(RuntimeError):
    """The lease lapsed — the peer did not heartbeat or ReleaseActivity.

    Airflow used to treat this as DAG success (hold ~180s then close). That
    hid WatchActivities death: gaius_article_curate looked green on 10–11 Sep
    2026 while Gaius never enqueued a row (MISSTICK).
    """

    def __init__(self, outcome: str = LAPSED, *, kind: str = ""):
        self.outcome = outcome
        self.kind = kind
        what = f"workload {kind} " if kind else ""
        super().__init__(
            f"{GURU_LAPSED} {what}lease {outcome} — peer did not ReleaseActivity"
        )


def require_released(outcome: str, *, kind: str = "") -> str:
    """close() may only succeed when the owner released the lease."""
    if outcome == RELEASED:
        return outcome
    if outcome == LAPSED:
        raise LapsedLease(outcome, kind=kind)
    raise ValueError(f"non-terminal lease outcome {outcome!r}")


class IneffectiveRelease(RuntimeError):
    """The owner released, but the intended effect did not occur.

    Airflow used to treat any ReleaseActivity as DAG success. That hid
    gaius_prospects_check: every 07:00 tick released ``skipped: gate_false``
    (green) while the check only ran on engine-catchup, and a failed
    prospects_update never retried.
    """

    def __init__(self, owner_outcome: str, *, kind: str = ""):
        self.owner_outcome = owner_outcome
        self.kind = kind
        what = f"workload {kind} " if kind else ""
        super().__init__(
            f"{GURU_NOEFFECT} {what}released without effect: {owner_outcome}"
        )


def owner_effect_head(owner_outcome: str) -> str:
    return (owner_outcome.split(":", 1)[0] if owner_outcome else "").strip().lower()


def require_effect(owner_outcome: str, *, kind: str = "") -> str:
    """Workload close: skip/fail/error/stalled is not DAG success.

    Interactive sessions use ``require_released`` only (freeform outcomes).
    Ordered workloads must produce the intended effect.
    """
    head = owner_effect_head(owner_outcome)
    if head in INEFFECTIVE_HEADS:
        raise IneffectiveRelease(owner_outcome, kind=kind)
    return owner_outcome


class LeaseUnreachable(RuntimeError):
    """The lease endpoint did not answer (network, 5xx, non-JSON)."""


def fetch(url: str, timeout_s: float = 5.0) -> dict[str, Any]:
    """GET the lease view. 404 is a real answer ("unknown"); anything else that
    is not a JSON 200 is ``LeaseUnreachable``."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — cluster-internal URL from the run conf
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            try:
                body = json.loads(e.read().decode() or "{}")
            except (ValueError, OSError):
                body = {}
            body["state"] = UNKNOWN
            return body
        raise LeaseUnreachable(f"HTTP {e.code} from {url}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LeaseUnreachable(f"{url}: {e}") from e
    try:
        payload = json.loads(raw.decode() or "{}")
    except ValueError as e:
        raise LeaseUnreachable(f"{url}: non-JSON body") from e
    if not isinstance(payload, dict):
        raise LeaseUnreachable(f"{url}: JSON body is not an object")
    return payload


def classify(payload: dict[str, Any]) -> str:
    """The state the Signals engine computed; anything else reads as unknown."""
    state = str(payload.get("state") or "").lower()
    return state if state in (ALIVE, RELEASED, LAPSED) else UNKNOWN


def outcome_for(state: str) -> str | None:
    """Terminal lease state → the hold task's outcome; None while waiting."""
    return state if state in TERMINAL else None


def poll(url: str, timeout_s: float = 5.0) -> tuple[str, dict[str, Any]]:
    payload = fetch(url, timeout_s)
    return classify(payload), payload


class DeclareRefused(RuntimeError):
    """Signals answered the declaration with a refusal (4xx + guru) or an outage (5xx)."""

    def __init__(self, status: int, body: dict[str, Any]):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body.get('error') or body}")


def post_json(url: str, payload: dict[str, Any], timeout_s: float = 10.0) -> dict[str, Any]:
    """POST a JSON object; a JSON object back. Used by SignalsDeclareOperator to
    declare the run ITSELF as an activity (``POST /coord/activities``). Any
    non-2xx is ``DeclareRefused`` with the body (guru inside) — never a silent
    run without its declaration."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — cluster-internal URL
            raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except (ValueError, OSError):
            body = {}
        raise DeclareRefused(e.code, body if isinstance(body, dict) else {"error": str(body)}) from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LeaseUnreachable(f"{url}: {e}") from e
    try:
        body = json.loads(raw.decode() or "{}")
    except ValueError as e:
        raise LeaseUnreachable(f"{url}: non-JSON body") from e
    if not isinstance(body, dict):
        raise LeaseUnreachable(f"{url}: JSON body is not an object")
    return body
