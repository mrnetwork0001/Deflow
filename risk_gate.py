"""
Deflow — Deterministic Zero-LLM Risk Gate
=========================================

The only component in Deflow with veto authority over capital.

Design rules, enforced by construction:

  1. **No model input.** This module imports nothing but the standard library.
     There is no network call, no prompt, no temperature, no retry. Given the
     same proposal and the same portfolio state it returns the same verdict,
     forever.
  2. **Fail closed.** Every check reads its input with an explicit,
     *pessimistic* default. A field the structurer forgot to populate is
     treated as the worst case, not as zero. A malformed proposal is vetoed,
     never approved.
  3. **Frozen limits.** The thresholds below are module-level constants. An
     agent can propose whatever it likes; it cannot widen the envelope it is
     judged against.
  4. **Cheap enough to never be skipped.** A full 12-breaker evaluation runs
     in single-digit microseconds (see `benchmark()`), so it sits in the hot
     path of every order with no incentive to bypass it.

The gate can only ever *shrink* or *refuse* a trade. It has no code path that
increases size, loosens a limit, or constructs a position.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DeterministicRiskGate",
    "RiskVerdict",
    "Breaker",
    "PortfolioState",
    "MAX_PORTFOLIO_RISK_PCT",
    "MAX_DELTA_EXPOSURE",
    "MIN_PROBABILITY_OF_PROFIT",
    "benchmark",
]

# ---------------------------------------------------------------------------
# Frozen risk envelope
# ---------------------------------------------------------------------------

MAX_PORTFOLIO_RISK_PCT = 0.02        # Breaker 2: max defined loss per trade, as a fraction of equity
MAX_AGGREGATE_RISK_PCT = 0.06        # Breaker 5: total capital at risk across all open positions
MAX_SYMBOL_RISK_PCT = 0.03           # Breaker 6: concentration cap per underlying
MAX_DELTA_EXPOSURE = 0.35            # Breaker 3: |net delta| per contract-equivalent
MAX_PORTFOLIO_NET_DELTA = 1.20       # Breaker 7: |summed portfolio delta| in contract-equivalents
MIN_PROBABILITY_OF_PROFIT = 0.65     # Breaker 4: minimum risk-neutral P(profit)
MAX_OPEN_POSITIONS = 6               # Breaker 8
MIN_DTE = 7                          # Breaker 9: gamma risk explodes inside a week
MAX_DTE = 60                         # Breaker 9: capital efficiency / theta decay window
MIN_REWARD_RISK_DEBIT = 0.80         # Breaker 10: debit spreads must pay at least 0.8:1
MIN_CREDIT_TO_WIDTH = 0.15           # Breaker 10: credit spreads must collect >=15% of wing width
MAX_DAILY_DRAWDOWN_PCT = 0.03        # Breaker 11: kill switch for the session
MAX_NET_VEGA_PER_1K_EQUITY = 2.50    # Breaker 12: vol exposure ceiling

# Exit guard (evaluated continuously against open positions, not at entry)
STOP_LOSS_PCT_OF_MAX_LOSS = 0.50     # close at 50% of defined max loss
PROFIT_TARGET_PCT_OF_MAX_PROFIT = 0.75
FORCED_EXIT_DTE = 3                  # never carry gamma into expiry week

_ALLOWED_STRATEGIES = frozenset(
    {
        "bull_call_spread",
        "bear_put_spread",
        "bull_put_spread",
        "bear_call_spread",
        "iron_condor",
    }
)

_MISSING = object()


# ---------------------------------------------------------------------------
# Breaker message templates
#
# Held as `str.format` templates rather than f-strings so the gate can build a
# Breaker without paying for the rendering. See `Breaker.detail`.
# ---------------------------------------------------------------------------

_F_STRUCT_OK = "Multi-leg defined-risk structure confirmed"
_F_STRUCT_BAD = (
    "Naked or unrecognised structure ({0}, {1} legs). "
    "Only covered multi-leg spreads may reach the broker."
)
_F_MAXLOSS = "Defined max loss ${0:,.2f} vs ${1:,.2f} cap ({2:.0%} of ${3:,.2f})"
_F_DELTA = "|net delta| {0:.3f} vs {1} bound"
_F_POP = "P(profit) {0:.1%} vs {1:.0%} floor"
_F_AGGREGATE = "Book risk after fill ${0:,.2f} vs ${1:,.2f} cap"
_F_SYMBOL = "{0} risk after fill ${1:,.2f} vs ${2:,.2f} cap"
_F_BOOK_DELTA = "Book |delta| after fill {0:.3f} vs {1} bound"
_F_POSITIONS = "{0} open vs {1} maximum"
_F_DTE = "{0:.0f} DTE vs permitted {1}-{2} window"
_F_CREDIT_WIDTH = "Credit is {0:.1%} of wing width vs {1:.0%} floor"
_F_REWARD_RISK = "Reward:risk {0:.2f} vs {1} floor"
_F_DRAWDOWN = "Session drawdown {0:.2%} vs {1:.0%} kill switch"
_F_VEGA = "Book |vega| after fill {0:,.1f} vs {1:,.1f} ceiling"

_CREDIT_STRATEGIES = frozenset({"bull_put_spread", "bear_call_spread", "iron_condor"})

# Pre-multiplied so breaker 12 needs one multiply instead of a divide-and-scale.
_VEGA_PER_DOLLAR = MAX_NET_VEGA_PER_1K_EQUITY / 1000.0

# A missing max_loss must fail every dollar cap. Using a finite sentinel rather
# than inf keeps the downstream arithmetic and formatting well-defined.
_WORST_LOSS = 1e12

_APPROVED_REASON = "APPROVED: all 12 deterministic breakers satisfied."
_MAX_OPEN_POSITIONS_F = float(MAX_OPEN_POSITIONS)
_MAX_DTE_F = float(MAX_DTE)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Breaker:
    """One circuit-breaker evaluation.

    Materialised lazily. The gate itself never builds these on the hot path --
    it records each result as a plain tuple and `RiskVerdict.breakers` inflates
    them on first access, which is only ever the audit log, the dashboard, or a
    veto message. Twelve object constructions plus twelve rendered
    currency-and-percentage strings cost more than every risk check combined,
    and for an approved order nobody reads a word of it.
    """

    __slots__ = ("id", "name", "passed", "observed", "limit", "_fmt", "_args")

    def __init__(
        self,
        id: int,
        name: str,
        passed: bool,
        fmt: str = "",
        args: Sequence[Any] = (),
        observed: Optional[float] = None,
        limit: Optional[float] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.passed = passed
        self.observed = observed
        self.limit = limit
        self._fmt = fmt
        self._args = args

    @property
    def detail(self) -> str:
        return self._fmt.format(*self._args) if self._fmt else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "observed": self.observed,
            "limit": self.limit,
        }

    def __repr__(self) -> str:
        return f"Breaker({self.id}, {self.name!r}, passed={self.passed})"


def _read(get: Any, key: str, pessimistic: float) -> float:
    """Read a numeric proposal field, falling back to the *worst case*.

    This is the fail-closed rule in code: a missing `max_loss` is not zero, it
    is unbounded. Note that NaN and +/-inf are deliberately allowed through the
    fast path -- every downstream comparison in this module is written so that
    a non-finite value fails its check (``nan <= limit`` is False, and so is
    ``nan >= floor``), which is exactly the behaviour we want.
    """
    value = get(key)
    cls = value.__class__
    if cls is float:
        return value
    if cls is int:
        return float(value)
    if value is None:
        return pessimistic
    try:
        return float(value)
    except (TypeError, ValueError):
        return pessimistic


class RiskVerdict:
    """Full, auditable result of a gate evaluation.

    Also unpacks as ``(approved, reason)`` for callers written against the
    original two-tuple interface.
    """

    __slots__ = ("approved", "reason", "records", "elapsed_us",
                 "approved_contracts", "requested_contracts", "_breakers")

    def __init__(
        self,
        approved: bool,
        reason: str,
        records: Sequence[tuple] = (),
        elapsed_us: float = 0.0,
        approved_contracts: int = 0,
        requested_contracts: int = 0,
    ) -> None:
        self.approved = approved
        self.reason = reason
        self.records = records
        self.elapsed_us = elapsed_us
        self.approved_contracts = approved_contracts
        self.requested_contracts = requested_contracts
        self._breakers: Optional[List[Breaker]] = None

    @property
    def breakers(self) -> List[Breaker]:
        if self._breakers is None:
            self._breakers = [Breaker(*r) for r in self.records]
        return self._breakers

    @property
    def failed(self) -> List[Breaker]:
        return [Breaker(*r) for r in self.records if not r[2]]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.records if r[2])

    @property
    def was_resized(self) -> bool:
        return self.approved and self.approved_contracts < self.requested_contracts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "elapsed_us": round(self.elapsed_us, 3),
            "requested_contracts": self.requested_contracts,
            "approved_contracts": self.approved_contracts,
            "was_resized": self.was_resized,
            "breakers_passed": self.passed_count,
            "breakers_total": len(self.records),
            "breakers": [b.to_dict() for b in self.breakers],
        }

    def __iter__(self):
        yield self.approved
        yield self.reason

    def __repr__(self) -> str:
        return f"RiskVerdict(approved={self.approved}, {self.passed_count}/{len(self.records)} breakers)"


@dataclass(frozen=True)
class PortfolioState:
    """Everything the gate needs to know about existing exposure.

    Defaults describe a flat book, so a caller that omits it gets the
    single-trade checks with no portfolio context -- never a free pass.
    """

    equity: float = 100_000.0
    open_positions: int = 0
    total_capital_at_risk: float = 0.0
    net_delta: float = 0.0
    net_vega: float = 0.0
    risk_by_symbol: Mapping[str, float] = field(default_factory=dict)
    day_pnl: float = 0.0
    start_of_day_equity: float = 0.0

    @property
    def day_drawdown_pct(self) -> float:
        base = self.start_of_day_equity or self.equity
        if base <= 0:
            return 0.0
        return -min(self.day_pnl, 0.0) / base


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class DeterministicRiskGate:
    """Twelve hard-coded circuit breakers. No LLM may override any of them."""

    VERSION = "2.0.0"

    def __init__(self, account_equity: float = 100_000.0) -> None:
        if account_equity <= 0:
            raise ValueError("account_equity must be positive")
        self.account_equity = float(account_equity)
        self.max_allowed_loss = self.account_equity * MAX_PORTFOLIO_RISK_PCT
        self.evaluations = 0
        self.vetoes = 0

    # -- helpers ------------------------------------------------------------

    # -- public API ---------------------------------------------------------

    def evaluate_trade(
        self,
        trade_proposal: Mapping[str, Any],
        portfolio: Optional[PortfolioState] = None,
    ) -> RiskVerdict:
        """Run all twelve breakers against a proposal.

        Every breaker always runs -- there is no short-circuit on first failure,
        because a veto message that names only the first problem hides the rest
        from the audit log. Results are recorded as tuples and inflated into
        `Breaker` objects only if someone reads them.
        """
        t0 = time.perf_counter()
        self.evaluations += 1

        if portfolio is None:
            portfolio = PortfolioState(equity=self.account_equity)
        equity = portfolio.equity or self.account_equity
        max_loss_limit = equity * MAX_PORTFOLIO_RISK_PCT
        get = trade_proposal.get

        # --- Breaker 1: structural -- defined-risk spreads only ------------
        strategy = str(get("strategy", "")).lower()
        leg_count = _read(get, "leg_count", 0.0)
        structural_ok = (
            bool(get("is_defined_risk_spread", False))
            and strategy in _ALLOWED_STRATEGIES
            and leg_count >= 2
        )
        b1 = (
            (1, "defined_risk_structure", True, _F_STRUCT_OK, (), leg_count, 2.0)
            if structural_ok
            else (1, "defined_risk_structure", False, _F_STRUCT_BAD,
                  (strategy or "unspecified", int(leg_count)), leg_count, 2.0)
        )

        # --- Breaker 2: per-trade max loss ---------------------------------
        max_loss = _read(get, "max_loss", _WORST_LOSS)
        b2 = (2, "max_loss_2pct", max_loss <= max_loss_limit, _F_MAXLOSS,
              (max_loss, max_loss_limit, MAX_PORTFOLIO_RISK_PCT, equity), max_loss, max_loss_limit)

        # --- Breaker 3: per-trade delta bound ------------------------------
        raw_delta = _read(get, "net_delta", 99.0)
        net_delta = raw_delta if raw_delta >= 0.0 else -raw_delta
        b3 = (3, "trade_delta_bound", net_delta <= MAX_DELTA_EXPOSURE, _F_DELTA,
              (net_delta, MAX_DELTA_EXPOSURE), net_delta, MAX_DELTA_EXPOSURE)

        # --- Breaker 4: probability of profit ------------------------------
        pop = _read(get, "probability_of_profit", 0.0)
        b4 = (4, "probability_of_profit", pop >= MIN_PROBABILITY_OF_PROFIT, _F_POP,
              (pop, MIN_PROBABILITY_OF_PROFIT), pop, MIN_PROBABILITY_OF_PROFIT)

        # --- Breaker 5: aggregate portfolio risk ---------------------------
        aggregate_limit = equity * MAX_AGGREGATE_RISK_PCT
        projected_risk = portfolio.total_capital_at_risk + max_loss
        b5 = (5, "aggregate_risk_6pct", projected_risk <= aggregate_limit, _F_AGGREGATE,
              (projected_risk, aggregate_limit), projected_risk, aggregate_limit)

        # --- Breaker 6: per-symbol concentration ---------------------------
        symbol = str(get("symbol", "?")).upper()
        symbol_limit = equity * MAX_SYMBOL_RISK_PCT
        projected_symbol = portfolio.risk_by_symbol.get(symbol, 0.0) + max_loss
        b6 = (6, "symbol_concentration_3pct", projected_symbol <= symbol_limit, _F_SYMBOL,
              (symbol, projected_symbol, symbol_limit), projected_symbol, symbol_limit)

        # --- Breaker 7: portfolio net delta --------------------------------
        pd_raw = portfolio.net_delta + raw_delta
        projected_delta = pd_raw if pd_raw >= 0.0 else -pd_raw
        b7 = (7, "portfolio_delta_bound", projected_delta <= MAX_PORTFOLIO_NET_DELTA, _F_BOOK_DELTA,
              (projected_delta, MAX_PORTFOLIO_NET_DELTA), projected_delta, MAX_PORTFOLIO_NET_DELTA)

        # --- Breaker 8: position count -------------------------------------
        open_positions = portfolio.open_positions
        b8 = (8, "max_open_positions", open_positions < MAX_OPEN_POSITIONS, _F_POSITIONS,
              (open_positions, MAX_OPEN_POSITIONS), float(open_positions), _MAX_OPEN_POSITIONS_F)

        # --- Breaker 9: days to expiry window ------------------------------
        dte = _read(get, "dte", -1.0)
        b9 = (9, "dte_window", MIN_DTE <= dte <= MAX_DTE, _F_DTE,
              (dte, MIN_DTE, MAX_DTE), dte, _MAX_DTE_F)

        # --- Breaker 10: payoff quality ------------------------------------
        max_profit = _read(get, "max_profit", 0.0)
        if strategy in _CREDIT_STRATEGIES:
            width = max_profit + max_loss  # credit + (width - credit) == width
            ratio = max_profit / width if width > 0 else 0.0
            b10 = (10, "payoff_quality", ratio >= MIN_CREDIT_TO_WIDTH, _F_CREDIT_WIDTH,
                   (ratio, MIN_CREDIT_TO_WIDTH), ratio, MIN_CREDIT_TO_WIDTH)
        else:
            ratio = max_profit / max_loss if max_loss > 0 else 0.0
            b10 = (10, "payoff_quality", ratio >= MIN_REWARD_RISK_DEBIT, _F_REWARD_RISK,
                   (ratio, MIN_REWARD_RISK_DEBIT), ratio, MIN_REWARD_RISK_DEBIT)

        # --- Breaker 11: daily drawdown kill switch ------------------------
        dd = portfolio.day_drawdown_pct
        b11 = (11, "daily_drawdown_killswitch", dd < MAX_DAILY_DRAWDOWN_PCT, _F_DRAWDOWN,
               (dd, MAX_DAILY_DRAWDOWN_PCT), dd, MAX_DAILY_DRAWDOWN_PCT)

        # --- Breaker 12: vega ceiling --------------------------------------
        vega_limit = equity * _VEGA_PER_DOLLAR
        pv_raw = portfolio.net_vega + _read(get, "net_vega", 0.0)
        projected_vega = pv_raw if pv_raw >= 0.0 else -pv_raw
        b12 = (12, "vega_ceiling", projected_vega <= vega_limit, _F_VEGA,
               (projected_vega, vega_limit), projected_vega, vega_limit)

        records = (b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12)

        # --- Verdict --------------------------------------------------------
        requested = int(_read(get, "contracts", 0.0))

        if b1[2] and b2[2] and b3[2] and b4[2] and b5[2] and b6[2] \
                and b7[2] and b8[2] and b9[2] and b10[2] and b11[2] and b12[2]:
            return RiskVerdict(
                True, _APPROVED_REASON, records,
                (time.perf_counter() - t0) * 1e6, requested, requested,
            )

        self.vetoes += 1
        failed = [r for r in records if not r[2]]
        head = failed[0]
        reason = f"VETO [breaker {head[0]}/{head[1]}]: {head[3].format(*head[4])}"
        if len(failed) > 1:
            reason += f" (+{len(failed) - 1} further breaker{'s' if len(failed) > 2 else ''} failed)"
        return RiskVerdict(
            False, reason, records, (time.perf_counter() - t0) * 1e6, 0, requested,
        )

    # -- position sizing ----------------------------------------------------

    def max_contracts(
        self,
        max_loss_per_contract: float,
        portfolio: Optional[PortfolioState] = None,
        symbol: str = "?",
    ) -> int:
        """Largest contract count that satisfies breakers 2, 5 and 6.

        The gate sizes the trade; the model never does. Returns 0 when no size
        fits, which the desk treats as a refusal rather than a minimum fill.
        """
        if max_loss_per_contract <= 0:
            return 0
        if portfolio is None:
            portfolio = PortfolioState(equity=self.account_equity)
        equity = portfolio.equity or self.account_equity

        headroom = min(
            equity * MAX_PORTFOLIO_RISK_PCT,
            equity * MAX_AGGREGATE_RISK_PCT - portfolio.total_capital_at_risk,
            equity * MAX_SYMBOL_RISK_PCT - float(portfolio.risk_by_symbol.get(symbol.upper(), 0.0)),
        )
        if headroom <= 0:
            return 0
        return max(int(headroom // max_loss_per_contract), 0)

    # -- exit guard ---------------------------------------------------------

    def evaluate_exit(
        self,
        unrealized_pnl: float,
        max_loss: float,
        max_profit: float,
        dte: int,
    ) -> Tuple[bool, str]:
        """Mandatory exit rules for an open position.

        Returns `(should_close, reason)`. These fire without model consultation:
        a 50% stop against defined max loss, a 75% profit target, and a forced
        roll-off inside `FORCED_EXIT_DTE` days so no position is carried into
        the gamma spike at expiry.
        """
        if max_loss > 0 and unrealized_pnl <= -STOP_LOSS_PCT_OF_MAX_LOSS * max_loss:
            return True, (
                f"STOP LOSS: ${unrealized_pnl:,.2f} breached "
                f"{STOP_LOSS_PCT_OF_MAX_LOSS:.0%} of ${max_loss:,.2f} defined max loss."
            )
        if max_profit > 0 and unrealized_pnl >= PROFIT_TARGET_PCT_OF_MAX_PROFIT * max_profit:
            return True, (
                f"PROFIT TARGET: ${unrealized_pnl:,.2f} reached "
                f"{PROFIT_TARGET_PCT_OF_MAX_PROFIT:.0%} of ${max_profit:,.2f} max profit."
            )
        if dte <= FORCED_EXIT_DTE:
            return True, f"EXPIRY GUARD: {dte} DTE is inside the {FORCED_EXIT_DTE}-day no-carry window."
        return False, "HOLD: no exit condition met."

    def envelope(self) -> Dict[str, Any]:
        """The full frozen risk envelope, for the dashboard and the audit log."""
        return {
            "gate_version": self.VERSION,
            "account_equity": self.account_equity,
            "max_loss_per_trade": self.max_allowed_loss,
            "max_portfolio_risk_pct": MAX_PORTFOLIO_RISK_PCT,
            "max_aggregate_risk_pct": MAX_AGGREGATE_RISK_PCT,
            "max_symbol_risk_pct": MAX_SYMBOL_RISK_PCT,
            "max_delta_exposure": MAX_DELTA_EXPOSURE,
            "max_portfolio_net_delta": MAX_PORTFOLIO_NET_DELTA,
            "min_probability_of_profit": MIN_PROBABILITY_OF_PROFIT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "dte_window": [MIN_DTE, MAX_DTE],
            "min_reward_risk_debit": MIN_REWARD_RISK_DEBIT,
            "min_credit_to_width": MIN_CREDIT_TO_WIDTH,
            "max_daily_drawdown_pct": MAX_DAILY_DRAWDOWN_PCT,
            "stop_loss_pct_of_max_loss": STOP_LOSS_PCT_OF_MAX_LOSS,
            "profit_target_pct_of_max_profit": PROFIT_TARGET_PCT_OF_MAX_PROFIT,
            "forced_exit_dte": FORCED_EXIT_DTE,
            "evaluations": self.evaluations,
            "vetoes": self.vetoes,
        }


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

_BENCH_PROPOSAL: Dict[str, Any] = {
    "symbol": "SPY",
    "strategy": "bull_put_spread",
    "is_defined_risk_spread": True,
    "leg_count": 2,
    "contracts": 4,
    "max_loss": 1600.0,
    "max_profit": 400.0,
    "net_delta": 0.18,
    "net_vega": -12.0,
    "probability_of_profit": 0.78,
    "dte": 30,
}


def benchmark(iterations: int = 100_000) -> Dict[str, float]:
    """Measure per-evaluation latency of the full 12-breaker path."""
    gate = DeterministicRiskGate(100_000.0)
    portfolio = PortfolioState(equity=100_000.0)
    # Warm the interpreter so we measure steady state, not first-call overhead.
    for _ in range(1000):
        gate.evaluate_trade(_BENCH_PROPOSAL, portfolio)

    t0 = time.perf_counter()
    for _ in range(iterations):
        gate.evaluate_trade(_BENCH_PROPOSAL, portfolio)
    total = time.perf_counter() - t0

    return {
        "iterations": float(iterations),
        "total_seconds": total,
        "mean_us": (total / iterations) * 1e6,
        "evaluations_per_second": iterations / total,
    }


if __name__ == "__main__":
    gate = DeterministicRiskGate(account_equity=100_000.0)

    print("=" * 74)
    print(f" DEFLOW DETERMINISTIC RISK GATE v{DeterministicRiskGate.VERSION} — 12 zero-LLM circuit breakers")
    print("=" * 74)

    cases = [
        (
            "Bull call spread, sized inside every limit",
            {
                "symbol": "SPY", "strategy": "bull_call_spread", "is_defined_risk_spread": True,
                "leg_count": 2, "contracts": 3, "max_loss": 1425.0, "max_profit": 1575.0,
                "net_delta": 0.22, "net_vega": 7.1, "probability_of_profit": 0.68, "dte": 35,
            },
        ),
        (
            "Naked call — no long wing to cap the loss",
            {
                "symbol": "NVDA", "strategy": "naked_call", "is_defined_risk_spread": False,
                "leg_count": 1, "contracts": 1, "max_loss": 15000.0, "max_profit": 480.0,
                "net_delta": 0.31, "probability_of_profit": 0.72, "dte": 21,
            },
        ),
        (
            "Correctly structured spread, oversized to 4.2% of equity",
            {
                "symbol": "QQQ", "strategy": "bull_put_spread", "is_defined_risk_spread": True,
                "leg_count": 2, "contracts": 12, "max_loss": 4200.0, "max_profit": 800.0,
                "net_delta": 0.19, "net_vega": -20.0, "probability_of_profit": 0.81, "dte": 30,
            },
        ),
        (
            "Proposal with max_loss omitted entirely (fail-closed test)",
            {
                "symbol": "SPY", "strategy": "iron_condor", "is_defined_risk_spread": True,
                "leg_count": 4, "contracts": 2, "max_profit": 300.0,
                "net_delta": 0.02, "probability_of_profit": 0.84, "dte": 28,
            },
        ),
        (
            "0-DTE lottery ticket inside the gamma window",
            {
                "symbol": "SPY", "strategy": "bear_call_spread", "is_defined_risk_spread": True,
                "leg_count": 2, "contracts": 2, "max_loss": 800.0, "max_profit": 200.0,
                "net_delta": 0.12, "probability_of_profit": 0.88, "dte": 0,
            },
        ),
    ]

    for title, proposal in cases:
        verdict = gate.evaluate_trade(proposal, PortfolioState(equity=100_000.0))
        mark = "PASS" if verdict.approved else "VETO"
        print(f"\n[{mark}] {title}")
        print(f"       {verdict.reason}")
        print(f"       {sum(1 for b in verdict.breakers if b.passed)}/{len(verdict.breakers)} breakers passed "
              f"in {verdict.elapsed_us:.2f} µs")
        for b in verdict.failed:
            print(f"         x breaker {b.id:>2} {b.name}: {b.detail}")

    print("\n" + "-" * 74)
    stats = benchmark(50_000)
    print(f" Latency: {stats['mean_us']:.2f} µs mean over {int(stats['iterations']):,} evaluations "
          f"({stats['evaluations_per_second']:,.0f}/sec)")
    print(f" Session: {gate.evaluations} evaluations, {gate.vetoes} vetoes")
    print("-" * 74)
