"""State-aware Brier ledger for IT-ops probes (synth calibration lineage).

Every probe verdict is a FORECAST: a proposition with implied confidence,
tagged with the procedure FSM state at claim time. Outcomes arrive when
an oracle (kubectl / YK GET) or a downstream step resolves the claim.

Brier is scored per (observer, method fsm_state, implicit object FSM +
state, procedure, engine epoch). The method cell is where *we* were;
the implicit cell is where the K8s/YK *object* was (Running vs
Completing). Mixing those hid the Helm-Job miss.

A probe that asserts a terminal from a holding state is ill-posed and
resolves false. Uncalibrated (n=0) is honest ignorance, not trust.

α = shrunk(1 − Brier) is the DST discount an ACP agent should apply
before acting on that observer in this state.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path("build/state/ops-observations.jsonl")

# Verdict → implied P(proposition is TRUE). One table, auditable.
VERDICT_P = {
    "satisfied": 0.85,
    "unverified": 0.15,
    "blocked": 0.10,
    "ill_posed": 0.80,  # claimed from the wrong FSM state; usually false
    "vacuous": 0.50,
}


def _engine_rev() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


@dataclass
class Observation:
    id: str
    ts: float
    observer: str
    proposition: str
    p: float
    verdict: str
    evidence: str
    procedure: str
    fsm_state: str
    engine_rev: str
    implicit_fsm: str = ""
    implicit_state: str = ""
    elapsed_ms: float | None = None
    outcome: bool | None = None
    resolver: str | None = None
    resolved_ts: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ObservationLedger:
    """Append-only JSONL. Corrections are events; reads fold them on."""

    def __init__(self, path: Path | None = None, engine_rev: str | None = None):
        self._path = path or DEFAULT_LEDGER
        self._rev = engine_rev if engine_rev is not None else _engine_rev()

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        observer: str,
        proposition: str,
        verdict: str,
        evidence: str,
        *,
        procedure: str,
        fsm_state: str,
        implicit_fsm: str = "",
        implicit_state: str = "",
        elapsed_ms: float | None = None,
        p: float | None = None,
        **meta: Any,
    ) -> str:
        obs = Observation(
            id=uuid.uuid4().hex[:12],
            ts=time.time(),
            observer=observer,
            proposition=proposition,
            p=VERDICT_P.get(verdict, 0.5) if p is None else p,
            verdict=verdict,
            evidence=evidence,
            procedure=procedure,
            fsm_state=fsm_state,
            implicit_fsm=implicit_fsm,
            implicit_state=implicit_state,
            engine_rev=self._rev,
            elapsed_ms=elapsed_ms,
            meta=meta,
        )
        self._append(asdict(obs))
        return obs.id

    def resolve(self, obs_id: str, outcome: bool, resolver: str) -> None:
        self._append(
            {
                "_correction": True,
                "id": obs_id,
                "outcome": outcome,
                "resolver": resolver,
                "resolved_ts": time.time(),
            }
        )

    def resolve_open(
        self, proposition: str, outcome: bool, resolver: str, *, window_s: float = 3600.0
    ) -> int:
        cutoff = time.time() - window_s
        n = 0
        for obs in self._load().values():
            if (
                obs.get("proposition") == proposition
                and obs.get("outcome") is None
                and float(obs.get("ts") or 0) >= cutoff
                and not obs.get("_correction")
            ):
                self.resolve(str(obs["id"]), outcome, resolver)
                n += 1
        return n

    def score(
        self,
        observer: str,
        fsm_state: str | None = None,
        *,
        procedure: str | None = None,
        implicit_fsm: str | None = None,
        implicit_state: str | None = None,
    ) -> tuple[float | None, int]:
        """Brier for this observer in a method and/or implicit cell."""
        sse, n = 0.0, 0
        for obs in self._load().values():
            if obs.get("observer") != observer:
                continue
            if fsm_state is not None and obs.get("fsm_state") != fsm_state:
                continue
            if implicit_fsm is not None and (obs.get("implicit_fsm") or "") != implicit_fsm:
                continue
            if implicit_state is not None and (
                obs.get("implicit_state") or ""
            ) != implicit_state:
                continue
            if procedure is not None and obs.get("procedure") != procedure:
                continue
            if obs.get("engine_rev") != self._rev:
                continue
            if obs.get("outcome") is None:
                continue
            n += 1
            truth = 1.0 if obs["outcome"] else 0.0
            sse += (float(obs["p"]) - truth) ** 2
        return (round(sse / n, 4) if n else None), n

    def discount_alpha(
        self,
        observer: str,
        fsm_state: str | None = None,
        *,
        procedure: str | None = None,
        implicit_fsm: str | None = None,
        implicit_state: str | None = None,
        prior: float = 0.5,
        k: float = 2.0,
    ) -> tuple[float, str]:
        brier, n = self.score(
            observer,
            fsm_state,
            procedure=procedure,
            implicit_fsm=implicit_fsm,
            implicit_state=implicit_state,
        )
        if brier is None:
            return prior, f"α={prior:.2f} (uncalibrated)"
        alpha = (n / (n + k)) * (1.0 - brier) + (k / (n + k)) * prior
        return alpha, f"α={alpha:.2f} (Brier {brier:.3f}/n={n})"

    def forecast_risk(
        self,
        observer: str,
        fsm_state: str | None = None,
        *,
        procedure: str | None = None,
        implicit_fsm: str | None = None,
        implicit_state: str | None = None,
    ) -> dict[str, Any]:
        """P(this observer is wrong here). Uncalibrated → 0.5, not 0."""
        brier, n = self.score(
            observer,
            fsm_state,
            procedure=procedure,
            implicit_fsm=implicit_fsm,
            implicit_state=implicit_state,
        )
        alpha, note = self.discount_alpha(
            observer,
            fsm_state,
            procedure=procedure,
            implicit_fsm=implicit_fsm,
            implicit_state=implicit_state,
        )
        risk = brier if brier is not None else 0.5
        return {
            "observer": observer,
            "fsm_state": fsm_state,
            "implicit_fsm": implicit_fsm,
            "implicit_state": implicit_state,
            "procedure": procedure,
            "brier": brier,
            "n": n,
            "risk": risk,
            "alpha": round(alpha, 4),
            "note": note,
        }

    def report(self, *, axis: str = "method") -> list[dict[str, Any]]:
        """axis=method | implicit | both."""
        groups: dict[tuple, dict[str, Any]] = {}
        for obs in self._load().values():
            if axis == "implicit":
                key = (
                    obs.get("observer"),
                    obs.get("implicit_fsm") or "",
                    obs.get("implicit_state") or "",
                    obs.get("procedure"),
                    obs.get("engine_rev"),
                )
            elif axis == "both":
                key = (
                    obs.get("observer"),
                    obs.get("fsm_state"),
                    obs.get("implicit_fsm") or "",
                    obs.get("implicit_state") or "",
                    obs.get("procedure"),
                    obs.get("engine_rev"),
                )
            else:
                key = (
                    obs.get("observer"),
                    obs.get("fsm_state"),
                    obs.get("procedure"),
                    obs.get("engine_rev"),
                )
            g = groups.setdefault(key, {"n": 0, "resolved": 0, "sse": 0.0})
            g["n"] += 1
            if obs.get("outcome") is not None:
                g["resolved"] += 1
                truth = 1.0 if obs["outcome"] else 0.0
                g["sse"] += (float(obs["p"]) - truth) ** 2
        out = []
        for k, g in sorted(groups.items()):
            row: dict[str, Any] = {
                "n": g["n"],
                "resolved": g["resolved"],
                "brier": round(g["sse"] / g["resolved"], 4) if g["resolved"] else None,
            }
            if axis == "implicit":
                row.update(
                    observer=k[0],
                    implicit_fsm=k[1],
                    implicit_state=k[2],
                    procedure=k[3],
                    engine_rev=k[4],
                )
            elif axis == "both":
                row.update(
                    observer=k[0],
                    fsm_state=k[1],
                    implicit_fsm=k[2],
                    implicit_state=k[3],
                    procedure=k[4],
                    engine_rev=k[5],
                )
            else:
                row.update(
                    observer=k[0],
                    fsm_state=k[1],
                    procedure=k[2],
                    engine_rev=k[3],
                )
            out.append(row)
        return out

    def _append(self, row: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")

    def _load(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return rows
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("_correction"):
                target = rows.get(str(row.get("id", "")))
                if target is not None:
                    target["outcome"] = row.get("outcome")
                    target["resolver"] = row.get("resolver")
                    target["resolved_ts"] = row.get("resolved_ts")
            elif "id" in row:
                rows[str(row["id"])] = row
        return rows
