"""Detecting an unpriced event from the volatility term structure.

Alpaca serves no earnings calendar -- `/v1beta1/earnings` does not exist and
corporate actions return dividends only -- so a date-based guard is not
available. The options themselves are a better source anyway.

In a quiet market the implied-vol term structure slopes gently upward: longer
options carry a little more vol because there is more time for something to go
wrong. When a dated catalyst sits inside the front expiry that inverts. The
front contract prices the whole jump over a few days, while a later one
amortises the same jump across months, so front vol rises *above* back vol.

That inversion is the signal. It requires no calendar, it is measured from live
quotes, and it catches anything the market is pricing -- an earnings print, a
trial readout, a rate decision -- rather than only the events some vendor
happens to list.

Why the desk cares: selling defined-risk premium that expires *after* a
catalyst means being short the gap. The credit looks generous precisely because
the market knows what is coming. That is not variance risk premium being
harvested; it is being paid a fair price for a real risk, and the whole thesis
of this desk is the difference between those two things.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from .models import OptionQuote

log = logging.getLogger("deflow.events")

# One expiry's vol this much above the NEXT one out means a catalyst sits
# between them. Normal term structure slopes gently upward, so any ratio above
# 1.0 is already unusual; 1.15 keeps ordinary curvature and quote noise out.
INVERSION_RATIO = 1.15

# Contracts inside a week carry structurally inflated at-the-money vol -- the
# gamma and pin effects near expiry, not a catalyst -- and comparing against
# them reports an event on almost every symbol. The curve is therefore read
# only across the window the desk actually trades.
MIN_DTE = 7
MAX_DTE = 60

MIN_EXPIRIES = 2
MIN_QUOTES_PER_EXPIRY = 6


@dataclass
class EventRisk:
    """What the term structure implies about a catalyst."""

    detected: bool
    expiry: Optional[date] = None          # the last expiry BEFORE the catalyst is safe
    front_iv: float = 0.0
    back_iv: float = 0.0
    ratio: float = 1.0
    front_expiry: Optional[date] = None
    back_expiry: Optional[date] = None
    term: List[Dict[str, object]] = field(default_factory=list)

    @property
    def implied_move(self) -> float:
        """Rough size of the move the front expiry is pricing, as a fraction.

        The excess variance in the front contract over the back one, converted
        back to a one-day move. This is what the auditor uses to widen its
        jump assumption rather than stressing the position at a calm-market
        gap size.
        """
        if not self.detected or self.front_iv <= 0:
            return 0.0
        excess = max(self.front_iv**2 - self.back_iv**2, 0.0)
        return min((excess**0.5) / (252**0.5), 0.30)

    def to_dict(self) -> Dict[str, object]:
        return {
            "detected": self.detected,
            "front_iv": round(self.front_iv, 4),
            "back_iv": round(self.back_iv, 4),
            "ratio": round(self.ratio, 3),
            "front_expiry": self.front_expiry.isoformat() if self.front_expiry else None,
            "back_expiry": self.back_expiry.isoformat() if self.back_expiry else None,
            "safe_through": self.expiry.isoformat() if self.expiry else None,
            "implied_move": round(self.implied_move, 4),
        }

    def summary(self) -> str:
        if not self.detected:
            return f"term structure normal (front/back {self.ratio:.2f})"
        return (
            f"event priced before {self.front_expiry:%d %b}: front IV {self.front_iv:.1%} vs "
            f"back {self.back_iv:.1%} ({self.ratio:.2f}×), implying a "
            f"{self.implied_move:.1%} move"
        )


def _atm_iv_by_expiry(chain: Sequence[OptionQuote], spot: float) -> Dict[date, float]:
    """Average implied vol of the contracts closest to the money, per expiry.

    Restricted to the DTE window the desk trades. Including sub-week contracts
    made every symbol look like it had an event, because their at-the-money vol
    is inflated by proximity to expiry rather than by anything in the calendar.
    """
    buckets: Dict[date, List[OptionQuote]] = {}
    for q in chain:
        if q.implied_vol > 0 and q.mid > 0 and MIN_DTE <= q.dte <= MAX_DTE:
            buckets.setdefault(q.expiry, []).append(q)

    out: Dict[date, float] = {}
    for expiry, quotes in buckets.items():
        if len(quotes) < MIN_QUOTES_PER_EXPIRY:
            continue
        nearest = min(abs(q.strike - spot) for q in quotes)
        # Take the strikes within a small band of the money; a single contract
        # is too easy to skew with one stale quote.
        band = [q.implied_vol for q in quotes if abs(q.strike - spot) <= nearest + spot * 0.01]
        if band:
            out[expiry] = sum(band) / len(band)
    return out


def detect(chain: Sequence[OptionQuote], spot: float) -> EventRisk:
    """Read the term structure for a priced-in catalyst.

    Walks the curve comparing each expiry to the NEXT one out, rather than to
    the furthest. A single thin far-dated expiry with a stale quote would
    otherwise set the reference for the whole curve -- and far-dated option
    quotes are exactly where staleness lives.

    The first inversion found is the relevant one: if expiry i prices more vol
    than expiry i+1, the market expects something to happen on or before i, and
    everything expiring from i onward is short that move.
    """
    if spot <= 0:
        return EventRisk(False)

    curve = _atm_iv_by_expiry(chain, spot)
    if len(curve) < MIN_EXPIRIES:
        return EventRisk(False)

    expiries = sorted(curve)
    term = [{"expiry": e.isoformat(), "atm_iv": round(curve[e], 4)} for e in expiries]

    worst_ratio = 0.0
    hit: Optional[int] = None
    for i in range(len(expiries) - 1):
        near, far = curve[expiries[i]], curve[expiries[i + 1]]
        if far <= 0:
            continue
        ratio = near / far
        if ratio > worst_ratio:
            worst_ratio = ratio
        if ratio >= INVERSION_RATIO and hit is None:
            hit = i

    if hit is None:
        return EventRisk(
            False,
            front_iv=curve[expiries[0]], back_iv=curve[expiries[-1]],
            ratio=worst_ratio, front_expiry=expiries[0], back_expiry=expiries[-1],
            term=term,
        )

    front, back = expiries[hit], expiries[hit + 1]
    # Everything expiring on or after `front` spans the catalyst. An expiry
    # strictly before it does not -- so that is what remains safe to sell.
    safe = expiries[hit - 1] if hit > 0 else None
    return EventRisk(
        True, expiry=safe,
        front_iv=curve[front], back_iv=curve[back],
        ratio=curve[front] / curve[back], front_expiry=front, back_expiry=back,
        term=term,
    )


def expiry_is_exposed(risk: EventRisk, expiry: date) -> bool:
    """Would a structure expiring on `expiry` be held through the catalyst?

    Anything expiring on or after the front expiry spans it. An option that
    expires strictly before the elevated contract does not.
    """
    if not risk.detected or risk.front_expiry is None:
        return False
    return expiry >= risk.front_expiry


__all__ = ["EventRisk", "INVERSION_RATIO", "detect", "expiry_is_exposed"]
