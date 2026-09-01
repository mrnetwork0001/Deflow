"""Statistics the Analyst runs over daily bars. Standard library only."""

from __future__ import annotations

import math
from typing import List, Sequence

TRADING_DAYS = 252.0


def log_returns(closes: Sequence[float]) -> List[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]


def realized_vol(closes: Sequence[float], window: int = 20) -> float:
    """Annualised close-to-close realised volatility over the last `window` bars."""
    rets = log_returns(closes[-(window + 1):])
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * TRADING_DAYS)


def rolling_realized_vol(closes: Sequence[float], window: int = 20) -> List[float]:
    """The full realised-vol series, which is what an IV rank is measured against."""
    out: List[float] = []
    for end in range(window + 1, len(closes) + 1):
        out.append(realized_vol(closes[end - window - 1:end], window))
    return out


def sma(values: Sequence[float], window: int) -> float:
    if len(values) < window or window <= 0:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-window:]) / window


def rsi(closes: Sequence[float], window: int = 14) -> float:
    """Wilder's RSI. Returns the neutral 50 when there is not enough history."""
    if len(closes) < window + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(len(closes) - window, len(closes)):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain, avg_loss = gains / window, losses / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def percentile_rank(value: float, sample: Sequence[float]) -> float:
    """Fraction of `sample` at or below `value`, in [0, 1]."""
    if not sample:
        return 0.5
    return sum(1 for s in sample if s <= value) / len(sample)


def range_rank(value: float, sample: Sequence[float]) -> float:
    """Position of `value` inside the min-max range of `sample`, clipped to [0, 1].

    This is the classic "IV rank" definition (as opposed to "IV percentile",
    which is `percentile_rank` above). Deflow reports both.
    """
    if not sample:
        return 0.5
    lo, hi = min(sample), max(sample)
    if hi - lo < 1e-9:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def trend_score(closes: Sequence[float]) -> float:
    """Composite trend reading in [-1, +1].

    Blends three views that disagree in useful ways: where price sits relative
    to its 20- and 50-day averages, whether the short average is above the
    long one, and 10-day momentum. Any single one of these whipsaws; the
    average of the three is what the regime classifier consumes.
    """
    if len(closes) < 50:
        return 0.0
    price = closes[-1]
    s20, s50 = sma(closes, 20), sma(closes, 50)
    if s50 <= 0 or s20 <= 0:
        return 0.0

    # Each component is squashed into [-1, 1] by a scale chosen so that a
    # typical 1-sigma equity-index move lands around +/-0.5, not pinned at 1.
    above_20 = max(-1.0, min(1.0, (price / s20 - 1.0) / 0.02))
    above_50 = max(-1.0, min(1.0, (price / s50 - 1.0) / 0.05))
    ma_cross = max(-1.0, min(1.0, (s20 / s50 - 1.0) / 0.03))
    momentum = max(-1.0, min(1.0, (price / closes[-11] - 1.0) / 0.04)) if len(closes) > 11 else 0.0

    return (above_20 + above_50 + ma_cross + momentum) / 4.0


__all__ = [
    "log_returns",
    "percentile_rank",
    "range_rank",
    "realized_vol",
    "rolling_realized_vol",
    "rsi",
    "sma",
    "trend_score",
]
