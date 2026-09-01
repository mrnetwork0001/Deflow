"""FastAPI backend: read-only observability plus manual cycle control.

Deliberately asymmetric. Everything a dashboard needs to *watch* the desk is
exposed; the only endpoints that cause anything to happen are `POST /api/cycle`
(run one pass now) and `POST /api/risk/evaluate` (submit a hypothetical trade to
the risk gate and see the twelve breakers rule on it). There is no endpoint that
places an order directly -- orders exist only as the output of a full pipeline
that has cleared the gate.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse


from .config import ROOT, SETTINGS
from .desk import TradingDesk

log = logging.getLogger("deflow.api")

# Bounded so a dashboard that stops reading cannot grow the queue without limit.
EVENT_BUFFER = 512

# The dashboard polls performance every 5s. Asking Alpaca every time would turn
# one open browser tab into 12 broker calls a minute, so the snapshot is cached
# for slightly longer than a poll interval.
BROKER_TTL_SECONDS = 6.0
# Past this, a cached reading stops standing in for a live one and the caller
# falls back to mid-marks with the label to match.
BROKER_MAX_STALE_SECONDS = 900.0
_broker_lock = threading.Lock()
_broker_cache: Dict[str, Any] = {"at": 0.0, "snapshot": None}


def _broker_truth(desk: TradingDesk) -> Optional[Dict[str, Any]]:
    """Equity and unrealised P&L exactly as the broker reports them.

    Deflow marks every leg at the quote mid. Alpaca marks at liquidation value
    -- long legs toward the bid, short legs toward the ask -- and a spread has
    one of each, so the mid flatters both ends and our book reads high every
    time, never low. On 2026-09-01 that was $581.55 against the broker's
    $405.60 on the same four positions: a 43% overstatement of the P&L.

    Mid is the right number for the exit logic, which is asking what the
    structure is worth. It is the wrong number for the dashboard, which is
    answering "how much money is there" -- and that answer has to be the one a
    judge gets when they open Alpaca, or the whole ledger-verification argument
    is worth nothing.

    Returns None when there is no broker to ask; the caller must then say so
    rather than passing mid-marks off as the broker's figures.
    """
    rest = desk.executor.rest
    if rest is None or not SETTINGS.has_alpaca_credentials:
        return None
    # In dry-run the fills are local simulations, so the broker's equity belongs
    # to a different book than the positions on screen. Pairing them would put a
    # real balance beside imaginary trades -- worse than showing mid-marks and
    # saying so.
    if SETTINGS.dry_run:
        return None

    now = time.monotonic()
    with _broker_lock:
        cached = _broker_cache["snapshot"]
        if cached is not None and now - _broker_cache["at"] < BROKER_TTL_SECONDS:
            return cached

    def _last_good() -> Optional[Dict[str, Any]]:
        """Serve the previous broker reading rather than silently changing basis.

        Returning None on a transient error looked safe and was not: the caller
        falls back to mid-marks, so one failed call swapped the headline from
        the broker's $99,898.50 to our own $100,076.50 and back again on the
        next poll. A dashboard whose headline jumps $178 every few seconds is
        worse than one showing a reading a minute old, and the label already
        tells the reader which it is. Only genuinely old readings are dropped.
        """
        with _broker_lock:
            stale = _broker_cache["snapshot"]
            age = now - _broker_cache["at"]
        if stale is None or age > BROKER_MAX_STALE_SECONDS:
            return None
        out = dict(stale)
        out["stale_seconds"] = round(age, 1)
        return out

    account = rest.get_account()
    if not account.ok or not isinstance(account.data, dict):
        log.warning("Broker equity unavailable: %s", account.error)
        return _last_good()
    try:
        equity = float(account.data["equity"])
    except (KeyError, TypeError, ValueError):
        log.warning("Broker account payload had no usable equity field")
        return _last_good()

    # Unrealised comes from the positions, not from equity arithmetic: equity
    # minus starting capital is total P&L, and splitting that into realised and
    # unrealised needs the leg-level marks.
    unrealized: Optional[float] = None
    positions = rest.get_positions()
    if positions.ok and isinstance(positions.data, list):
        try:
            unrealized = sum(float(p["unrealized_pl"]) for p in positions.data)
        except (KeyError, TypeError, ValueError):
            unrealized = None

    snapshot = {
        "equity": round(equity, 2),
        "unrealized_pnl": round(unrealized, 2) if unrealized is not None else None,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _broker_lock:
        _broker_cache["snapshot"] = snapshot
        _broker_cache["at"] = now
    return snapshot


class EventHub:
    """Fan-out of desk events to any number of connected SSE clients."""

    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._recent: List[Dict[str, Any]] = []

    def publish(self, message: Dict[str, Any]) -> None:
        with self._lock:
            self._recent.append(message)
            if len(self._recent) > 200:
                del self._recent[:-200]
            clients = list(self._clients)
        for client in clients:
            # A stalled client is dropped rather than allowed to block the
            # trading loop.
            with contextlib.suppress(queue.Full):
                client.put_nowait(message)

    def subscribe(self) -> queue.Queue:
        client: queue.Queue = queue.Queue(maxsize=EVENT_BUFFER)
        with self._lock:
            self._clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def recent(self, n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return self._recent[-n:]


class Scheduler:
    """Background thread that runs a desk cycle on a fixed interval."""

    def __init__(self, desk: TradingDesk, interval: int) -> None:
        self.desk = desk
        self.interval = max(interval, 30)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.desk.run_cycle()
            except Exception:
                log.exception("Scheduled cycle failed")
            # wait() rather than sleep() so a shutdown is immediate.
            self._stop.wait(self.interval)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="deflow-scheduler", daemon=True)
        self._thread.start()
        self.running = True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.running = False


def create_app(desk: TradingDesk, autostart: bool = True) -> FastAPI:
    hub = EventHub()
    desk.subscribe(hub.publish)
    scheduler = Scheduler(desk, SETTINGS.cycle_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if autostart:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(
        title="Deflow",
        description="Autonomous multi-agent options desk on Alpaca paper trading.",
        version="1.0.0",
        lifespan=lifespan,
    )
    # The dashboard may be served from another origin entirely -- Vercel in
    # production, localhost:3000 in development -- so the browser's origin is
    # not the API's. Origins are listed explicitly rather than wildcarded:
    # POST /api/cycle and /api/risk/evaluate cause work, and a wildcard would
    # let any page on the internet drive them.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SETTINGS.cors_origins,
        # Vercel preview deployments get a fresh subdomain per push, so the
        # regex admits the project's previews without opening the whole web.
        allow_origin_regex=r"https://[a-z0-9-]+-.*\.vercel\.app",
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # -- meta ---------------------------------------------------------------

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "mode": SETTINGS.mode,
            "paper_endpoint": SETTINGS.is_paper_endpoint,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @app.get("/api/status")
    def status() -> Dict[str, Any]:
        payload = desk.status()
        payload["scheduler"] = {"running": scheduler.running, "interval_seconds": scheduler.interval}
        return payload

    # -- book ---------------------------------------------------------------

    @app.get("/api/performance")
    def performance() -> Dict[str, Any]:
        """Book statistics, with the headline money taken from the broker.

        `mark_source` says which basis the equity figure is on. It is not
        decoration: a dashboard that silently swaps between the broker's number
        and our own mid-marks is lying by omission on whichever day the broker
        call fails.
        """
        perf = desk.portfolio.performance()
        truth = _broker_truth(desk)
        if truth is None:
            perf["mark_source"] = "deflow-mid"
            perf["broker"] = None
            return perf

        # Keep our own figure alongside, labelled. The gap between mid-marks and
        # liquidation marks is a real property of the book -- roughly the cost of
        # crossing eight bid/ask spreads -- and hiding it would throw away the
        # one number that says what an exit would actually collect.
        perf["desk_mark"] = {
            "equity": perf["equity"],
            "unrealized_pnl": perf["unrealized_pnl"],
            "total_pnl": perf["total_pnl"],
            "basis": "quote mid",
        }

        equity = truth["equity"]
        start = perf["starting_equity"]
        perf["equity"] = equity
        perf["total_pnl"] = round(equity - start, 2)
        perf["return_pct"] = round((equity / start - 1.0) * 100.0, 4) if start else 0.0
        if truth["unrealized_pnl"] is not None:
            perf["unrealized_pnl"] = truth["unrealized_pnl"]
            # Realised is then a residual, which is what keeps the three numbers
            # adding up on screen instead of drifting apart by the mark gap.
            perf["realized_pnl"] = round(perf["total_pnl"] - truth["unrealized_pnl"], 2)
        # Risk headroom is a fraction of real equity, so it moves with it.
        perf["capital_at_risk_pct"] = (
            round(perf["capital_at_risk"] / equity * 100, 3) if equity else 0.0
        )
        perf["mark_source"] = "alpaca"
        perf["broker"] = {
            "equity": equity,
            "as_of": truth["at"],
            # Non-zero means this reading is being reused because the live call
            # failed. The dashboard says so rather than presenting it as fresh.
            "stale_seconds": truth.get("stale_seconds", 0.0),
        }
        return perf

    @app.get("/api/positions")
    def positions() -> Dict[str, Any]:
        return {
            "open": [p.to_dict() for p in desk.portfolio.open.values()],
            "closed": [c.to_dict() for c in desk.portfolio.closed],
        }

    @app.get("/api/account")
    def account() -> Dict[str, Any]:
        """Live Alpaca account when credentials exist, local book otherwise."""
        rest = desk.executor.rest
        if rest is not None and SETTINGS.has_alpaca_credentials:
            result = rest.get_account()
            if result.ok:
                return {"source": "alpaca", "simulated": False, "account": result.data}
            return {"source": "alpaca", "simulated": False, "error": result.error}
        return {
            "source": "deflow-simulation",
            "simulated": True,
            "note": "No Alpaca credentials configured; figures are from the local simulated book.",
            "account": desk.portfolio.performance(),
        }

    @app.get("/api/equity-curve")
    def equity_curve(period: str = "1W", timeframe: str = "1H") -> Dict[str, Any]:
        """Equity over time.

        Prefers Alpaca's own portfolio history -- it is the broker's record,
        which is the one a judge can independently check -- and falls back to
        reconstructing a curve from the ledger's own cycle_end entries when
        there are no credentials or the endpoint is unavailable.
        """
        rest = desk.executor.rest
        if rest is not None and SETTINGS.has_alpaca_credentials:
            result = rest.get_portfolio_history(period=period, timeframe=timeframe)
            if result.ok and isinstance(result.data, dict):
                data = result.data
                stamps = data.get("timestamp") or []
                equity = data.get("equity") or []
                # Alpaca reports equity 0.0 for every bucket before the account
                # existed. A fresh hackathon account is hours old, so most of a
                # 1W window is zeros -- charted naively that is a $100,000
                # cliff at the origin and a P&L line pinned at -100%.
                if len(stamps) != len(equity):
                    # zip() would silently truncate to the shorter list and the
                    # curve would simply be missing its tail with no indication.
                    log.warning(
                        "Portfolio history arrays disagree (%d timestamps, %d equity values); "
                        "charting the overlap only",
                        len(stamps), len(equity),
                    )
                points = [
                    {"t": int(t), "equity": float(e)}
                    for t, e in zip(stamps, equity, strict=False)
                    if e is not None and float(e) > 0.0
                ]

                # Sanity-check the series against the account it claims to
                # describe. On 2026-09-01 this account returned base_value
                # 100000.0 with an equity array of [0]*29 + [190.0, 444.0] --
                # gains, not equity. Nothing here caught it, because 190 and 444
                # clear the > 0 filter, so the first point became the baseline
                # and the panel rendered "EQUITY $444.00, +133.68%". A return
                # figure like that on a submission reads as fabricated, and a
                # judge who checks finds a bug rather than a desk.
                #
                # Any real equity series sits near base_value. One that does not
                # is not equity, whatever the field is called, so it is refused
                # and the ledger reconstruction below is used instead.
                reference = float(data.get("base_value") or 0.0) or desk.portfolio.starting_equity
                if points and reference > 0:
                    lowest = min(pt["equity"] for pt in points)
                    if lowest < reference * 0.5:
                        log.warning(
                            "Alpaca portfolio history is not on an equity basis "
                            "(base_value %.2f, lowest point %.2f); falling back to the ledger.",
                            reference, lowest,
                        )
                        points = []

                if points:
                    base = points[0]["equity"] or desk.portfolio.starting_equity
                    for pt in points:
                        pt["pnl"] = round(pt["equity"] - base, 2)
                    return {
                        "source": "alpaca",
                        "base_value": base,
                        "points": points,
                        "note": (
                            f"{len(stamps) - len(points)} pre-funding buckets dropped"
                            if len(stamps) != len(points) else ""
                        ),
                    }

        # Ledger fallback: every cycle_end carries the performance snapshot.
        points = []
        for record in desk.ledger.read():
            if record.get("event") != "cycle_end":
                continue
            perf = (record.get("payload") or {}).get("performance") or {}
            if "equity" not in perf:
                continue
            points.append(
                {
                    "t": record.get("at"),
                    "equity": float(perf["equity"]),
                    "pnl": round(float(perf["equity"]) - desk.portfolio.starting_equity, 2),
                }
            )
        return {
            "source": "ledger",
            "base_value": desk.portfolio.starting_equity,
            "points": points[-500:],
        }

    @app.get("/api/refusals")
    def refusals(limit: int = Query(40, ge=1, le=200)) -> Dict[str, Any]:
        """Every trade the desk declined, and why.

        Roughly half of all symbol-cycles end in a refusal, and they are the
        most informative thing this system produces -- but they are invisible
        unless you read the raw event stream. Each refusal is attributed to the
        stage that made it, so 'the analyst saw no edge' is distinguishable
        from 'the risk gate vetoed a structure the model wanted'.
        """
        stages = {
            "analyst_view": ("analyst", lambda p: not p.get("tradeable", True)),
            "reasoning_choice": ("reasoning", lambda p: p.get("index") == -1),
            "audit": ("auditor", lambda p: not p.get("passed", True)),
            "risk_gate": ("risk_gate", lambda p: not p.get("approved", True)),
        }

        out: List[Dict[str, Any]] = []
        for record in desk.ledger.read():
            event = record.get("event")
            if event not in stages:
                continue
            stage, is_refusal = stages[event]
            payload = record.get("payload") or {}
            if not is_refusal(payload):
                continue

            if stage == "analyst":
                reason = (payload.get("reasons") or ["no edge measured"])[0]
            elif stage == "reasoning":
                reason = payload.get("rationale") or "model abstained"
            elif stage == "auditor":
                objections = payload.get("objections") or []
                fatal = [o for o in objections if o.get("severity") == "fatal"]
                reason = (fatal or objections or [{}])[0].get("message", "audit failed")
            else:
                reason = payload.get("reason", "vetoed")

            out.append(
                {
                    "seq": record.get("seq"),
                    "at": record.get("at"),
                    "stage": stage,
                    "symbol": payload.get("symbol", ""),
                    "reason": reason,
                }
            )

        counts: Dict[str, int] = {}
        for item in out:
            counts[item["stage"]] = counts.get(item["stage"], 0) + 1
        return {"total": len(out), "by_stage": counts, "refusals": out[-limit:][::-1]}

    # -- market -------------------------------------------------------------

    @app.get("/api/analysis")
    def analysis() -> Dict[str, Any]:
        views = desk.analyst.scan(SETTINGS.universe)
        return {
            "simulated": getattr(desk.provider, "simulated", True),
            "views": [v.to_dict() for v in views],
        }

    @app.get("/api/chain/{symbol}")
    def chain(symbol: str, min_dte: int = Query(7, ge=0), max_dte: int = Query(60, ge=1)) -> Dict[str, Any]:
        quotes = desk.provider.option_chain(symbol.upper(), min_dte, max_dte)
        return {
            "symbol": symbol.upper(),
            "simulated": getattr(desk.provider, "simulated", True),
            "count": len(quotes),
            "contracts": [
                {
                    "symbol": q.symbol, "right": q.right, "strike": q.strike,
                    "expiry": q.expiry.isoformat(), "dte": q.dte,
                    "bid": q.bid, "ask": q.ask, "mid": round(q.mid, 3),
                    "iv": round(q.implied_vol, 4), "spread_pct": round(q.spread_pct, 4),
                    "open_interest": q.open_interest,
                }
                for q in quotes[:400]
            ],
        }

    # -- risk ---------------------------------------------------------------

    @app.get("/api/risk/envelope")
    def envelope() -> Dict[str, Any]:
        return desk.gate.envelope()

    @app.post("/api/risk/evaluate")
    def evaluate(proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Run an arbitrary trade proposal through the twelve breakers.

        Exposed so the gate can be probed directly -- send it a naked call and
        watch it refuse. It evaluates against the live book, but nothing is
        routed and no state changes.
        """
        verdict = desk.gate.evaluate_trade(proposal, desk.portfolio.state())
        return verdict.to_dict()

    # -- ledger -------------------------------------------------------------

    @app.get("/api/ledger")
    def ledger(
        limit: int = Query(60, ge=1, le=500), event: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"entries": desk.ledger.tail(limit, event), "total": len(desk.ledger)}

    @app.get("/api/ledger/verify")
    def verify_ledger() -> Dict[str, Any]:
        return desk.ledger.verify().to_dict()

    # -- control ------------------------------------------------------------

    @app.post("/api/cycle")
    def run_cycle() -> Dict[str, Any]:
        return desk.run_cycle().to_dict()

    @app.post("/api/scheduler/{action}")
    def scheduler_control(action: str) -> Dict[str, Any]:
        if action == "start":
            scheduler.start()
        elif action == "stop":
            scheduler.stop()
        else:
            raise HTTPException(400, "action must be 'start' or 'stop'")
        return {"running": scheduler.running, "interval_seconds": scheduler.interval}

    # -- live stream --------------------------------------------------------

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        client = hub.subscribe()

        async def events():
            try:
                for message in hub.recent(30):
                    yield f"data: {json.dumps(message, default=str)}\n\n"
                while True:
                    try:
                        message = client.get_nowait()
                        yield f"data: {json.dumps(message, default=str)}\n\n"
                    except queue.Empty:
                        # Comment frame doubles as a keep-alive through proxies.
                        yield ": keep-alive\n\n"
                        await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            finally:
                hub.unsubscribe(client)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- dashboard ----------------------------------------------------------

    dashboard = ROOT / "web" / "out"
    if dashboard.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dashboard), html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def index() -> str:
            return _FALLBACK_PAGE

    return app


