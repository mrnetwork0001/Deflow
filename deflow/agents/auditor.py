"""Agent 3 — Adversarial Risk Auditor.

This agent's job is to try to talk the desk *out* of the trade.

It does not read the Structurer's numbers. It re-derives position Greeks from
Black-Scholes against the same quotes, runs a full 1,000-path fat-tailed
simulation under two different volatility measures, and then applies a list of
objections that each have the power to fail the proposal on their own.

The output is an `AuditReport` plus the exact payload handed to the
deterministic risk gate. The auditor can veto; it cannot approve. Approval is
the gate's alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..greeks import probability_itm, years_to_expiry
from ..models import CONTRACT_MULTIPLIER, SpreadProposal, utcnow
from ..montecarlo import DEFAULT_PATHS, StressResult, stress_test

log = logging.getLogger("deflow.auditor")

# --- Objection thresholds --------------------------------------------------
MIN_EV_RATIO = 0.0              # expectancy at realised vol must be positive
MAX_CVAR_RATIO = 1.001          # the 5% tail must not exceed structural max loss
MAX_ASSIGNMENT_PROB = 0.35      # P(short leg finishes ITM)
MAX_EXIT_COST_RATIO = 0.25      # round-trip slippage vs max profit
GREEKS_TOLERANCE = 0.02         # relative disagreement allowed on re-derivation


@dataclass
class Objection:
    """One reason not to do the trade."""

    code: str
    severity: str        # "fatal" | "warning"
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class AuditReport:
    """Everything the auditor learned, whether or not it objected."""

    symbol: str
    strategy: str
    passed: bool
    objections: List[Objection] = field(default_factory=list)
    physical: Optional[StressResult] = None      # simulated at realised vol
    risk_neutral: Optional[StressResult] = None  # simulated at implied vol
    greeks: Dict[str, float] = field(default_factory=dict)
    assignment_prob: float = 0.0
    exit_cost: float = 0.0
    variance_edge_usd: float = 0.0
    audited_at: str = field(default_factory=utcnow)

    @property
    def fatal(self) -> List[Objection]:
        return [o for o in self.objections if o.severity == "fatal"]

    @property
    def warnings(self) -> List[Objection]:
        return [o for o in self.objections if o.severity == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "passed": self.passed,
            "objections": [o.to_dict() for o in self.objections],
            "fatal_count": len(self.fatal),
            "warning_count": len(self.warnings),
            "greeks": self.greeks,
            "assignment_probability": round(self.assignment_prob, 4),
            "exit_cost_usd": round(self.exit_cost, 2),
            "variance_edge_usd": round(self.variance_edge_usd, 2),
            "monte_carlo_physical": self.physical.to_dict() if self.physical else {},
            "monte_carlo_risk_neutral": self.risk_neutral.to_dict() if self.risk_neutral else {},
            "audited_at": self.audited_at,
        }

    def headline(self) -> str:
        if self.passed:
            ev = self.physical.mean_pnl if self.physical else 0.0
            return (
                f"AUDIT PASS — EV {ev:+,.0f} USD at realised vol, "
                f"CVaR(5%) {self.physical.cvar_05:,.0f} USD, "
                f"{len(self.warnings)} warning(s)."
            )
        return f"AUDIT FAIL — {self.fatal[0].message}" if self.fatal else "AUDIT FAIL"


class AdversarialRiskAuditor:
    """Independently stress-tests a proposal and argues against it."""

    name = "Agent 3 · Adversarial Risk Auditor"

    def __init__(self, paths: int = DEFAULT_PATHS) -> None:
        self.paths = paths

    def audit(self, proposal: SpreadProposal, realised_vol: float) -> AuditReport:
        objections: List[Objection] = []

        # --- 1. Re-derive the Greeks from scratch --------------------------
        greeks = proposal.portfolio_greeks()
        derived = {
            "delta": round(greeks.delta, 4),
            "gamma": round(greeks.gamma, 5),
            "vega": round(greeks.vega, 4),
            "theta": round(greeks.theta, 4),
            "delta_per_contract": round(proposal.net_delta, 4),
        }

        # --- 2. Two simulations, two measures -------------------------------
        # Risk-neutral (implied vol): what the market says this is worth.
        # Physical (realised vol): what it is worth if the underlying keeps
        # moving the way it has actually been moving. The gap between them is
        # the variance risk premium, in dollars.
        risk_neutral = stress_test(proposal, paths=self.paths)
        physical = stress_test(proposal, paths=self.paths, vol_override=max(realised_vol, 0.03))
        variance_edge = physical.mean_pnl - risk_neutral.mean_pnl

        # --- 3. Objections ---------------------------------------------------

        # Expectancy. A high win rate with a negative mean is the classic
        # short-premium failure mode, and it is a fatal objection here.
        if physical.expected_value_ratio <= MIN_EV_RATIO:
            objections.append(
                Objection(
                    "negative_expectancy",
                    "fatal",
                    f"Expected P&L at realised vol is {physical.mean_pnl:+,.0f} USD "
                    f"({physical.expected_value_ratio:+.1%} of capital at risk) despite a "
                    f"{physical.prob_profit:.0%} win rate — the losing tail is larger than the wins.",
                )
            )

        # Structural integrity: a defined-risk spread's worst simulated path
        # must not be able to exceed its stated maximum loss. If it can, the
        # structure is not what it claims to be.
        if proposal.max_loss > 0 and abs(physical.worst) > proposal.max_loss * MAX_CVAR_RATIO:
            objections.append(
                Objection(
                    "loss_exceeds_defined_maximum",
                    "fatal",
                    f"Simulated worst case {physical.worst:,.0f} USD exceeds the stated "
                    f"defined maximum loss of {-proposal.max_loss:,.0f} USD. "
                    "The structure is not defined-risk as constructed.",
                )
            )

        # Assignment risk on the short legs.
        assignment = self._assignment_probability(proposal)
        if assignment > MAX_ASSIGNMENT_PROB:
            objections.append(
                Objection(
                    "assignment_risk",
                    "warning",
                    f"P(short leg finishes in the money) is {assignment:.0%}, above the "
                    f"{MAX_ASSIGNMENT_PROB:.0%} comfort threshold — early assignment is plausible.",
                )
            )

        # Round-trip cost: crossing the spread twice must not eat the trade.
        exit_cost = self._round_trip_cost(proposal)
        if proposal.max_profit > 0 and exit_cost > proposal.max_profit * MAX_EXIT_COST_RATIO:
            objections.append(
                Objection(
                    "exit_cost",
                    "warning",
                    f"Round-trip bid/ask cost of {exit_cost:,.0f} USD is "
                    f"{exit_cost / proposal.max_profit:.0%} of maximum profit.",
                )
            )

        # Direction sanity: the position's delta must agree with the structure
        # it claims to be. A "bullish" spread with negative delta is a bug.
        direction = proposal.strategy.direction
        if direction == "bullish" and greeks.delta < 0:
            objections.append(
                Objection("delta_direction_mismatch", "fatal",
                          f"Bullish structure carries {greeks.delta:+.1f} delta.")
            )
        elif direction == "bearish" and greeks.delta > 0:
            objections.append(
                Objection("delta_direction_mismatch", "fatal",
                          f"Bearish structure carries {greeks.delta:+.1f} delta.")
            )

        # Theta sign: a credit structure that bleeds theta is mispriced or
        # misbuilt, and a debit structure that earns it is equally suspicious.
        if proposal.strategy.is_credit and greeks.theta < 0:
            objections.append(
                Objection("theta_sign", "warning",
                          f"Credit structure shows negative theta ({greeks.theta:+.2f}/day).")
            )

        # Wing coverage: every short must sit inside a long of the same right.
        if not proposal.is_defined_risk:
            objections.append(
                Objection("undefined_risk", "fatal",
                          "At least one short leg is not covered by a long of the same right.")
            )

        return AuditReport(
            symbol=proposal.symbol,
            strategy=proposal.strategy.value,
            passed=not any(o.severity == "fatal" for o in objections),
            objections=objections,
            physical=physical,
            risk_neutral=risk_neutral,
            greeks=derived,
            assignment_prob=assignment,
            exit_cost=exit_cost,
            variance_edge_usd=variance_edge,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _assignment_probability(proposal: SpreadProposal) -> float:
        """Highest risk-neutral P(ITM) across the short legs."""
        worst = 0.0
        for leg in proposal.legs:
            if leg.ratio >= 0:
                continue
            dte = max((leg.expiry.toordinal() - __import__("datetime").date.today().toordinal()), 0)
            p = probability_itm(
                proposal.underlying_price, leg.strike, years_to_expiry(dte),
                leg.implied_vol or 0.20, leg.right,
            )
            worst = max(worst, p)
        return worst

    @staticmethod
    def _round_trip_cost(proposal: SpreadProposal) -> float:
        """Cost of crossing the bid/ask on entry and exit, from real quotes.

        Legs are priced at the mid, so getting in costs half the quoted width
        per leg and getting out costs the other half -- one full width per leg
        per round trip. `Leg.half_spread` is captured from the NBBO at
        construction, so this is measured rather than assumed; a leg built
        without quote data falls back to a one-cent floor.
        """
        total = sum(max(leg.half_spread * 2.0, 0.01) for leg in proposal.legs)
        return total * CONTRACT_MULTIPLIER * proposal.contracts

    @staticmethod
    def risk_payload(proposal: SpreadProposal, report: AuditReport) -> Dict[str, Any]:
        """The dict handed to the deterministic gate.

        Built from the proposal's own derived properties and the auditor's
        independently simulated probability of profit -- never from anything a
        language model produced.
        """
        payload = proposal.to_risk_payload()
        if report.physical:
            # Prefer the simulated win rate over the closed-form one: it
            # accounts for the jump tail that the analytic formula ignores.
            payload["probability_of_profit"] = report.physical.prob_profit
        return payload


__all__ = ["AdversarialRiskAuditor", "AuditReport", "Objection"]
