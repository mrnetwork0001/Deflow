"""Core domain objects shared by all four agents and the risk gate.

Plain dataclasses, not pydantic models: these cross the boundary into
risk_gate.py, which is deliberately dependency-free.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .greeks import Greeks, OptionRight, black_scholes, probability_itm, years_to_expiry

CONTRACT_MULTIPLIER = 100.0


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Strategy(str, Enum):
    """The five defined-risk structures Deflow is allowed to trade."""

    BULL_CALL_SPREAD = "bull_call_spread"    # debit,  long vol / bullish
    BEAR_PUT_SPREAD = "bear_put_spread"      # debit,  long vol / bearish
    BULL_PUT_SPREAD = "bull_put_spread"      # credit, short vol / bullish
    BEAR_CALL_SPREAD = "bear_call_spread"    # credit, short vol / bearish
    IRON_CONDOR = "iron_condor"              # credit, short vol / neutral

    @property
    def is_credit(self) -> bool:
        return self in {Strategy.BULL_PUT_SPREAD, Strategy.BEAR_CALL_SPREAD, Strategy.IRON_CONDOR}

    @property
    def is_debit(self) -> bool:
        return not self.is_credit

    @property
    def direction(self) -> str:
        if self in {Strategy.BULL_CALL_SPREAD, Strategy.BULL_PUT_SPREAD}:
            return "bullish"
        if self in {Strategy.BEAR_PUT_SPREAD, Strategy.BEAR_CALL_SPREAD}:
            return "bearish"
        return "neutral"


class Regime(str, Enum):
    """Volatility/trend regime emitted by the Analyst."""

    HIGH_VOL_BULL = "high_vol_bull"
    HIGH_VOL_BEAR = "high_vol_bear"
    HIGH_VOL_RANGE = "high_vol_range"
    LOW_VOL_BULL = "low_vol_bull"
    LOW_VOL_BEAR = "low_vol_bear"
    LOW_VOL_RANGE = "low_vol_range"


# --------------------------------------------------------------------------
# OCC option symbology
# --------------------------------------------------------------------------

_OCC_RE = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")


def occ_symbol(underlying: str, expiry: date, right: OptionRight, strike: float) -> str:
    """Build an OCC-21 contract symbol, e.g. SPY261218C00450000.

    Alpaca's options endpoints speak OCC, so every leg carries one.
    """
    cp = "C" if right == "call" else "P"
    # Strike is encoded in thousandths of a dollar, zero-padded to 8 chars.
    strike_int = int(round(strike * 1000))
    return f"{underlying.upper()}{expiry:%y%m%d}{cp}{strike_int:08d}"


def parse_occ(symbol: str) -> Dict[str, Any]:
    """Inverse of `occ_symbol`. Raises ValueError on a malformed symbol."""
    m = _OCC_RE.match(symbol.strip().upper())
    if not m:
        raise ValueError(f"Not a valid OCC option symbol: {symbol!r}")
    g = m.groupdict()
    return {
        "underlying": g["root"],
        "expiry": date(2000 + int(g["yy"]), int(g["mm"]), int(g["dd"])),
        "right": "call" if g["cp"] == "C" else "put",
        "strike": int(g["strike"]) / 1000.0,
    }


# --------------------------------------------------------------------------
# Quotes and legs
# --------------------------------------------------------------------------

@dataclass
class OptionQuote:
    """NBBO snapshot for a single contract."""

    symbol: str
    bid: float
    ask: float
    underlying_price: float
    strike: float
    right: OptionRight
    expiry: date
    implied_vol: float = 0.0
    open_interest: int = 0
    volume: int = 0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return max(self.bid, self.ask)

    @property
    def spread_pct(self) -> float:
        """Bid/ask width as a fraction of mid -- the liquidity filter's input."""
        mid = self.mid
        if mid <= 0:
            return 1.0
        return (self.ask - self.bid) / mid

    @property
    def dte(self) -> int:
        return max((self.expiry - date.today()).days, 0)

    def greeks(self, sigma: Optional[float] = None) -> Greeks:
        return black_scholes(
            self.underlying_price,
            self.strike,
            years_to_expiry(self.dte),
            sigma if sigma is not None else (self.implied_vol or 0.20),
            self.right,
        )


@dataclass
class Leg:
    """One leg of a multi-leg order. `ratio` is positive long, negative short."""

    symbol: str
    right: OptionRight
    strike: float
    expiry: date
    ratio: int                  # +1 buy, -1 sell
    price: float                # per-share mid used for structuring
    implied_vol: float = 0.20
    # Half the quoted bid/ask width at construction time. Carried on the leg so
    # the auditor can cost a round trip from real quotes instead of estimating
    # it, and so the structurer can penalise wide markets while ranking.
    half_spread: float = 0.0

    @property
    def side(self) -> str:
        return "buy" if self.ratio > 0 else "sell"

    @property
    def position_intent(self) -> str:
        return "buy_to_open" if self.ratio > 0 else "sell_to_open"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["expiry"] = self.expiry.isoformat()
        d["side"] = self.side
        return d


