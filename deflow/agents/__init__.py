"""The four agents of the Deflow desk.

    analyst    -> what is the market doing?          (regime + variance risk premium)
    structurer -> what trade expresses that?         (priced, defined-risk candidates)
    auditor    -> what is wrong with that trade?     (independent Greeks + fat-tail stress)
    executor   -> route it, or don't.                (Alpaca CLI / MCP / REST)

Only the executor touches the broker, and it will not act on anything the
deterministic risk gate has not signed off first.
"""

from .analyst import MacroVolatilityAnalyst
from .auditor import AdversarialRiskAuditor
from .structurer import OptionsStructurer

__all__ = [
    "AdversarialRiskAuditor",
    "MacroVolatilityAnalyst",
    "OptionsStructurer",
]
