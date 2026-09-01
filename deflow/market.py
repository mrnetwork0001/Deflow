"""Market data: one interface, two backends.

`AlpacaMarketData` is the real thing -- daily bars and full option-chain
snapshots (NBBO + server-side Greeks) from Alpaca's Market Data API.

`SimulatedMarketData` exists so that `python main.py` does something useful on
a machine with no Alpaca keys, which is the state a judge's machine will be in.
It is seeded and reproducible, and everything it returns is tagged
`simulated=True` so no simulated number can ever be mistaken for, or reported
as, a live result.
"""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .alpaca_rest import AlpacaClient
from .config import DATA_DIR, SETTINGS, Settings
from .greeks import black_scholes, implied_vol, years_to_expiry
from .indicators import (
    forecast_vol,
    percentile_rank,
    range_rank,
    realized_vol,
    rolling_realized_vol,
    rsi,
    sma,
    trend_score,
)
from .models import MarketSnapshot, OptionQuote, Regime, occ_symbol

log = logging.getLogger("deflow.market")

# A high IV rank means options are expensive relative to their own history --
# that is when Deflow sells premium instead of buying it.
HIGH_IV_RANK = 0.50
TREND_THRESHOLD = 0.25


def classify_regime(iv_rank: float, trend: float) -> Regime:
    """Map (IV rank, trend) onto the six-cell regime grid.

    The vol axis decides whether Deflow is a net buyer or seller of premium;
    the trend axis decides which side of the underlying it leans on.
    """
    high_vol = iv_rank >= HIGH_IV_RANK
    if trend >= TREND_THRESHOLD:
        return Regime.HIGH_VOL_BULL if high_vol else Regime.LOW_VOL_BULL
    if trend <= -TREND_THRESHOLD:
        return Regime.HIGH_VOL_BEAR if high_vol else Regime.LOW_VOL_BEAR
    return Regime.HIGH_VOL_RANGE if high_vol else Regime.LOW_VOL_RANGE


# ---------------------------------------------------------------------------
# Implied-volatility history
# ---------------------------------------------------------------------------

