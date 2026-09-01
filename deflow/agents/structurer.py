"""Agent 2 — Options Structurer.

Turns the Analyst's stance into concrete, priced, defined-risk spreads built
from live quotes.

Two rules govern everything here:

* **Deterministic construction.** Strikes are chosen by delta target, widths
  from a fixed ladder, premiums from live NBBO mids, and size from the risk
  gate's own sizer. A language model is offered the finished list and may pick
  one; it never builds one.

* **Liquidity is a hard filter, not a preference.** A spread that looks superb
  on mid-price and cannot be exited is worse than no spread. Every leg must
  clear a bid/ask width and open-interest floor before it is considered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from risk_gate import (
    MAX_DTE,
    MIN_CREDIT_TO_WIDTH,
    MIN_DTE,
    MIN_REWARD_RISK_DEBIT,
    DeterministicRiskGate,
    PortfolioState,
)

from ..greeks import black_scholes, years_to_expiry
from .. import events
from ..models import CONTRACT_MULTIPLIER, Leg, OptionQuote, Regime, SpreadProposal, Strategy
from ..montecarlo import stress_test
from .analyst import AnalystView

log = logging.getLogger("deflow.structurer")

# --- Liquidity floors ------------------------------------------------------
MAX_SPREAD_PCT = 0.15          # bid/ask width as a fraction of mid
MIN_OPEN_INTEREST = 100
MIN_BID = 0.05

# --- Construction ladders --------------------------------------------------
PREFERRED_DTE = (21, 45)                      # the theta sweet spot
CREDIT_SHORT_DELTAS = (0.16, 0.20, 0.25, 0.30)
DEBIT_LONG_DELTAS = (0.50, 0.60, 0.70)
DEBIT_SHORT_DELTAS = (0.20, 0.25, 0.30)
MAX_CANDIDATES = 8

# Wing widths, as a fraction of spot, so the ladder scales from NVDA to SPY.
WIDTH_FRACTIONS = (0.010, 0.015, 0.020, 0.030)


@dataclass
class Candidate:
    """A scored, fully-priced proposal awaiting audit."""

    proposal: SpreadProposal
    score: float
    score_parts: Dict[str, float] = field(default_factory=dict)
    ev_physical: float = 0.0          # Monte Carlo mean P&L under realised vol
    ev_ratio: float = 0.0
    liquidity: float = 0.0
    round_trip_cost: float = 0.0
    notes: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        """The compact view handed to the reasoning model.

        Deliberately excludes anything the model could use to re-derive or
        argue with the pricing -- it sees outcomes, not inputs.
        """
        p = self.proposal
        return {
            "strategy": p.strategy.value,
            "direction": p.strategy.direction,
            "symbol": p.symbol,
            "contracts": p.contracts,
            "dte": p.dte,
            "strikes": [l.strike for l in p.legs],
            "net_credit" if p.strategy.is_credit else "net_debit": round(
                p.net_credit if p.strategy.is_credit else p.net_debit, 2
            ),
            "max_loss": round(p.max_loss, 2),
            "max_profit": round(p.max_profit, 2),
            "reward_risk": round(p.reward_risk, 2),
            "probability_of_profit": round(p.probability_of_profit(), 3),
            "breakevens": [round(b, 2) for b in p.breakevens()],
            "net_delta": round(p.net_delta, 3),
            "expected_value_usd": round(self.ev_physical, 2),
            "expected_value_ratio": round(self.ev_ratio, 4),
            "round_trip_cost_usd": round(self.round_trip_cost, 2),
            "liquidity_score": round(self.liquidity, 3),
            "deterministic_score": round(self.score, 4),
        }


class OptionsStructurer:
    """Builds and ranks defined-risk spreads for one underlying."""

    name = "Agent 2 · Options Structurer"

    def __init__(self, provider: Any, gate: DeterministicRiskGate) -> None:
        self.provider = provider
        self.gate = gate
        # Populated on each build(); read by the desk for the ledger.
        self.event_risk = events.EventRisk(False)

    # -- chain preparation --------------------------------------------------

    @staticmethod
    def _liquid(quotes: Sequence[OptionQuote]) -> List[OptionQuote]:
        """Drop anything we could not get out of at a fair price.

        The open-interest test is applied only when open-interest data actually
        arrived. If every contract in the chain reports zero, that is a data
        problem, not a market in which nothing is open — and silently applying
        the filter anyway rejects the entire universe on every symbol while
        reporting nothing worse than "no candidates".

        That exact failure cost a full pre-market cycle: open interest is
        served by Alpaca's contracts endpoint, not its snapshot endpoint, and
        reading it off the snapshot yields 0 everywhere. So when the signal is
        missing the desk keeps trading on bid/ask width alone and says loudly
        that it is doing so, rather than going quiet and looking well-behaved.
        """
        priced = [
            q for q in quotes
            if q.bid >= MIN_BID and q.ask > q.bid and q.spread_pct <= MAX_SPREAD_PCT
            and q.implied_vol > 0
        ]
        if not priced:
            return []

        if all(q.open_interest <= 0 for q in priced):
            log.warning(
                "Open interest is zero across all %d priced contracts for %s — treating the "
                "signal as unavailable and screening on bid/ask width alone. Check the "
                "contracts-endpoint join.",
                len(priced), priced[0].symbol[:6].rstrip("0123456789") or "?",
            )
            return priced

        return [q for q in priced if q.open_interest >= MIN_OPEN_INTEREST]

    @staticmethod
    def _delta_of(q: OptionQuote) -> float:
        return black_scholes(
            q.underlying_price, q.strike, years_to_expiry(q.dte), q.implied_vol, q.right
        ).delta

    @staticmethod
    def _nearest_delta(
        quotes: Sequence[OptionQuote], target_abs_delta: float, right: str
    ) -> Optional[OptionQuote]:
        pool = [q for q in quotes if q.right == right]
        if not pool:
            return None
        return min(pool, key=lambda q: abs(abs(OptionsStructurer._delta_of(q)) - target_abs_delta))

    @staticmethod
    def _nearest_strike(
        quotes: Sequence[OptionQuote],
        strike: float,
        right: str,
        above: Optional[float] = None,
        below: Optional[float] = None,
    ) -> Optional[OptionQuote]:
        """Closest quote to `strike`, optionally restricted to one side.

        `above`/`below` exist because a protective wing is only protective if it
        sits strictly beyond the short leg. Without the constraint, a target
        strike outside the listed range collapses onto the short strike itself
        and silently produces a naked position -- which then has to be caught
        downstream. Constraining the search here means the geometry is correct
        by construction.
        """
        pool = [q for q in quotes if q.right == right]
        if above is not None:
            pool = [q for q in pool if q.strike > above]
        if below is not None:
            pool = [q for q in pool if q.strike < below]
        if not pool:
            return None
        return min(pool, key=lambda q: abs(q.strike - strike))

    @staticmethod
    def _by_expiry(quotes: Sequence[OptionQuote]) -> Dict[date, List[OptionQuote]]:
        buckets: Dict[date, List[OptionQuote]] = {}
        for q in quotes:
            buckets.setdefault(q.expiry, []).append(q)
        return buckets

    @staticmethod
    def _leg(q: OptionQuote, ratio: int) -> Leg:
        """Price a leg at the mid, recording the quoted width alongside it."""
        return Leg(
            symbol=q.symbol,
            right=q.right,
            strike=q.strike,
            expiry=q.expiry,
            ratio=ratio,
            price=q.mid,
            implied_vol=q.implied_vol,
            half_spread=max((q.ask - q.bid) / 2.0, 0.0),
        )

    # -- strategy selection -------------------------------------------------

    @staticmethod
    def strategy_for(view: AnalystView) -> Optional[Strategy]:
        """Map (stance, bias) onto a structure.

        Selling premium works in any direction because the wing caps the tail;
        buying convexity needs a direction to pay for the theta bleed, so a
        neutral tape with cheap options is simply passed on.
        """
        if view.stance == "sell_premium":
            return {
                "bullish": Strategy.BULL_PUT_SPREAD,
                "bearish": Strategy.BEAR_CALL_SPREAD,
                "neutral": Strategy.IRON_CONDOR,
            }[view.bias]
        if view.stance == "buy_convexity":
            return {
                "bullish": Strategy.BULL_CALL_SPREAD,
                "bearish": Strategy.BEAR_PUT_SPREAD,
                "neutral": None,
            }[view.bias]
        return None

    # -- construction -------------------------------------------------------

    def build(
        self,
        view: AnalystView,
        portfolio: PortfolioState,
        max_candidates: int = MAX_CANDIDATES,
    ) -> List[Candidate]:
        strategy = self.strategy_for(view)
        if strategy is None:
            return []

        snapshot = view.snapshot
        chain = self._liquid(self.provider.option_chain(snapshot.symbol, MIN_DTE, MAX_DTE))
        if not chain:
            log.info("%s: no contracts cleared the liquidity filter", snapshot.symbol)
            return []

        # Read the volatility term structure for a catalyst the market has
        # already priced. Selling premium that expires AFTER an event means
        # being short the gap, and the credit looks generous precisely because
        # the move is coming -- that is being paid fairly for a real risk, not
        # harvesting a variance premium, which is the only thing this desk is
        # trying to do.
        self.event_risk = events.detect(chain, snapshot.price)
        buckets = self._by_expiry(chain)
        if self.event_risk.detected and strategy.is_credit:
            safe = {
                expiry: quotes
                for expiry, quotes in buckets.items()
                if not events.expiry_is_exposed(self.event_risk, expiry)
            }
            dropped = len(buckets) - len(safe)
            if dropped:
                log.info(
                    "%s: %d expiries span a priced-in event (%s); short premium restricted "
                    "to expiries before it",
                    snapshot.symbol, dropped, self.event_risk.summary(),
                )
            buckets = safe
            if not buckets:
                return []

        # Restrict to the 21-45 DTE window when the chain offers it. Inside a
        # week or two, gamma dominates and the 3-DTE exit guard leaves almost
        # no room for the trade to work; scoring alone was not reliably keeping
        # the desk out of those expiries.
        preferred = {
            expiry: quotes
            for expiry, quotes in buckets.items()
            if PREFERRED_DTE[0] <= (expiry - date.today()).days <= PREFERRED_DTE[1]
        }
        if preferred:
            buckets = preferred

        candidates: List[Candidate] = []
        for expiry, quotes in sorted(buckets.items()):
            dte = (expiry - date.today()).days
            if not (MIN_DTE <= dte <= MAX_DTE):
                continue
            builder = {
                Strategy.BULL_PUT_SPREAD: self._build_credit_vertical,
                Strategy.BEAR_CALL_SPREAD: self._build_credit_vertical,
                Strategy.IRON_CONDOR: self._build_iron_condor,
                Strategy.BULL_CALL_SPREAD: self._build_debit_vertical,
                Strategy.BEAR_PUT_SPREAD: self._build_debit_vertical,
            }[strategy]
            candidates.extend(builder(strategy, snapshot, quotes, portfolio, view.snapshot.regime))

        # Score, then keep the best few for the reasoning layer to choose from.
        for c in candidates:
            self._score(c, view)
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:max_candidates]

    @staticmethod
    def _satisfies_payoff_floor(proposal: SpreadProposal) -> bool:
        """Mirror of risk-gate breaker 10, applied at construction time."""
        if proposal.max_loss <= 0:
            return False
        if proposal.strategy.is_credit:
            width = proposal.max_profit + proposal.max_loss
            return width > 0 and (proposal.max_profit / width) >= MIN_CREDIT_TO_WIDTH
        return (proposal.max_profit / proposal.max_loss) >= MIN_REWARD_RISK_DEBIT

    def _size(self, proposal: SpreadProposal, portfolio: PortfolioState) -> int:
        """Ask the risk gate how big this is allowed to be. Never decide it here."""
        per_contract = proposal.max_loss / max(proposal.contracts, 1)
        return self.gate.max_contracts(per_contract, portfolio, proposal.symbol)

    def _finalise(
        self,
        symbol: str,
        strategy: Strategy,
        legs: List[Leg],
        spot: float,
        snapshot: Any,
        regime: Regime,
        portfolio: PortfolioState,
    ) -> Optional[SpreadProposal]:
        """Build at size 1, ask the gate for the real size, rebuild."""
        probe = SpreadProposal(
            symbol=symbol, strategy=strategy, legs=legs, contracts=1,
            underlying_price=spot, iv_rank=snapshot.iv_rank, regime=regime,
        )
        if probe.max_loss <= 0 or not probe.is_defined_risk:
            return None
        # Gate-aware construction. The risk gate stays authoritative -- it runs
        # again on whatever is finally chosen, and can still veto -- but there
        # is no reason to spend a Monte Carlo, a model call and an audit on a
        # structure whose payoff ratio the gate is guaranteed to refuse. Two of
        # the desk's three tradeable names were being lost this way: the single
        # top-scored candidate went forward, hit breaker 10, and took the whole
        # symbol down with it while perfectly acceptable narrower spreads sat
        # unexamined in the same list.
        if not self._satisfies_payoff_floor(probe):
            return None

        contracts = self._size(probe, portfolio)
        if contracts < 1:
            return None
        return SpreadProposal(
            symbol=symbol, strategy=strategy, legs=legs, contracts=contracts,
            underlying_price=spot, iv_rank=snapshot.iv_rank, regime=regime,
        )

    # -- builders -----------------------------------------------------------

    def _build_credit_vertical(
        self, strategy: Strategy, snapshot: Any, quotes: List[OptionQuote],
        portfolio: PortfolioState, regime: Regime,
    ) -> List[Candidate]:
        """Sell an OTM option, buy a further-OTM wing to cap the tail."""
        right = "put" if strategy is Strategy.BULL_PUT_SPREAD else "call"
        spot = snapshot.price
        out: List[Candidate] = []

        for target in CREDIT_SHORT_DELTAS:
            short_q = self._nearest_delta(quotes, target, right)
            if short_q is None:
                continue
            for frac in WIDTH_FRACTIONS:
                width = spot * frac
                # The long wing sits further out of the money than the short.
                if right == "put":
                    wing_strike = short_q.strike - width
                    long_q = self._nearest_strike(quotes, wing_strike, right, below=short_q.strike)
                else:
                    wing_strike = short_q.strike + width
                    long_q = self._nearest_strike(quotes, wing_strike, right, above=short_q.strike)
                if long_q is None:
                    continue

                legs = [self._leg(short_q, -1), self._leg(long_q, +1)]
                proposal = self._finalise(
                    snapshot.symbol, strategy, legs, spot, snapshot, regime, portfolio
                )
                if proposal and proposal.net_credit > 0:
                    out.append(Candidate(proposal=proposal, score=0.0))
        return out

    def _build_debit_vertical(
        self, strategy: Strategy, snapshot: Any, quotes: List[OptionQuote],
        portfolio: PortfolioState, regime: Regime,
    ) -> List[Candidate]:
        """Buy the near-the-money option, sell a further-out one to cut cost."""
        right = "call" if strategy is Strategy.BULL_CALL_SPREAD else "put"
        spot = snapshot.price
        out: List[Candidate] = []

        for long_target in DEBIT_LONG_DELTAS:
            long_q = self._nearest_delta(quotes, long_target, right)
            if long_q is None:
                continue
            for short_target in DEBIT_SHORT_DELTAS:
                if short_target >= long_target:
                    continue
                probe = self._nearest_delta(quotes, short_target, right)
                if probe is None:
                    continue
                # The short leg must sit further OTM than the long, or the
                # structure is not a debit spread at all.
                if right == "call":
                    short_q = self._nearest_strike(quotes, probe.strike, right, above=long_q.strike)
                else:
                    short_q = self._nearest_strike(quotes, probe.strike, right, below=long_q.strike)
                if short_q is None:
                    continue

                legs = [self._leg(long_q, +1), self._leg(short_q, -1)]
                proposal = self._finalise(
                    snapshot.symbol, strategy, legs, spot, snapshot, regime, portfolio
                )
                if proposal and proposal.net_debit > 0:
                    out.append(Candidate(proposal=proposal, score=0.0))
        return out

    def _build_iron_condor(
        self, strategy: Strategy, snapshot: Any, quotes: List[OptionQuote],
        portfolio: PortfolioState, regime: Regime,
    ) -> List[Candidate]:
        """Sell a put spread and a call spread against a range-bound tape."""
        spot = snapshot.price
        out: List[Candidate] = []

        for target in CREDIT_SHORT_DELTAS:
            short_put = self._nearest_delta(quotes, target, "put")
            short_call = self._nearest_delta(quotes, target, "call")
            if short_put is None or short_call is None:
                continue
            if short_put.strike >= short_call.strike:
                continue  # inverted condor; not a structure we trade
            for frac in WIDTH_FRACTIONS:
                width = spot * frac
                long_put = self._nearest_strike(
                    quotes, short_put.strike - width, "put", below=short_put.strike
                )
                long_call = self._nearest_strike(
                    quotes, short_call.strike + width, "call", above=short_call.strike
                )
                if long_put is None or long_call is None:
                    continue

                legs = [
                    self._leg(short_put, -1), self._leg(long_put, +1),
                    self._leg(short_call, -1), self._leg(long_call, +1),
                ]
                proposal = self._finalise(
                    snapshot.symbol, strategy, legs, spot, snapshot, regime, portfolio
                )
                if proposal and proposal.net_credit > 0:
                    out.append(Candidate(proposal=proposal, score=0.0))
        return out

    # -- scoring ------------------------------------------------------------

    def _score(self, candidate: Candidate, view: AnalystView) -> None:
        """Rank candidates on realised-vol expectancy, not on implied pricing.

        This is the crux of the whole strategy. Under the risk-neutral measure
        every vertical spread is worth exactly what it costs -- simulating with
        implied vol would score every candidate at zero. Deflow's thesis is
        that implied *overstates* what the underlying will actually deliver, so
        candidates are simulated at **realised** volatility. A spread only
        scores well if it profits at the volatility the stock has really been
        printing, while being paid at the volatility the market is charging.
        """
        p = candidate.proposal
        realised = max(view.snapshot.hv_forecast, 0.03)

        physical = stress_test(p, paths=400, vol_override=realised)
        risk_neutral = stress_test(p, paths=400)

        candidate.ev_physical = physical.mean_pnl
        candidate.ev_ratio = physical.expected_value_ratio

        # Liquidity, as the thing that actually matters: what fraction of this
        # spread's maximum profit gets handed to the market makers on a round
        # trip. Crossing every leg twice at the quoted width is the honest
        # worst case, and a structure that gives away half its upside to
        # spreads is not a good trade however well it prices.
        round_trip = sum(leg.half_spread * 2.0 for leg in p.legs) * CONTRACT_MULTIPLIER * p.contracts
        candidate.round_trip_cost = round_trip
        candidate.liquidity = (
            max(0.0, 1.0 - round_trip / p.max_profit) if p.max_profit > 0 else 0.0
        )

        pop = p.probability_of_profit()
        # Tail quality: how much of the structural max loss the 5% tail eats.
        tail = 1.0 - min(abs(physical.cvar_05) / p.max_loss, 1.0) if p.max_loss > 0 else 0.0
        # Edge over fair value: what we gain by simulating at realised rather
        # than implied. Positive means the variance premium is on our side.
        edge = (physical.mean_pnl - risk_neutral.mean_pnl) / p.max_loss if p.max_loss > 0 else 0.0
        # Favour the 21-45 DTE window.
        lo, hi = PREFERRED_DTE
        dte_fit = 1.0 if lo <= p.dte <= hi else max(0.0, 1.0 - abs(p.dte - (lo + hi) / 2) / 45.0)
        delta_fit = max(0.0, 1.0 - abs(p.net_delta) / 0.35)

        parts = {
            "expectancy": max(-1.0, min(1.0, candidate.ev_ratio * 4.0)),
            "variance_edge": max(-1.0, min(1.0, edge * 4.0)),
            "probability": (pop - 0.5) * 2.0,
            "tail_quality": tail,
            "liquidity": candidate.liquidity,
            "dte_fit": dte_fit,
            "delta_fit": delta_fit,
            "conviction": view.conviction,
        }
        weights = {
            "expectancy": 0.26,
            "variance_edge": 0.17,
            "probability": 0.12,
            "tail_quality": 0.13,
            "liquidity": 0.18,
            "dte_fit": 0.07,
            "delta_fit": 0.04,
            "conviction": 0.03,
        }
        candidate.score_parts = parts
        candidate.score = sum(parts[k] * w for k, w in weights.items())

        if candidate.ev_physical <= 0:
            candidate.notes.append(
                f"Negative expectancy at realised vol ({candidate.ev_physical:+,.0f} USD) — "
                "the premium collected does not cover the tail."
            )


__all__ = ["Candidate", "OptionsStructurer", "MAX_SPREAD_PCT", "MIN_OPEN_INTEREST"]
