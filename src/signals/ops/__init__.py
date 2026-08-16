"""IT-ops procedures: explicit FSM + state-aware Brier ledger.

A probe is a forecast (proposition, p) tagged with the FSM state it was
made from. Ill-posed claims (asserting a terminal from a holding state)
resolve false and accrue Brier. ACP agents later walk the same method.
"""

from signals.ops.fsm import IllegalTransition, ProcedureFSM
from signals.ops.ledger import ObservationLedger

__all__ = ["IllegalTransition", "ObservationLedger", "ProcedureFSM"]
