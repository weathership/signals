"""Invariant model — aligned with cybersec zarf/converge/model.py (Layer A/B)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple


class Layer(str, Enum):
    """A = transport-once artifacts; B = disposable cluster state."""

    A = "A"
    B = "B"


class Cost(str, Enum):
    CHEAP = "cheap"
    EXPENSIVE = "expensive"


class Outcome(str, Enum):
    OK = "ok"
    REMEDIATED = "fixed"
    WOULD_FIX = "would-fix"
    MANUAL = "manual"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Probe:
    ok: bool
    detail: str = ""


@dataclass
class Fix:
    changed: bool = False
    detail: str = ""


@dataclass(frozen=True)
class Invariant:
    id: str
    tier: str
    title: str
    layer: Layer
    detect: Callable
    remediate: Optional[Callable] = None
    cost: Cost = Cost.CHEAP
    depends_on: Tuple[str, ...] = ()
    manual_hint: str = ""

    def __post_init__(self):
        if self.layer is Layer.A and self.remediate is not None:
            raise ValueError(
                f"invariant {self.id}: Layer-A must be detect-only (CONSERVATION)"
            )


@dataclass
class Eval:
    inv: Invariant
    outcome: Outcome
    detail: str = ""

    @property
    def converged(self) -> bool:
        return self.outcome in (Outcome.OK, Outcome.REMEDIATED, Outcome.SKIPPED)