# --------------------------------------------------------------------------
# Trade proposal
# --------------------------------------------------------------------------

@dataclass
class SpreadProposal:
    """A fully-specified, defined-risk multi-leg options trade.

    Every field the risk gate inspects is computed here from the legs, not
    supplied by a model. The LLM can choose *which* structure to propose; it
    can never assert what that structure risks.
    """

    symbol: str
    strategy: Strategy
    legs: List[Leg]
    contracts: int
    underlying_price: float
    thesis: str = ""
    iv_rank: float = 0.0
    regime: Regime = Regime.LOW_VOL_RANGE
    proposed_at: str = field(default_factory=utcnow)
    proposal_id: str = ""
    source: str = "structurer"

    # ---- Economics, derived from the legs ---------------------------------

    @property
    def net_premium(self) -> float:
        """Per-spread cash flow, per share. Positive = debit paid, negative = credit received."""
        return sum(leg.ratio * leg.price for leg in self.legs)

    @property
    def net_debit(self) -> float:
        return max(self.net_premium, 0.0)

    @property
    def net_credit(self) -> float:
        return max(-self.net_premium, 0.0)

    @property
    def widest_wing(self) -> float:
        """Widest same-right strike gap -- the structural loss cap for a vertical/condor."""
        widest = 0.0
        for right in ("call", "put"):
            strikes = sorted(leg.strike for leg in self.legs if leg.right == right)
            if len(strikes) >= 2:
                widest = max(widest, strikes[-1] - strikes[0])
        return widest

    @property
    def max_loss(self) -> float:
        """Worst case in dollars across the whole position.

        Debit spreads: you cannot lose more than you paid.
        Credit spreads / condors: width of the tested wing minus credit taken.
        """
        per_spread = (
            self.net_debit
            if self.strategy.is_debit
            else max(self.widest_wing - self.net_credit, 0.0)
        )
        return per_spread * CONTRACT_MULTIPLIER * self.contracts

    @property
    def max_profit(self) -> float:
        per_spread = (
            max(self.widest_wing - self.net_debit, 0.0)
            if self.strategy.is_debit
            else self.net_credit
        )
        return per_spread * CONTRACT_MULTIPLIER * self.contracts

    @property
    def capital_at_risk(self) -> float:
        """Buying power the broker will hold. Same as max loss for defined-risk."""
        return self.max_loss

    @property
    def reward_risk(self) -> float:
        return self.max_profit / self.max_loss if self.max_loss > 0 else 0.0

    # ---- Risk surface ------------------------------------------------------

    def portfolio_greeks(self) -> Greeks:
        """Position Greeks, summed across legs and scaled by contracts."""
        total = Greeks(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for leg in self.legs:
            dte = max((leg.expiry - date.today()).days, 0)
            g = black_scholes(
                self.underlying_price, leg.strike, years_to_expiry(dte), leg.implied_vol or 0.20, leg.right
            ).scaled(leg.ratio * self.contracts, CONTRACT_MULTIPLIER)
            total = Greeks(
                price=total.price + g.price,
                delta=total.delta + g.delta,
                gamma=total.gamma + g.gamma,
                vega=total.vega + g.vega,
                theta=total.theta + g.theta,
                rho=total.rho + g.rho,
            )
        return total

    @property
    def net_delta(self) -> float:
        """Delta expressed per-contract-equivalent so it is comparable to the 0.35 bound.

        Raw position delta scales with size; normalising by (contracts x 100)
        keeps the gate's threshold meaningful across position sizes.
        """
        raw = self.portfolio_greeks().delta
        denom = CONTRACT_MULTIPLIER * max(self.contracts, 1)
        return raw / denom

    @property
    def dte(self) -> int:
        return min((leg.expiry - date.today()).days for leg in self.legs) if self.legs else 0

    def probability_of_profit(self) -> float:
        """Risk-neutral P(profit at expiry), computed from breakevens.

        Verticals have a single breakeven; the condor has two and profits
        between them.
        """
        sigma = sum(leg.implied_vol for leg in self.legs) / max(len(self.legs), 1) or 0.20
        T = years_to_expiry(self.dte)
        S = self.underlying_price
        bes = self.breakevens()
        if not bes:
            return 0.0
        if self.strategy is Strategy.IRON_CONDOR:
            lo, hi = min(bes), max(bes)
            # P(lo < S_T < hi) = P(S_T > lo) - P(S_T > hi)
            return max(
                probability_itm(S, lo, T, sigma, "call") - probability_itm(S, hi, T, sigma, "call"), 0.0
            )
        be = bes[0]
        if self.strategy.direction == "bullish":
            return probability_itm(S, be, T, sigma, "call")
        return probability_itm(S, be, T, sigma, "put")

    def breakevens(self) -> List[float]:
        """Underlying prices at which the structure breaks even at expiry."""
        if self.strategy is Strategy.BULL_CALL_SPREAD:
            longs = [l.strike for l in self.legs if l.ratio > 0]
            return [min(longs) + self.net_debit] if longs else []
        if self.strategy is Strategy.BEAR_PUT_SPREAD:
            longs = [l.strike for l in self.legs if l.ratio > 0]
            return [max(longs) - self.net_debit] if longs else []
        if self.strategy is Strategy.BULL_PUT_SPREAD:
            shorts = [l.strike for l in self.legs if l.ratio < 0]
            return [max(shorts) - self.net_credit] if shorts else []
        if self.strategy is Strategy.BEAR_CALL_SPREAD:
            shorts = [l.strike for l in self.legs if l.ratio < 0]
            return [min(shorts) + self.net_credit] if shorts else []
        if self.strategy is Strategy.IRON_CONDOR:
            short_put = max((l.strike for l in self.legs if l.ratio < 0 and l.right == "put"), default=None)
            short_call = min((l.strike for l in self.legs if l.ratio < 0 and l.right == "call"), default=None)
            if short_put is None or short_call is None:
                return []
            return [short_put - self.net_credit, short_call + self.net_credit]
        return []

    @property
    def is_defined_risk(self) -> bool:
        """True only if every short leg is covered by a long of the same right.

        This is the structural check behind the gate's "no naked options" rule:
        it counts contracts per right and refuses any right where shorts
        outnumber longs.
        """
        if len(self.legs) < 2:
            return False
        for right in ("call", "put"):
            longs = sum(l.ratio for l in self.legs if l.right == right and l.ratio > 0)
            shorts = -sum(l.ratio for l in self.legs if l.right == right and l.ratio < 0)
            if shorts > longs:
                return False
        # A long wing only caps risk if it exists at a strike beyond the short.
        return math.isfinite(self.max_loss) and self.max_loss > 0

    # ---- Serialisation -----------------------------------------------------

    def to_risk_payload(self) -> Dict[str, Any]:
        """The exact dict handed to `DeterministicRiskGate.evaluate_trade`."""
        g = self.portfolio_greeks()
        return {
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "is_defined_risk_spread": self.is_defined_risk,
            "leg_count": len(self.legs),
            "contracts": self.contracts,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "net_delta": self.net_delta,
            "net_vega": g.vega,
            "net_theta": g.theta,
            "net_gamma": g.gamma,
            "probability_of_profit": self.probability_of_profit(),
            "reward_risk": self.reward_risk,
            "dte": self.dte,
            "underlying_price": self.underlying_price,
            "iv_rank": self.iv_rank,
        }

    def to_dict(self) -> Dict[str, Any]:
        g = self.portfolio_greeks()
        return {
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "direction": self.strategy.direction,
            "is_credit": self.strategy.is_credit,
            "contracts": self.contracts,
            "underlying_price": round(self.underlying_price, 2),
            "legs": [l.to_dict() for l in self.legs],
            "net_premium": round(self.net_premium, 4),
            "max_loss": round(self.max_loss, 2),
            "max_profit": round(self.max_profit, 2),
            "reward_risk": round(self.reward_risk, 3),
            "probability_of_profit": round(self.probability_of_profit(), 4),
            "breakevens": [round(b, 2) for b in self.breakevens()],
            "net_delta": round(self.net_delta, 4),
            "greeks": {
                "delta": round(g.delta, 3),
                "gamma": round(g.gamma, 4),
                "vega": round(g.vega, 3),
                "theta": round(g.theta, 3),
            },
            "dte": self.dte,
            "iv_rank": round(self.iv_rank, 3),
            "regime": self.regime.value,
            "thesis": self.thesis,
            "proposed_at": self.proposed_at,
            "source": self.source,
        }


@dataclass
class MarketSnapshot:
    """Analyst output for one underlying."""

    symbol: str
    price: float
    iv_rank: float
    iv_30d: float
    hv_60d: float
    trend_score: float          # -1 (strong down) .. +1 (strong up)
    regime: Regime
    sma20: float = 0.0
    sma50: float = 0.0
    rsi14: float = 50.0
    variance_premium: float = 0.0   # iv_30d - hv_60d
    as_of: str = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": round(self.price, 2),
            "iv_rank": round(self.iv_rank, 3),
            "iv_30d": round(self.iv_30d, 4),
            "hv_60d": round(self.hv_60d, 4),
            "variance_premium": round(self.variance_premium, 4),
            "trend_score": round(self.trend_score, 3),
            "regime": self.regime.value,
            "sma20": round(self.sma20, 2),
            "sma50": round(self.sma50, 2),
            "rsi14": round(self.rsi14, 1),
            "as_of": self.as_of,
        }


__all__ = [
    "CONTRACT_MULTIPLIER",
    "Leg",
    "MarketSnapshot",
    "OptionQuote",
    "Regime",
    "SpreadProposal",
    "Strategy",
    "occ_symbol",
    "parse_occ",
    "utcnow",
]