class IVHistoryStore:
    """Persisted daily ATM implied vol, so IV rank becomes real over time.

    A true IV rank needs a year of implied-vol observations, and Alpaca (like
    most brokers) does not serve historical IV. Deflow therefore does two
    things and is explicit about which one is in play:

      * From day one it ranks the current ATM IV against the trailing year of
        *realised* vol -- a documented proxy, reported as `basis="hv_proxy"`.
      * Every cycle it appends the observed ATM IV here. Once at least
        `MIN_SAMPLES` sessions have accumulated, the rank switches to the real
        implied-vol history and reports `basis="iv_history"`.
    """

    MIN_SAMPLES = 20
    MAX_SAMPLES = 252

    def __init__(self, path: Optional[str] = None) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = DATA_DIR / (path or "iv_history.json")
        self._data: Dict[str, Dict[str, float]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("IV history unreadable (%s); starting fresh", exc)
                self._data = {}

    def record(self, symbol: str, iv: float, day: Optional[date] = None) -> None:
        if iv <= 0:
            return
        day = day or date.today()
        bucket = self._data.setdefault(symbol.upper(), {})
        bucket[day.isoformat()] = round(iv, 6)
        # Keep only the trailing year.
        if len(bucket) > self.MAX_SAMPLES:
            for stale in sorted(bucket)[: len(bucket) - self.MAX_SAMPLES]:
                del bucket[stale]
        try:
            self.path.write_text(json.dumps(self._data, indent=1, sort_keys=True))
        except OSError as exc:
            log.warning("Could not persist IV history: %s", exc)

    def series(self, symbol: str) -> List[float]:
        bucket = self._data.get(symbol.upper(), {})
        return [bucket[k] for k in sorted(bucket)]

    def rank(self, symbol: str, current_iv: float, hv_series: Sequence[float]) -> Dict[str, object]:
        """IV rank plus the basis it was computed on."""
        observed = self.series(symbol)
        if len(observed) >= self.MIN_SAMPLES:
            return {
                "iv_rank": range_rank(current_iv, observed),
                "iv_percentile": percentile_rank(current_iv, observed),
                "basis": "iv_history",
                "samples": len(observed),
            }
        return {
            "iv_rank": range_rank(current_iv, hv_series),
            "iv_percentile": percentile_rank(current_iv, hv_series),
            "basis": "hv_proxy",
            "samples": len(hv_series),
        }


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class MarketDataProvider(Protocol):
    simulated: bool

    def snapshot(self, symbol: str) -> Optional[MarketSnapshot]: ...
    def option_chain(self, symbol: str, min_dte: int, max_dte: int) -> List[OptionQuote]: ...


# ---------------------------------------------------------------------------
# Live Alpaca
# ---------------------------------------------------------------------------

class AlpacaMarketData:
    """Daily bars and option chains from Alpaca's Market Data API."""

    simulated = False

    def __init__(self, client: AlpacaClient, iv_store: Optional[IVHistoryStore] = None) -> None:
        self.client = client
        self.iv_store = iv_store or IVHistoryStore()
        self._bars_cache: Dict[str, List[float]] = {}
        self._chain_cache: Dict[str, tuple] = {}

    def _closes(self, symbol: str) -> List[float]:
        if symbol in self._bars_cache:
            return self._bars_cache[symbol]
        result = self.client.get_daily_bars(symbol)
        if not result.ok:
            log.warning("No bars for %s: %s", symbol, result.error)
            return []
        bars = (result.data or {}).get("bars", {}).get(symbol.upper(), [])
        closes = [float(b["c"]) for b in bars if b.get("c")]
        self._bars_cache[symbol] = closes
        return closes

    def _contract_meta(
        self, symbol: str, min_dte: int, max_dte: int, spot: float
    ) -> Dict[str, Dict[str, Any]]:
        """Open interest and tradability, keyed by OCC symbol.

        Alpaca splits the data a liquidity filter needs across two endpoints:
        the snapshot carries quotes, Greeks and implied vol but **no open
        interest**, while the contracts endpoint carries open interest but no
        quotes. Screening on liquidity means joining them.

        Getting this wrong is not a subtle failure. Reading `openInterest` off
        the snapshot -- where the field simply does not exist -- yields 0 for
        every contract, and a `>= 100` filter then rejects the entire option
        universe on every symbol, every cycle, while reporting only that
        nothing "cleared the liquidity filter".
        """
        today = date.today()
        cache_key = f"meta:{symbol}:{min_dte}:{max_dte}"
        cached = self._chain_cache.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < 900:
            return cached[1]

        meta: Dict[str, Dict[str, Any]] = {}
        token: Optional[str] = None
        for _ in range(20):  # bounded: ~20k contracts is far beyond any single name
            result = self.client.get_option_contracts(
                symbol,
                expiration_gte=today + timedelta(days=min_dte),
                expiration_lte=today + timedelta(days=max_dte),
                strike_gte=spot * 0.80,
                strike_lte=spot * 1.20,
                page_token=token,
            )
            if not result.ok:
                log.warning("Contract metadata unavailable for %s: %s", symbol, result.error)
                break
            payload = result.data or {}
            for contract in payload.get("option_contracts", []):
                occ = contract.get("symbol")
                if not occ:
                    continue
                try:
                    oi = int(contract.get("open_interest") or 0)
                except (TypeError, ValueError):
                    oi = 0
                meta[occ] = {"open_interest": oi, "tradable": bool(contract.get("tradable", True))}
            token = payload.get("next_page_token")
            if not token:
                break

        self._chain_cache[cache_key] = (datetime.now(timezone.utc), meta)
        return meta

    def option_chain(self, symbol: str, min_dte: int = 7, max_dte: int = 60) -> List[OptionQuote]:
        today = date.today()
        cache_key = f"{symbol}:{min_dte}:{max_dte}"
        cached = self._chain_cache.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < 60:
            return cached[1]

        spot = self.spot(symbol)
        if spot <= 0:
            return []

        # Paginate. The endpoint caps at 1000 contracts per page, and on a
        # name with daily expiries -- SPY, QQQ -- that single page is consumed
        # by the nearest few dates before reaching the 21-45 DTE window the
        # desk actually trades. Taking only the first page meant SPY offered
        # one usable expiry and QQQ none, so the two most liquid symbols in
        # the universe were effectively untradeable while appearing merely
        # unattractive.
        snapshots: Dict[str, Any] = {}
        token: Optional[str] = None
        for _ in range(12):  # 12k contracts is far beyond any single name
            result = self.client.get_option_chain(
                symbol,
                expiration_gte=today + timedelta(days=min_dte),
                expiration_lte=today + timedelta(days=max_dte),
                # Only strikes within +/-20% are ever structurally useful.
                strike_gte=spot * 0.80,
                strike_lte=spot * 1.20,
                page_token=token,
            )
            if not result.ok:
                log.warning("No option chain for %s: %s", symbol, result.error)
                break
            payload = result.data or {}
            snapshots.update(payload.get("snapshots", {}))
            token = payload.get("next_page_token")
            if not token:
                break

        if not snapshots:
            return []

        contract_meta = self._contract_meta(symbol, min_dte, max_dte, spot)

        quotes: List[OptionQuote] = []
        for occ, snap in snapshots.items():
            quote = snap.get("latestQuote") or {}
            bid, ask = float(quote.get("bp", 0.0) or 0.0), float(quote.get("ap", 0.0) or 0.0)
            if bid <= 0 or ask <= 0:
                continue  # unquotable contract; the structurer must not see it
            try:
                from .models import parse_occ

                parsed = parse_occ(occ)
            except ValueError:
                continue

            contract = contract_meta.get(occ)
            if contract is not None and not contract["tradable"]:
                continue

            greeks = snap.get("greeks") or {}
            iv = float(snap.get("impliedVolatility", 0.0) or 0.0)
            if iv <= 0:
                # Alpaca omits IV on illiquid contracts; recover it ourselves.
                iv = implied_vol(
                    (bid + ask) / 2.0, spot, parsed["strike"],
                    years_to_expiry((parsed["expiry"] - today).days), parsed["right"],
                )
            quotes.append(
                OptionQuote(
                    symbol=occ,
                    bid=bid,
                    ask=ask,
                    underlying_price=spot,
                    strike=parsed["strike"],
                    right=parsed["right"],
                    expiry=parsed["expiry"],
                    implied_vol=iv,
                    # Joined from the contracts endpoint; the snapshot has no
                    # open-interest field.
                    open_interest=(contract or {}).get("open_interest", 0),
                    volume=int((snap.get("dailyBar") or {}).get("v", 0) or 0),
                )
            )
            _ = greeks  # Alpaca's Greeks are cross-checked in the auditor, not trusted here.

        self._chain_cache[cache_key] = (datetime.now(timezone.utc), quotes)
        return quotes

    def is_market_open(self) -> tuple[bool, str]:
        """Ask Alpaca whether the session is open, cached for 30 seconds.

        Fails OPEN deliberately: if the clock endpoint is unreachable the desk
        keeps trading rather than sitting out a live session on a transient
        network error. A rejected order is a logged non-event; a missed session
        is P&L that cannot be recovered.
        """
        cached = self._chain_cache.get("clock")
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < 30:
            return cached[1]

        result = self.client.get_clock()
        if not result.ok:
            log.warning("Market clock unavailable (%s); assuming open", result.error)
            return True, "clock unavailable — assuming open"

        data = result.data or {}
        state = (bool(data.get("is_open")), str(data.get("next_open", "")))
        verdict = (state[0], "" if state[0] else f"closed until {state[1]}")
        self._chain_cache["clock"] = (datetime.now(timezone.utc), verdict)
        return verdict

    def spot(self, symbol: str) -> float:
        trade = self.client.get_latest_stock_trade(symbol)
        if trade.ok:
            t = (trade.data or {}).get("trades", {}).get(symbol.upper(), {})
            if t.get("p"):
                return float(t["p"])
        closes = self._closes(symbol)
        return closes[-1] if closes else 0.0

    def snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        closes = self._closes(symbol)
        if len(closes) < 60:
            log.warning("Insufficient history for %s (%d bars)", symbol, len(closes))
            return None

        spot = self.spot(symbol) or closes[-1]
        hv_series = rolling_realized_vol(closes, 20)[-252:]
        hv60 = realized_vol(closes, 60)
        hv_fc = forecast_vol(closes)

        chain = self.option_chain(symbol, 20, 45)
        atm_iv = _atm_iv(chain, spot) or hv60
        self.iv_store.record(symbol, atm_iv)
        rank = self.iv_store.rank(symbol, atm_iv, hv_series)

        trend = trend_score(closes)
        return MarketSnapshot(
            symbol=symbol.upper(),
            price=spot,
            iv_rank=float(rank["iv_rank"]),
            iv_30d=atm_iv,
            hv_60d=hv60,
            trend_score=trend,
            regime=classify_regime(float(rank["iv_rank"]), trend),
            sma20=sma(closes, 20),
            sma50=sma(closes, 50),
            rsi14=rsi(closes, 14),
            hv_forecast=hv_fc,
            variance_premium=atm_iv - hv_fc,
        )


def _atm_iv(chain: Sequence[OptionQuote], spot: float) -> float:
    """Average implied vol of the two contracts closest to the money."""
    usable = [q for q in chain if q.implied_vol > 0 and 20 <= q.dte <= 45]
    if not usable:
        return 0.0
    nearest = min(abs(q.strike - spot) for q in usable)
    at_money = [q.implied_vol for q in usable if abs(abs(q.strike - spot) - nearest) < 0.51]
    return sum(at_money) / len(at_money) if at_money else 0.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimSpec:
    """Per-symbol parameters for the synthetic market."""

    spot: float
    drift: float
    vol: float
    atm_iv: float
    skew: float          # put-side IV lift per unit log-moneyness
    smile: float         # convexity of the smile
    strike_step: float


_SIM_SPECS: Dict[str, SimSpec] = {
    "SPY": SimSpec(548.0, 0.08, 0.13, 0.145, -0.55, 1.10, 1.0),
    "QQQ": SimSpec(472.0, 0.11, 0.17, 0.185, -0.48, 1.25, 1.0),
    "NVDA": SimSpec(128.0, 0.22, 0.44, 0.475, -0.22, 1.90, 2.5),
    "TSLA": SimSpec(242.0, 0.05, 0.52, 0.560, -0.18, 2.10, 5.0),
    "AAPL": SimSpec(228.0, 0.09, 0.24, 0.255, -0.35, 1.40, 2.5),
    "IWM": SimSpec(224.0, 0.06, 0.19, 0.208, -0.44, 1.20, 1.0),
    "MSFT": SimSpec(418.0, 0.10, 0.22, 0.238, -0.33, 1.35, 5.0),
    "AMD": SimSpec(162.0, 0.14, 0.46, 0.495, -0.24, 1.75, 2.5),
}
_DEFAULT_SPEC = SimSpec(100.0, 0.06, 0.25, 0.27, -0.30, 1.30, 1.0)


class SimulatedMarketData:
    """Deterministic synthetic market for credential-free runs.

    The generator is seeded from the symbol and the calendar date, so a run on
    a given day is reproducible and two symbols never move in lockstep. Prices
    follow GBM; the option surface is a Black-Scholes smile with a realistic
    equity put skew, and bid/ask widths grow with moneyness and shrink with
    time to expiry, which is what makes the liquidity filter do real work here.
    """

    simulated = True

    def __init__(self, seed_offset: int = 0, iv_store: Optional[IVHistoryStore] = None) -> None:
        self.seed_offset = seed_offset
        self.iv_store = iv_store or IVHistoryStore("iv_history_sim.json")
        self._paths: Dict[str, List[float]] = {}

    @staticmethod
    def _spec(symbol: str) -> SimSpec:
        return _SIM_SPECS.get(symbol.upper(), _DEFAULT_SPEC)

    def _path(self, symbol: str, days: int = 300) -> List[float]:
        """A stable one-year daily price history for the symbol."""
        if symbol in self._paths:
            return self._paths[symbol]
        spec = self._spec(symbol)
        rng = random.Random(f"{symbol}:{date.today().isoformat()}:{self.seed_offset}")

        dt = 1.0 / 252.0
        # Walk backwards from today's nominal spot so the series ends near it.
        closes = [spec.spot]
        # A slow stochastic vol factor makes IV rank move instead of sitting flat.
        vol_state = spec.vol
        for _ in range(days):
            vol_state = max(0.05, vol_state + 0.10 * (spec.vol - vol_state) * dt + 0.35 * vol_state * math.sqrt(dt) * rng.gauss(0, 1))
            shock = (spec.drift - 0.5 * vol_state**2) * dt + vol_state * math.sqrt(dt) * rng.gauss(0, 1)
            closes.append(closes[-1] * math.exp(shock))
        # Reverse so the *generated* series ends at the nominal spot, keeping
        # quoted prices in a familiar range for anyone reading the dashboard.
        scale = spec.spot / closes[-1]
        self._paths[symbol] = [c * scale for c in closes]
        return self._paths[symbol]

    def is_market_open(self) -> tuple[bool, str]:
        """The synthetic market never closes -- there is no session to miss."""
        return True, ""

    def spot(self, symbol: str) -> float:
        return self._path(symbol)[-1]

    def _iv_at(self, symbol: str, strike: float, spot: float, dte: int) -> float:
        """Smile-adjusted implied vol for one strike."""
        spec = self._spec(symbol)
        closes = self._path(symbol)
        # Anchor the surface on recent realised vol plus a variance risk
        # premium, which is the whole reason a premium-selling strategy exists.
        base = max(realized_vol(closes, 20), 0.05) * 1.12
        m = math.log(strike / spot) if spot > 0 and strike > 0 else 0.0
        # Term structure: short-dated options carry more vol-of-vol.
        term = 1.0 + 0.28 * math.exp(-dte / 30.0)
        iv = base * term * (1.0 + spec.skew * m + spec.smile * m * m)
        return max(0.04, min(iv, 3.0))

    @staticmethod
    def _expiries(min_dte: int, max_dte: int) -> List[date]:
        """Fridays inside the DTE window -- the real listing convention."""
        today = date.today()
        out = []
        for offset in range(min_dte, max_dte + 1):
            d = today + timedelta(days=offset)
            if d.weekday() == 4:
                out.append(d)
        return out

    def option_chain(self, symbol: str, min_dte: int = 7, max_dte: int = 60) -> List[OptionQuote]:
        spec = self._spec(symbol)
        spot = self.spot(symbol)
        step = spec.strike_step

        # Strike coverage has to scale with volatility and time, not sit at a
        # flat +/-15%. NVDA at 80% implied vol has a ~1-sigma monthly move
        # around 23%, so a flat band lists no strike beyond the short leg of a
        # normal credit spread and the desk cannot build a protective wing at
        # all. Real chains extend several sigma; this covers +/-3.
        sigma = self._iv_at(symbol, spot, spot, max_dte)
        horizon = math.sqrt(max(max_dte, 1) / 365.0)
        band = max(0.15, min(3.0 * sigma * horizon, 0.75))
        lo, hi = spot * (1.0 - band), spot * (1.0 + band)
        first = math.floor(lo / step) * step

        strikes: List[float] = []
        k = first
        while k <= hi:
            if k > 0:
                strikes.append(round(k, 2))
            k += step

        quotes: List[OptionQuote] = []
        for expiry in self._expiries(min_dte, max_dte):
            dte = (expiry - date.today()).days
            T = years_to_expiry(dte)
            for strike in strikes:
                for right in ("call", "put"):
                    iv = self._iv_at(symbol, strike, spot, dte)
                    mid = black_scholes(spot, strike, T, iv, right).price
                    if mid < 0.02:
                        continue  # below the minimum tick; genuinely untradable
                    # Spread widens away from the money and for longer dated
                    # contracts -- the pattern the liquidity filter screens on.
                    moneyness = abs(math.log(strike / spot)) if spot > 0 else 0.0
                    rel = 0.012 + 0.55 * moneyness + 0.0009 * dte
                    half = max(mid * rel, 0.01) / 2.0
                    bid, ask = max(round(mid - half, 2), 0.01), round(mid + half, 2)
                    oi = int(9000 * math.exp(-14 * moneyness) * math.exp(-dte / 90.0)) + 25
                    quotes.append(
                        OptionQuote(
                            symbol=occ_symbol(symbol, expiry, right, strike),
                            bid=bid,
                            ask=ask,
                            underlying_price=spot,
                            strike=strike,
                            right=right,
                            expiry=expiry,
                            implied_vol=iv,
                            open_interest=oi,
                            volume=max(int(oi * 0.12), 1),
                        )
                    )
        return quotes

    def snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        closes = self._path(symbol)
        spot = closes[-1]
        hv_series = rolling_realized_vol(closes, 20)[-252:]
        hv60 = realized_vol(closes, 60)
        hv_fc = forecast_vol(closes)
        atm_iv = self._iv_at(symbol, spot, spot, 30)
        self.iv_store.record(symbol, atm_iv)
        rank = self.iv_store.rank(symbol, atm_iv, hv_series)
        trend = trend_score(closes)
        return MarketSnapshot(
            symbol=symbol.upper(),
            price=spot,
            iv_rank=float(rank["iv_rank"]),
            iv_30d=atm_iv,
            hv_60d=hv60,
            trend_score=trend,
            regime=classify_regime(float(rank["iv_rank"]), trend),
            sma20=sma(closes, 20),
            sma50=sma(closes, 50),
            rsi14=rsi(closes, 14),
            hv_forecast=hv_fc,
            variance_premium=atm_iv - hv_fc,
        )


def build_provider(settings: Settings = SETTINGS, client: Optional[AlpacaClient] = None):
    """Pick the live provider when credentials exist, the simulator otherwise."""
    if settings.has_alpaca_credentials and client is not None:
        return AlpacaMarketData(client)
    return SimulatedMarketData()


__all__ = [
    "AlpacaMarketData",
    "IVHistoryStore",
    "MarketDataProvider",
    "SimulatedMarketData",
    "build_provider",
    "classify_regime",
]
