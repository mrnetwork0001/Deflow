"""Defending a tested position: rolling out, and time-scaled profit taking.

Two forms of management that a fixed stop-and-target cannot express.

**Rolling out.** When the underlying pushes through a short strike near expiry,
closing realises the loss. Rolling closes the tested structure and reopens it
in a later expiry, collecting fresh credit for the additional duration. It buys
time for the move to mean-revert and pays you to wait.

The honest caveat, because it changes when this is worth doing: on a
*defined-risk* spread the wing already caps the loss. Rolling frequently
converts a capped loss into the same capped loss with more time attached, which
is not obviously an improvement. So it is gated hard -- it must collect a net
credit, it must not widen the maximum loss, and a position may only be rolled
twice before the desk accepts it was wrong.

**Time-scaled profit taking.** A credit spread's remaining profit decays with
its remaining time. Holding for the last 25% of maximum profit means holding
through the period where gamma is largest and the reward for doing so is
smallest. The target therefore falls as expiry approaches, which is ordinary
premium-selling practice and, unlike rolling, applies to every winning trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .models import CONTRACT_MULTIPLIER, Leg, OptionQuote, SpreadProposal

log = logging.getLogger("deflow.rolls")

# --- Rolling ---------------------------------------------------------------

# Roll only once the position is close enough to expiry that time is the
# binding problem. Earlier than this there is still room for the move to
# reverse without doing anything.
ROLL_DTE = 12

# How far through the short strike counts as "tested". Slightly before it, so
# the roll happens while the short still has extrinsic value to sell.
TESTED_BUFFER = 0.005

# A position may be rolled this many times. Beyond it the desk is refusing to
# accept a losing view, which is how a capped loss becomes an uncapped habit.
MAX_ROLLS = 2

# The roll must collect at least this much credit per spread, or it is paying
# to stay in a losing trade.
MIN_ROLL_CREDIT = 0.02

# --- Time-scaled profit target ---------------------------------------------

# Take profit at this fraction of maximum profit, interpolated by remaining
# time: patient when there is time to be patient, decisive near expiry.
FAR_TARGET = 0.75    # at or beyond FAR_DTE
NEAR_TARGET = 0.40   # at or inside NEAR_DTE
FAR_DTE = 30
NEAR_DTE = 7


def profit_target(dte: int) -> float:
    """Fraction of maximum profit worth holding out for at `dte` days.

    Linear between the two anchors. The last quarter of a credit spread's
    profit is the slowest and most dangerous to collect -- it arrives only as
    the short strike decays to zero, which is exactly when gamma is largest.
    """
    if dte >= FAR_DTE:
        return FAR_TARGET
    if dte <= NEAR_DTE:
        return NEAR_TARGET
    span = FAR_DTE - NEAR_DTE
    return NEAR_TARGET + (FAR_TARGET - NEAR_TARGET) * ((dte - NEAR_DTE) / span)


@dataclass
class RollPlan:
    """A proposed roll, priced and ready for the risk gate."""

    original_id: str
    proposal: SpreadProposal
    credit: float                 # per spread, positive means collected
    reason: str
    old_dte: int
    new_dte: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_id": self.original_id,
            "symbol": self.proposal.symbol,
            "strategy": self.proposal.strategy.value,
            "contracts": self.proposal.contracts,
            "credit_per_spread": round(self.credit, 4),
            "total_credit": round(self.credit * CONTRACT_MULTIPLIER * self.proposal.contracts, 2),
            "old_dte": self.old_dte,
            "new_dte": self.new_dte,
            "max_loss": round(self.proposal.max_loss, 2),
            "reason": self.reason,
        }


def is_tested(proposal: SpreadProposal, spot: float) -> bool:
    """Has the underlying reached the short strike the structure depends on?"""
    for leg in proposal.legs:
        if leg.ratio >= 0:
            continue
        if leg.right == "call" and spot >= leg.strike * (1 - TESTED_BUFFER):
            return True
        if leg.right == "put" and spot <= leg.strike * (1 + TESTED_BUFFER):
            return True
    return False


def should_consider(
    proposal: SpreadProposal, spot: float, unrealized_pnl: float, rolls_used: int
) -> Optional[str]:
    """Whether this position is a roll candidate, and why. None if not."""
    if not proposal.strategy.is_credit:
        # A debit spread has nothing to roll for: there is no credit to
        # collect, so extending it is simply paying again for the same view.
        return None
    if rolls_used >= MAX_ROLLS:
        return None
    if proposal.dte > ROLL_DTE:
        return None
    if not is_tested(proposal, spot):
        return None
    if unrealized_pnl >= 0:
        # A winning position near expiry should be closed, not extended.
        return None
    return (
        f"short strike tested at {spot:.2f} with {proposal.dte} DTE and "
        f"{unrealized_pnl:+,.0f} unrealised"
    )


def build(
    proposal: SpreadProposal,
    chain: Sequence[OptionQuote],
    spot: float,
    reason: str,
) -> Optional[RollPlan]:
    """Reconstruct the same structure in a later expiry, if it pays to.

    Keeps the strike geometry -- same width, same distance from the money --
    and moves it out in time. Anything that would widen the maximum loss or
    fail to collect a credit is discarded rather than adjusted into
    acceptability.
    """
    later = sorted({q.expiry for q in chain if q.dte > proposal.dte + 7})
    if not later:
        return None

    by_symbol = {q.symbol: q for q in chain}
    # What closing the current structure costs: buy back the shorts, sell the
    # longs, at the prices actually quoted.
    close_cost = 0.0
    for leg in proposal.legs:
        quote = by_symbol.get(leg.symbol)
        if quote is None or quote.mid <= 0:
            return None
        close_cost += -leg.ratio * quote.mid

    for expiry in later[:3]:
        candidates = [q for q in chain if q.expiry == expiry]
        if not candidates:
            continue

        new_legs: List[Leg] = []
        ok = True
        for leg in proposal.legs:
            pool = [q for q in candidates if q.right == leg.right]
            if not pool:
                ok = False
                break
            match = min(pool, key=lambda q: abs(q.strike - leg.strike))
            if match.mid <= 0:
                ok = False
                break
            new_legs.append(
                Leg(
                    symbol=match.symbol, right=match.right, strike=match.strike,
                    expiry=match.expiry, ratio=leg.ratio, price=match.mid,
                    implied_vol=match.implied_vol,
                    half_spread=max((match.ask - match.bid) / 2.0, 0.0),
                )
            )
        if not ok or len(new_legs) != len(proposal.legs):
            continue

        rolled = SpreadProposal(
            symbol=proposal.symbol, strategy=proposal.strategy, legs=new_legs,
            contracts=proposal.contracts, underlying_price=spot,
            iv_rank=proposal.iv_rank, regime=proposal.regime,
            thesis=f"roll of {proposal.proposal_id}: {reason}",
            source="roll",
        )
        if not rolled.is_defined_risk:
            continue
        # The whole point is to be paid for the extra duration. Opening credit
        # minus what it costs to close the old structure.
        credit = rolled.net_credit - close_cost
        if credit < MIN_ROLL_CREDIT:
            continue
        if rolled.max_loss > proposal.max_loss + 1e-6:
            # Rolling into more risk than the position already carries is
            # doubling down, not defending.
            continue

        return RollPlan(
            original_id=proposal.proposal_id, proposal=rolled, credit=credit,
            reason=reason, old_dte=proposal.dte, new_dte=rolled.dte,
        )
    return None


__all__ = [
    "MAX_ROLLS", "ROLL_DTE", "RollPlan", "build", "is_tested",
    "profit_target", "should_consider",
]