_FALLBACK_PAGE = """<!doctype html>
<title>Deflow</title>
<style>
 body{background:#0a0e14;color:#d7dce5;font:15px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
      margin:0;display:grid;place-items:center;min-height:100vh}
 .c{max-width:640px;padding:40px}
 h1{color:#00e08a;font-size:26px;margin:0 0 4px}
 .s{color:#7d8799;margin-bottom:28px}
 a{color:#4da6ff;text-decoration:none}
 li{margin:5px 0}
 code{background:#151b26;padding:2px 7px;border-radius:4px;color:#ffcc66}
</style>
<div class=c>
<h1>Deflow</h1>
<div class=s>Autonomous multi-agent options desk &middot; Alpaca paper trading</div>
<p>The API is running. The dashboard has not been built yet:</p>
<p><code>cd web && npm install && npm run build</code></p>
<p>Endpoints:</p>
<ul>
 <li><a href="/api/status">/api/status</a> — desk, risk envelope, ledger state</li>
 <li><a href="/api/performance">/api/performance</a> — P&amp;L and trade statistics</li>
 <li><a href="/api/positions">/api/positions</a> — open and closed structures</li>
 <li><a href="/api/analysis">/api/analysis</a> — live analyst views</li>
 <li><a href="/api/ledger">/api/ledger</a> — hash-chained decision log</li>
 <li><a href="/api/ledger/verify">/api/ledger/verify</a> — chain integrity check</li>
 <li><a href="/api/risk/envelope">/api/risk/envelope</a> — the twelve breakers</li>
 <li><a href="/docs">/docs</a> — OpenAPI reference</li>
</ul>
</div>"""


__all__ = ["EventHub", "Scheduler", "create_app"]
