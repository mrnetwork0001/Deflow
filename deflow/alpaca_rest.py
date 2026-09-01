"""Thin, typed client for Alpaca's Trading and Market Data REST APIs.

Written directly against the HTTP surface rather than through a wrapper so the
multi-leg (`order_class="mleg"`) payload -- the one part of the Alpaca API this
project actually lives or dies on -- is visible and adjustable in one place.

Every method is defensive: a network failure returns an explicit error object
rather than raising into the trading loop, because a desk that crashes on a
transient 502 is worse than a desk that skips a cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence

import httpx

from .config import SETTINGS, Settings

log = logging.getLogger("deflow.alpaca")


class AlpacaError(RuntimeError):
    """Raised only by callers that opt into strict mode."""


@dataclass
class ApiResult:
    """Uniform success/failure envelope so the desk never sees an exception."""

    ok: bool
    data: Any = None
    error: str = ""
    status_code: int = 0

    def __bool__(self) -> bool:
        return self.ok


class AlpacaClient:
    """Alpaca paper-trading REST client.

    Refuses to initialise against a non-paper endpoint: this project is a
    hackathon submission and must never be one environment variable away from
    routing a live order.
    """

    def __init__(self, settings: Settings = SETTINGS, timeout: float = 20.0) -> None:
        self.settings = settings
        if settings.has_alpaca_credentials and not settings.is_paper_endpoint:
            raise AlpacaError(
                f"Refusing to start: {settings.trading_base_url} is not an Alpaca paper endpoint. "
                "Deflow is paper-only by construction."
            )
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret,
            "accept": "application/json",
        }
        self._client = httpx.Client(timeout=timeout, headers=self._headers)

    # -- plumbing -----------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> ApiResult:
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            log.warning("Alpaca %s %s failed: %s", method, url, exc)
            return ApiResult(False, error=f"transport: {exc}")

        if resp.status_code >= 400:
            # Alpaca returns a JSON body with `message` on most 4xx/5xx.
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            log.warning("Alpaca %s %s -> %s: %s", method, url, resp.status_code, detail)
            return ApiResult(False, error=str(detail)[:500], status_code=resp.status_code)

        try:
            return ApiResult(True, data=resp.json(), status_code=resp.status_code)
        except Exception:
            return ApiResult(True, data=resp.text, status_code=resp.status_code)

    def _trading(self, method: str, path: str, **kwargs: Any) -> ApiResult:
        return self._request(method, f"{self.settings.trading_base_url}{path}", **kwargs)

    def _data(self, method: str, path: str, **kwargs: Any) -> ApiResult:
        return self._request(method, f"{self.settings.data_base_url}{path}", **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AlpacaClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- account ------------------------------------------------------------

    def get_account(self) -> ApiResult:
        """Account snapshot: equity, buying power, and the account number
        that has to appear in the hackathon submission."""
        return self._trading("GET", "/v2/account")

    def get_clock(self) -> ApiResult:
        return self._trading("GET", "/v2/clock")

    def get_positions(self) -> ApiResult:
        return self._trading("GET", "/v2/positions")

    def get_orders(self, status: str = "all", limit: int = 100, nested: bool = True) -> ApiResult:
        return self._trading(
            "GET",
            "/v2/orders",
            params={"status": status, "limit": limit, "nested": str(nested).lower()},
        )

    def get_portfolio_history(self, period: str = "1W", timeframe: str = "1H") -> ApiResult:
        """Equity curve for the dashboard and the P&L write-up."""
        return self._trading(
            "GET",
            "/v2/account/portfolio/history",
            params={"period": period, "timeframe": timeframe, "intraday_reporting": "market_hours"},
        )

    # -- equity market data -------------------------------------------------

    def get_daily_bars(self, symbol: str, lookback_days: int = 260) -> ApiResult:
        """Daily bars, used for realised volatility and the trend filter.

        `feed=iex` is the free tier; SIP requires a paid data subscription that
        a hackathon paper account will not have.
        """
        start = (datetime.now(timezone.utc) - timedelta(days=int(lookback_days * 1.6))).date()
        return self._data(
            "GET",
            "/v2/stocks/bars",
            params={
                "symbols": symbol,
                "timeframe": "1Day",
                "start": start.isoformat(),
                "limit": 10_000,
                "adjustment": "split",
                "feed": "iex",
            },
        )

    def get_latest_stock_quote(self, symbol: str) -> ApiResult:
        return self._data("GET", "/v2/stocks/quotes/latest", params={"symbols": symbol, "feed": "iex"})

    def get_latest_stock_trade(self, symbol: str) -> ApiResult:
        return self._data("GET", "/v2/stocks/trades/latest", params={"symbols": symbol, "feed": "iex"})

    # -- options ------------------------------------------------------------

    def get_option_contracts(
        self,
        underlying: str,
        expiration_gte: Optional[date] = None,
        expiration_lte: Optional[date] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
        limit: int = 1000,
    ) -> ApiResult:
        """Tradable contract universe for an underlying (Trading API)."""
        params: Dict[str, Any] = {
            "underlying_symbols": underlying.upper(),
            "status": "active",
            "limit": limit,
        }
        if expiration_gte:
            params["expiration_date_gte"] = expiration_gte.isoformat()
        if expiration_lte:
            params["expiration_date_lte"] = expiration_lte.isoformat()
        if strike_gte is not None:
            params["strike_price_gte"] = f"{strike_gte:.2f}"
        if strike_lte is not None:
            params["strike_price_lte"] = f"{strike_lte:.2f}"
        return self._trading("GET", "/v2/options/contracts", params=params)

    def get_option_chain(
        self,
        underlying: str,
        expiration_gte: Optional[date] = None,
        expiration_lte: Optional[date] = None,
        strike_gte: Optional[float] = None,
        strike_lte: Optional[float] = None,
    ) -> ApiResult:
        """Full chain snapshot with NBBO quotes, Greeks and implied vol.

        This is the single richest endpoint in the stack: Alpaca computes the
        Greeks server-side, and Deflow re-derives them locally so the auditor
        can cross-check rather than trust.
        """
        params: Dict[str, Any] = {"feed": "indicative", "limit": 1000}
        if expiration_gte:
            params["expiration_date_gte"] = expiration_gte.isoformat()
        if expiration_lte:
            params["expiration_date_lte"] = expiration_lte.isoformat()
        if strike_gte is not None:
            params["strike_price_gte"] = f"{strike_gte:.2f}"
        if strike_lte is not None:
            params["strike_price_lte"] = f"{strike_lte:.2f}"
        return self._data("GET", f"/v1beta1/options/snapshots/{underlying.upper()}", params=params)

    # -- order routing ------------------------------------------------------

    @staticmethod
    def build_mleg_payload(
        legs: Sequence[Dict[str, Any]],
        quantity: int,
        limit_price: float,
        time_in_force: str = "day",
        closing: bool = False,
    ) -> Dict[str, Any]:
        """Assemble an Alpaca `order_class="mleg"` body.

        Two details that are easy to get wrong and expensive to get wrong:

        * `limit_price` is the **net** price of the package. Alpaca's
          convention is positive for a net debit and negative for a net credit,
          so a credit spread submits a negative limit.
        * `ratio_qty` is always positive; direction lives in `side`, and
          `position_intent` distinguishes opening from closing so the broker
          nets the position instead of stacking a second one.
        """
        payload_legs = []
        for leg in legs:
            side = leg["side"]
            if closing:
                intent = "sell_to_close" if side == "sell" else "buy_to_close"
            else:
                intent = "buy_to_open" if side == "buy" else "sell_to_open"
            payload_legs.append(
                {
                    "symbol": leg["symbol"],
                    "ratio_qty": str(abs(int(leg.get("ratio", 1)))),
                    "side": side,
                    "position_intent": intent,
                }
            )
        return {
            "order_class": "mleg",
            "qty": str(int(quantity)),
            "type": "limit",
            "time_in_force": time_in_force,
            "limit_price": f"{limit_price:.2f}",
            "legs": payload_legs,
        }

    def submit_mleg_order(self, payload: Dict[str, Any]) -> ApiResult:
        return self._trading("POST", "/v2/orders", json=payload)

    def cancel_order(self, order_id: str) -> ApiResult:
        return self._trading("DELETE", f"/v2/orders/{order_id}")

    def close_position(self, symbol: str, qty: Optional[int] = None) -> ApiResult:
        params = {"qty": str(qty)} if qty else {}
        return self._trading("DELETE", f"/v2/positions/{symbol}", params=params)


__all__ = ["AlpacaClient", "AlpacaError", "ApiResult"]
