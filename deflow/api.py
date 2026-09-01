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
    # The dashboard is served from a different port in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
        return desk.portfolio.performance()

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
