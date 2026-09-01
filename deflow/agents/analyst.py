"""Agent 1 — Macro & Volatility Analyst.

Answers one question per symbol: *is option premium currently rich or cheap,
and which way is the underlying leaning?*

The edge Deflow trades is the **variance risk premium** -- the persistent gap
between the volatility implied by option prices and the volatility the
underlying actually delivers. When implied sits meaningfully above realised,
selling defined-risk premium has positive expectancy under the physical
measure; when it sits below, owning convexity does. When the gap is inside the
noise band, the correct action is to do nothing, and this agent says so.

Nothing here is a model's opinion. Every number is computed from bars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models import MarketSnapshot, utcnow

log = logging.getLogger("deflow.analyst")

# Bands on (implied - realised). Chosen so that the "sell premium" branch needs
# a genuine cushion rather than a rounding error, and the symmetric "buy
# convexity" branch needs implied to be visibly cheap.
VRP_RICH = 0.020        # implied >= realised + 2 vol points -> premium is rich
VRP_CHEAP = -0.010      # implied <= realised - 1 vol point  -> convexity is cheap

MIN_IV_RANK_TO_SELL = 0.40
MAX_IV_RANK_TO_BUY = 0.55


@dataclass
class AnalystView:
    """The Analyst's verdict on one underlying."""

    snapshot: MarketSnapshot
    stance: str                      # "sell_premium" | "buy_convexity" | "stand_down"
    bias: str                        # "bullish" | "bearish" | "neutral"
    conviction: float                # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)
    as_of: str = field(default_factory=utcnow)

    @property
    def tradeable(self) -> bool:
        return self.stance != "stand_down"

    def brief(self) -> str:
        s = self.snapshot
        return (
            f"{s.symbol} @ ${s.price:,.2f} | regime={s.regime.value} | "
            f"IV30={s.iv_30d:.1%} HVfc={s.hv_forecast:.1%} VRP={s.variance_premium:+.1%} | "
            f"IV rank={s.iv_rank:.0%} | trend={s.trend_score:+.2f} RSI={s.rsi14:.0f} | "
            f"stance={self.stance} bias={self.bias} conviction={self.conviction:.0%}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.snapshot.to_dict(),
            "stance": self.stance,
            "bias": self.bias,
            "conviction": round(self.conviction, 3),
            "tradeable": self.tradeable,
            "reasons": self.reasons,
            "brief": self.brief(),
        }


