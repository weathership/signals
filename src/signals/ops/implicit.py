"""Implicit object FSMs — K8s / YuniKorn native state machines.

The method FSM is what *we* walk. These are what the *objects* walk.
A probe is scored against both: claiming yk-completed while the
Application is still Running is a different cell than the same claim
during Completing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImplicitFSM:
    name: str
    states: tuple[str, ...]
    holding: frozenset[str]
    terminals: frozenset[str]
    # First match wins when reducing a fleet of objects to one cell.
    severity: tuple[str, ...]

    def normalize(self, state: str) -> str:
        s = (state or "unknown").lower()
        return s if s in self.states else "unknown"

    def is_holding(self, state: str) -> bool:
        return self.normalize(state) in self.holding

    def reduce(self, states: list[str]) -> str:
        if not states:
            return self.severity[-1] if self.severity else "unknown"
        rank = {s: i for i, s in enumerate(self.severity)}
        return min(
            (self.normalize(s) for s in states),
            key=lambda s: rank.get(s, len(rank)),
        )


YK_APPLICATION = ImplicitFSM(
    name="yk.application",
    states=(
        "new",
        "accepted",
        "starting",
        "running",
        "completing",
        "completed",
        "failing",
        "failed",
        "rejected",
        "resuming",
        "missing",
        "unknown",
    ),
    holding=frozenset(
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
    ),
    terminals=frozenset({"completed", "failed", "rejected", "missing"}),
    severity=(
        "failing",
        "running",
        "resuming",
        "starting",
        "accepted",
        "new",
        "unknown",
        "completing",
        "rejected",
        "failed",
        "completed",
        "missing",
    ),
)

K8S_DEPLOY = ImplicitFSM(
    name="k8s.deploy",
    states=("absent", "desired_positive", "desired_zero", "unknown"),
    holding=frozenset({"desired_positive", "unknown"}),
    terminals=frozenset({"absent", "desired_zero"}),
    severity=("desired_positive", "unknown", "desired_zero", "absent"),
)

K8S_POD = ImplicitFSM(
    name="k8s.pod",
    states=("absent", "pending", "running", "terminating", "succeeded", "failed", "unknown"),
    holding=frozenset({"pending", "running", "terminating", "unknown"}),
    terminals=frozenset({"absent", "succeeded", "failed"}),
    severity=(
        "running",
        "pending",
        "terminating",
        "unknown",
        "failed",
        "succeeded",
        "absent",
    ),
)

K8S_JOB = ImplicitFSM(
    name="k8s.job",
    states=("absent", "active", "complete", "failed", "unknown"),
    holding=frozenset({"active", "unknown"}),
    terminals=frozenset({"absent", "complete", "failed"}),
    severity=("active", "unknown", "failed", "complete", "absent"),
)

MACHINES: dict[str, ImplicitFSM] = {
    YK_APPLICATION.name: YK_APPLICATION,
    K8S_DEPLOY.name: K8S_DEPLOY,
    K8S_POD.name: K8S_POD,
    K8S_JOB.name: K8S_JOB,
}


def implicit_cell(fsm_name: str, state: str) -> str:
    m = MACHINES.get(fsm_name)
    if m is None:
        return (state or "unknown").lower()
    return m.normalize(state)
