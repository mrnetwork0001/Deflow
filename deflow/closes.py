"""Settled end-of-session equity, one number per trading day.

Alpaca's own history surfaces proved unreliable for this account (the intraday
equity series arrives on a gains basis, and the daily series lagged a full
session), but one identity cannot be wrong: while the market is closed, the
account's current equity IS the previous session's close -- nothing trades
overnight in it. Captured on that rule and recorded here, each close becomes a
settled, re-checkable fact instead of a number that a later API quirk can
rewrite.
"""

from __future__ import annotations

import json
import logging
from typing import Dict

from .config import DATA_DIR

log = logging.getLogger("deflow.closes")

_PATH = DATA_DIR / "daily_closes.json"


def read_daily_closes() -> Dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(_PATH.read_text()).items()}
    except (OSError, ValueError, TypeError):
        return {}


def record_daily_close(day: str, equity: float) -> None:
    """Record a session's settled close. First write wins: a close is a fact,
    and facts do not get quietly revised by whoever asks last."""
    closes = read_daily_closes()
    if day in closes:
        return
    closes[day] = round(float(equity), 2)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(closes, indent=1, sort_keys=True))
        log.info("Recorded settled close for %s: %.2f", day, equity)
    except OSError as exc:
        log.warning("Could not record daily close: %s", exc)
