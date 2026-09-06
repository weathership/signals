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
