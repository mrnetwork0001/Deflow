"""The trading desk: orchestrates the four agents into one auditable cycle.

One cycle, in order:

    0. Mark the book and honour any exit the deterministic guard demands.
    1. Analyst      -- classify each name's volatility regime.
    2. Structurer   -- build priced, defined-risk candidates for tradeable names.
    3. Reasoning    -- an open-weight model picks one candidate, or abstains.
    4. Auditor      -- independently stress-test the pick and try to break it.
    5. Risk gate    -- twelve deterministic breakers, zero LLM influence.
    6. Executor     -- route to Alpaca, re-checking the gate on the way in.

Every step writes to the hash-chained ledger, including the steps that decide
*not* to trade. A desk that only logs its fills cannot be audited.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from risk_gate import DeterministicRiskGate

from .agents.analyst import MacroVolatilityAnalyst
from .agents.auditor import AdversarialRiskAuditor
from .agents.executor import ExecutionAgent
from .agents.structurer import (
    MAX_SPREAD_PCT,
    MIN_OPEN_INTEREST,
    OptionsStructurer,
)
from .config import SETTINGS, Settings
from .ledger import DecisionLedger
from .llm import ReasoningEngine
from .models import utcnow
from .portfolio import Portfolio

log = logging.getLogger("deflow.desk")

# How long a limit order may rest before the desk withdraws it. A limit
# priced off a twenty-minute-old quote is no longer the trade the gate
# approved, and it reserves risk budget while it waits.
STALE_ORDER_SECONDS = 900


@dataclass
class SymbolOutcome:
    """What happened to one symbol in one cycle."""

    symbol: str
    stage: str                    # where the pipeline stopped
    accepted: bool
    detail: str
    view: Optional[Dict[str, Any]] = None
    candidates: int = 0
    choice: Optional[Dict[str, Any]] = None
    proposal: Optional[Dict[str, Any]] = None
    audit: Optional[Dict[str, Any]] = None
    verdict: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class CycleReport:
    """The full record of one pass over the universe."""

    cycle_id: str
    started_at: str
    finished_at: str = ""
    mode: str = "simulation"
    outcomes: List[SymbolOutcome] = field(default_factory=list)
    exits: List[Dict[str, Any]] = field(default_factory=list)
    fills: List[Dict[str, Any]] = field(default_factory=list)
    performance: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def orders_submitted(self) -> int:
        return sum(1 for o in self.outcomes if o.accepted)

    @property
    def vetoed(self) -> int:
        return sum(1 for o in self.outcomes if o.stage in {"risk_gate", "audit"} and not o.accepted)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "mode": self.mode,
            "symbols_scanned": len(self.outcomes),
            "orders_submitted": self.orders_submitted,
            "vetoed": self.vetoed,
            "exits": self.exits,
            "fills": self.fills,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "performance": self.performance,
            "errors": self.errors,
        }


class TradingDesk:
    """Wires the agents, the gate, the book and the ledger together."""

    def __init__(
        self,
        provider: Any,
        gate: DeterministicRiskGate,
        portfolio: Portfolio,
        executor: ExecutionAgent,
        reasoning: Optional[ReasoningEngine] = None,
        ledger: Optional[DecisionLedger] = None,
        settings: Settings = SETTINGS,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.gate = gate
        self.portfolio = portfolio
        self.executor = executor
        self.ledger = ledger or DecisionLedger()
        self.reasoning = reasoning or ReasoningEngine()

        self.analyst = MacroVolatilityAnalyst(provider)
        self.structurer = OptionsStructurer(provider, gate)
        self.auditor = AdversarialRiskAuditor()

        self.cycles = 0
        self.last_report: Optional[CycleReport] = None
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    # -- event fan-out -------------------------------------------------------

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._subscribers.append(callback)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        """Write to the ledger and push to any live dashboard listeners."""
        record = self.ledger.append(event, payload)
        message = {"event": event, "payload": payload, "seq": record.get("seq"), "at": record.get("at")}
        for callback in list(self._subscribers):
            try:
                callback(message)
            except Exception:  # a broken dashboard must never stop trading
                log.debug("subscriber raised", exc_info=True)

    # -- the cycle -----------------------------------------------------------

    def run_cycle(self) -> CycleReport:
        self.cycles += 1
        report = CycleReport(
            cycle_id=f"cyc-{uuid.uuid4().hex[:10]}",
            started_at=utcnow(),
            mode=self.settings.mode,
        )
        self._emit("cycle_start", {"cycle_id": report.cycle_id, "mode": report.mode,
                                   "universe": self.settings.universe})

        # Do nothing while the session is closed. Outside market hours the
        # option chain still returns quotes -- yesterday's, wide and stale --
        # so the desk would happily construct spreads from prices nobody can
        # trade at and fire multi-leg orders that the broker rejects. Those
        # rejections are harmless to the balance and corrosive to the record:
        # they fill the account's order history with noise that anyone
        # reviewing its performance has to wade through.
        is_open, why = self._market_state()
        if not is_open:
            report.finished_at = utcnow()
            report.performance = self.portfolio.performance()
            self.last_report = report
            self._emit("market_closed", {"cycle_id": report.cycle_id, "detail": why})
            log.info("Market closed (%s); skipping cycle", why)
            return report

        # --- 0a. Turn working orders into positions, or discard them -------
        try:
            report.fills = self._reconcile_fills()
        except Exception as exc:
            log.exception("Fill reconciliation failed")
            report.errors.append(f"fill reconciliation: {exc}")

        # --- 0b. Manage what is already open -------------------------------
        try:
            report.exits = self._manage_open_positions()
        except Exception as exc:
            log.exception("Position management failed")
            report.errors.append(f"position management: {exc}")

        # --- 1-6. Look for new risk ----------------------------------------
        for symbol in self.settings.universe:
            try:
                report.outcomes.append(self._process_symbol(symbol))
            except Exception as exc:
                log.exception("Cycle failed on %s", symbol)
                report.errors.append(f"{symbol}: {exc}")
                report.outcomes.append(
                    SymbolOutcome(symbol=symbol, stage="error", accepted=False, detail=str(exc))
                )

        report.performance = self.portfolio.performance()
        report.finished_at = utcnow()
        self.last_report = report
        self._emit(
            "cycle_end",
            {
                "cycle_id": report.cycle_id,
                "orders_submitted": report.orders_submitted,
                "vetoed": report.vetoed,
                "performance": report.performance,
            },
        )
        return report

    def _market_state(self) -> tuple[bool, str]:
        """Session state, tolerating a provider that cannot report one."""
        checker = getattr(self.provider, "is_market_open", None)
        if checker is None:
            return True, ""
        try:
            return checker()
        except Exception as exc:
            log.warning("Market clock check failed (%s); assuming open", exc)
            return True, "clock check failed — assuming open"

    # -- per-symbol pipeline -------------------------------------------------

    def _process_symbol(self, symbol: str) -> SymbolOutcome:
        # --- Stage 1: Analyst ----------------------------------------------
        view = self.analyst.analyse(symbol)
        if view is None:
            return SymbolOutcome(symbol, "analyst", False, "No market data available for this symbol.")

        self._emit("analyst_view", {"symbol": symbol, **view.to_dict()})

        if not view.tradeable:
            return SymbolOutcome(
                symbol, "analyst", False,
                f"Stood down: {view.reasons[0]}",
                view=view.to_dict(),
            )

        # --- Stage 2: Structurer -------------------------------------------
        portfolio_state = self.portfolio.state()

        strategy = self.structurer.strategy_for(view)
        if strategy is None:
            return SymbolOutcome(
                symbol, "structurer", False,
                f"No defined-risk structure expresses a {view.stance} stance on a "
                f"{view.bias} tape — buying convexity needs a direction to pay for the theta.",
                view=view.to_dict(),
            )

        candidates = self.structurer.build(view, portfolio_state)
        if not candidates:
            return SymbolOutcome(
                symbol, "structurer", False,
                f"No {strategy.value} cleared the liquidity, sizing and geometry filters "
                f"(bid/ask <= {int(MAX_SPREAD_PCT * 100)}% of mid, OI >= {MIN_OPEN_INTEREST}).",
                view=view.to_dict(),
            )

        self._emit(
            "candidates_built",
            {
                "symbol": symbol,
                "count": len(candidates),
                "strategy": candidates[0].proposal.strategy.value,
                "candidates": [c.summary() for c in candidates],
                "event_risk": self.structurer.event_risk.to_dict(),
            },
        )

        # --- Stage 3: Reasoning (bounded, replaceable) ----------------------
        choice = self.reasoning.select(
            regime_brief=view.brief(),
            candidates=[c.summary() for c in candidates],
            fallback_index=0,
            fallback_reason=(
                f"Highest deterministic composite score ({candidates[0].score:.3f}) "
                f"with {candidates[0].ev_ratio:+.1%} expectancy at realised volatility."
            ),
        )
        self._emit("reasoning_choice", {"symbol": symbol, **choice.to_dict()})

        if choice.index == -1:
            return SymbolOutcome(
                symbol, "reasoning", False,
                f"Abstained: {choice.rationale}",
                view=view.to_dict(), candidates=len(candidates), choice=choice.to_dict(),
            )

        selected = candidates[choice.index]
        proposal = selected.proposal
        proposal.proposal_id = f"prop-{uuid.uuid4().hex[:12]}"
        proposal.thesis = choice.rationale
        proposal.source = choice.model

        # --- Stage 4: Adversarial audit ------------------------------------
        event = self.structurer.event_risk
        audit = self.auditor.audit(
            proposal,
            realised_vol=view.snapshot.hv_forecast,
            implied_move=event.implied_move,
        )
        self._emit("audit", {"symbol": symbol, "proposal_id": proposal.proposal_id,
                             "event_risk": event.to_dict(), **audit.to_dict()})

        if not audit.passed:
            return SymbolOutcome(
                symbol, "audit", False,
                audit.headline(),
                view=view.to_dict(), candidates=len(candidates),
                choice=choice.to_dict(), proposal=proposal.to_dict(), audit=audit.to_dict(),
            )

        # --- Stage 5: Deterministic risk gate ------------------------------
        payload = self.auditor.risk_payload(proposal, audit)
        verdict = self.gate.evaluate_trade(payload, portfolio_state)
        self._emit(
            "risk_gate",
            {"symbol": symbol, "proposal_id": proposal.proposal_id,
             "payload": payload, **verdict.to_dict()},
        )

        if not verdict.approved:
            return SymbolOutcome(
                symbol, "risk_gate", False, verdict.reason,
                view=view.to_dict(), candidates=len(candidates), choice=choice.to_dict(),
                proposal=proposal.to_dict(), audit=audit.to_dict(), verdict=verdict.to_dict(),
            )

        # --- Stage 6: Execution ---------------------------------------------
        execution = self.executor.submit(proposal, portfolio_state, verdict)
        self._emit("execution", {"symbol": symbol, "proposal_id": proposal.proposal_id,
                                 **execution.to_dict()})

        if execution.submitted:
            # Working order, not a position. It becomes one only when Alpaca
            # confirms a fill -- see _reconcile_fills().
            self.portfolio.add_pending(
                proposal,
                order_id=execution.order_id,
                limit_price=execution.limit_price,
                simulated=execution.simulated,
            )

        return SymbolOutcome(
            symbol,
            "execution",
            execution.submitted,
            (
                f"Working {proposal.contracts}x {proposal.strategy.value} via {execution.route}"
                if execution.submitted
                else (
                    f"Dry run: {proposal.contracts}x {proposal.strategy.value} rendered "
                    f"at {execution.limit_price:+.2f} net, not submitted"
                    if execution.dry_run
                    else f"Execution failed: {execution.error}"
                )
            ),
            view=view.to_dict(), candidates=len(candidates), choice=choice.to_dict(),
            proposal=proposal.to_dict(), audit=audit.to_dict(),
            verdict=verdict.to_dict(), execution=execution.to_dict(),
        )

    # -- open positions ------------------------------------------------------

    def _reconcile_fills(self) -> List[Dict[str, Any]]:
        """Ask the broker what actually happened to every working order.

        `submitted` only ever meant Alpaca accepted the request. Deflow sends
        multi-leg LIMIT orders a few percent through the mid, and on a wide
        spread those can rest all session without trading. Treating acceptance
        as ownership let the desk believe it held structures it did not own,
        stop trading because it thought it was at its position cap, and report
        P&L on fills that never occurred.

        Orders still working past STALE_ORDER_SECONDS are cancelled rather than
        left resting: a limit priced off a quote from twenty minutes ago is no
        longer the trade the gate approved, and holding it reserves risk
        budget that could be doing something.
        """
        if not self.portfolio.pending:
            return []

        outcomes: List[Dict[str, Any]] = []
        for order in list(self.portfolio.pending.values()):
            state = self.executor.order_status(order.order_id)
            status = state["status"]
            order.status = status
            order.checks += 1

            record = {
                "proposal_id": order.id,
                "symbol": order.symbol,
                "order_id": order.order_id,
                "status": status,
                "age_seconds": round(order.age_seconds(), 1),
            }

            if status == "filled":
                filled = state.get("filled_avg_price")
                # Alpaca reports a multi-leg fill as the net package price, in
                # the same sign convention the order used.
                position = self.portfolio.confirm_fill(order.id, filled)
                record["outcome"] = "filled"
                record["filled_price"] = filled
                if position is not None:
                    record["entry_premium"] = round(position.entry_premium, 4)

            elif status in {"canceled", "cancelled", "expired", "rejected", "suspended"}:
                self.portfolio.drop_pending(order.id, status)
                record["outcome"] = "dead"

            elif not state["found"]:
                # The broker has no record of it. Never assume a fill from
                # silence -- release the reserved risk instead.
                self.portfolio.drop_pending(order.id, "not found at broker")
                record["outcome"] = "not_found"

            elif order.age_seconds() > STALE_ORDER_SECONDS:
                cancelled = self.executor.cancel(order.order_id)
                self.portfolio.drop_pending(order.id, f"stale after {order.age_seconds():.0f}s")
                record["outcome"] = "cancelled_stale"
                record["cancel_ok"] = cancelled

            else:
                record["outcome"] = "working"

            outcomes.append(record)
            if record["outcome"] != "working":
                self._emit("fill", record)

        return outcomes

    def _manage_open_positions(self) -> List[Dict[str, Any]]:
        """Mark the book, then close anything the exit guard flags."""
        if not self.portfolio.open:
            return []

        symbols = {p.symbol for p in self.portfolio.open.values()}
        quotes = []
        spots: Dict[str, float] = {}
        for symbol in symbols:
            chain = self.provider.option_chain(symbol, 0, 90)
            quotes.extend(chain)
            if chain:
                spots[symbol] = chain[0].underlying_price
        self.portfolio.mark_all(quotes, spots)

        exits = []
        for position, reason in self.portfolio.exits_due():
            result = self.executor.close(position.proposal, reason)
            record = {
                "position_id": position.id,
                "symbol": position.symbol,
                "strategy": position.proposal.strategy.value,
                "reason": reason,
                "unrealized_pnl": round(position.unrealized_pnl, 2),
                "submitted": result.submitted,
                "route": result.route,
                "error": result.error,
            }
            if result.submitted:
                closed = self.portfolio.close(position.id, reason)
                record["realized_pnl"] = round(closed.realized_pnl, 2) if closed else 0.0
            self._emit("exit", record)
            exits.append(record)
        return exits

    # -- status --------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        chain = self.ledger.verify()
        is_open, why = self._market_state()
        return {
            "mode": self.settings.mode,
            "market_open": is_open,
            "market_detail": why,
            "simulated_market_data": getattr(self.provider, "simulated", True),
            "universe": self.settings.universe,
            "cycles_run": self.cycles,
            "execution": self.executor.describe_route(),
            "reasoning": {
                "featherless_enabled": self.reasoning.enabled,
                "model": self.reasoning.client.model if self.reasoning.enabled else "deterministic-ranker",
                "calls": self.reasoning.client.calls,
                "failures": self.reasoning.client.failures,
            },
            "risk_envelope": self.gate.envelope(),
            "performance": self.portfolio.performance(),
            "working_orders": [o.to_dict() for o in self.portfolio.pending.values()],
            "ledger": {"entries": len(self.ledger), "head": self.ledger.head[:16], **chain.to_dict()},
            "last_cycle": self.last_report.to_dict() if self.last_report else None,
        }


__all__ = ["CycleReport", "SymbolOutcome", "TradingDesk"]
