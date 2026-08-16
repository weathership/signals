"""Explicit procedure FSM. Holding states are not terminals."""

from __future__ import annotations

from dataclasses import dataclass, field


class IllegalTransition(Exception):
    """Caller asked for a next state the procedure does not allow."""


@dataclass
class ProcedureFSM:
    """Directed graph of named states. ``holding`` may not be treated as done."""

    name: str
    states: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    holding: frozenset[str] = field(default_factory=frozenset)
    terminals: frozenset[str] = field(default_factory=lambda: frozenset({"placed", "failed"}))
    start: str = "start"
    current: str = "start"

    def reset(self) -> None:
        self.current = self.start

    def allowed(self, nxt: str) -> bool:
        return nxt in self.transitions.get(self.current, ())

    def step(self, nxt: str) -> str:
        if nxt not in self.states:
            raise IllegalTransition(f"{self.name}: unknown state {nxt!r}")
        if not self.allowed(nxt):
            raise IllegalTransition(
                f"{self.name}: {self.current!r} → {nxt!r} not allowed "
                f"(from here: {self.transitions.get(self.current, ())})"
            )
        self.current = nxt
        return self.current

    def is_holding(self) -> bool:
        return self.current in self.holding

    def is_terminal(self) -> bool:
        return self.current in self.terminals

    def well_posed(self, allowed_from: frozenset[str] | set[str] | tuple[str, ...]) -> bool:
        """Whether a claim about a later state is legal from here."""
        return self.current in allowed_from

    def as_method(self) -> dict:
        """Named method document (ACP / agent surface; no live cluster)."""
        return {
            "name": self.name,
            "start": self.start,
            "current": self.current,
            "states": list(self.states),
            "holding": sorted(self.holding),
            "terminals": sorted(self.terminals),
            "transitions": {k: list(v) for k, v in self.transitions.items()},
            "law": (
                "Do not treat a holding state as terminal. "
                "Do not start the next epoch on an identity still in a holding state. "
                "A probe is a forecast tagged with the FSM position it was made from."
            ),
        }