class MacroVolatilityAnalyst:
    """Scans the universe and classifies each name's volatility regime."""

    name = "Agent 1 · Macro & Volatility Analyst"

    def __init__(self, provider: Any) -> None:
        self.provider = provider

    def analyse(self, symbol: str) -> Optional[AnalystView]:
        snapshot = self.provider.snapshot(symbol)
        if snapshot is None:
            return None
        return self.classify(snapshot)

    def scan(self, universe: List[str]) -> List[AnalystView]:
        views = []
        for symbol in universe:
            try:
                view = self.analyse(symbol)
            except Exception as exc:  # one bad symbol must not stop the desk
                log.exception("Analyst failed on %s: %s", symbol, exc)
                continue
            if view is not None:
                views.append(view)
        return views

    # -- classification -----------------------------------------------------

    @staticmethod
    def classify(s: MarketSnapshot) -> AnalystView:
        reasons: List[str] = []
        vrp = s.variance_premium

        # --- Stance: are options rich or cheap? ----------------------------
        if vrp >= VRP_RICH and s.iv_rank >= MIN_IV_RANK_TO_SELL:
            stance = "sell_premium"
            reasons.append(
                f"Implied {s.iv_30d:.1%} exceeds forecast realised {s.hv_forecast:.1%} by "
                f"{vrp:+.1%} ({vrp * 100:.1f} vol points) with IV rank at {s.iv_rank:.0%} — "
                f"premium is rich."
            )
        elif vrp <= VRP_CHEAP and s.iv_rank <= MAX_IV_RANK_TO_BUY:
            stance = "buy_convexity"
            reasons.append(
                f"Implied {s.iv_30d:.1%} sits below forecast realised {s.hv_forecast:.1%} "
                f"({vrp:+.1%}) with IV rank at {s.iv_rank:.0%} — convexity is underpriced."
            )
        else:
            stance = "stand_down"
            # Three different things bring us here, and conflating them makes
            # the ledger unreadable. Name the one that actually applied.
            if vrp >= VRP_RICH:
                reasons.append(
                    f"Variance premium {vrp:+.1%} is rich, but IV rank {s.iv_rank:.0%} is below the "
                    f"{MIN_IV_RANK_TO_SELL:.0%} floor — implied is above realised only because realised "
                    f"has collapsed, not because premium is historically elevated."
                )
            elif vrp <= VRP_CHEAP:
                reasons.append(
                    f"Implied sits {vrp:+.1%} below realised, but IV rank {s.iv_rank:.0%} is above the "
                    f"{MAX_IV_RANK_TO_BUY:.0%} ceiling — options are cheap against a realised move that "
                    f"is itself extreme, so owning convexity here is paying up near the highs."
                )
            else:
                reasons.append(
                    f"Variance premium {vrp:+.1%} is inside the [{VRP_CHEAP:+.1%}, {VRP_RICH:+.1%}] "
                    f"noise band (IV rank {s.iv_rank:.0%}) — no volatility edge to trade."
                )

        # --- Directional bias ----------------------------------------------
        if s.trend_score >= 0.25:
            bias = "bullish"
            reasons.append(f"Trend score {s.trend_score:+.2f}: price above the 20/50-day structure.")
        elif s.trend_score <= -0.25:
            bias = "bearish"
            reasons.append(f"Trend score {s.trend_score:+.2f}: price below the 20/50-day structure.")
        else:
            bias = "neutral"
            reasons.append(f"Trend score {s.trend_score:+.2f}: no directional edge, range-bound.")

        # An overheated or washed-out RSI argues against pressing the trend.
        if bias == "bullish" and s.rsi14 > 72:
            reasons.append(f"RSI {s.rsi14:.0f} is overbought — directional conviction reduced.")
        elif bias == "bearish" and s.rsi14 < 28:
            reasons.append(f"RSI {s.rsi14:.0f} is oversold — directional conviction reduced.")

        return AnalystView(
            snapshot=s,
            stance=stance,
            bias=bias,
            conviction=MacroVolatilityAnalyst._conviction(s, stance, bias),
            reasons=reasons,
        )

    @staticmethod
    def _conviction(s: MarketSnapshot, stance: str, bias: str) -> float:
        """Blend the volatility signal with the trend signal into [0, 1].

        Deliberately conservative: even a perfect setup tops out below 1.0, so
        the desk never treats any single reading as certainty.
        """
        if stance == "stand_down":
            return 0.0

        # Volatility component: how far past the band, normalised over 4 points.
        vrp = s.variance_premium
        edge = (vrp - VRP_RICH) if stance == "sell_premium" else (VRP_CHEAP - vrp)
        vol_score = max(0.0, min(1.0, edge / 0.04))

        # Rank component: extremes of the IV-rank range are the higher-quality
        # entries for each stance.
        rank_score = s.iv_rank if stance == "sell_premium" else (1.0 - s.iv_rank)

        trend_strength = min(abs(s.trend_score), 1.0)
        # A premium seller is happy trading a neutral tape (iron condor);
        # a convexity buyer needs a direction to pay for the theta.
        trend_score = (0.55 + 0.45 * trend_strength) if stance == "sell_premium" else trend_strength

        rsi_penalty = 0.0
        if bias == "bullish" and s.rsi14 > 72:
            rsi_penalty = 0.12
        elif bias == "bearish" and s.rsi14 < 28:
            rsi_penalty = 0.12

        raw = 0.45 * vol_score + 0.30 * rank_score + 0.25 * trend_score - rsi_penalty
        return max(0.0, min(0.92, raw))


__all__ = ["AnalystView", "MacroVolatilityAnalyst", "VRP_CHEAP", "VRP_RICH"]
