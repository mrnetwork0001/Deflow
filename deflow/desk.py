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
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from risk_gate import DeterministicRiskGate

from .agents.analyst import MacroVolatilityAnalyst
from .agents.auditor import AdversarialRiskAuditor
from .agents.executor import ExecutionAgent
from . import rolls
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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"} if raw else default

# How long a limit order may rest before the desk withdraws it. A limit
# priced off a twenty-minute-old quote is no longer the trade the gate
# approved, and it reserves risk budget while it waits.
STALE_ORDER_SECONDS = 900

# Rolling is off until the desk has traded a clean session. New logic in
# the exit path is the most expensive place to be wrong, and a roll that
# closes without reopening is a position silently abandoned. Enable with
# DEFLOW_ROLL_ENABLED=true once fills are known good.
ROLL_ENABLED = _bool_env("DEFLOW_ROLL_ENABLED", False)


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
    exit_fills: List[Dict[str, Any]] = field(default_factory=list)
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
            "exit_fills": self.exit_fills,
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
        # proposal_id -> roll count, applied when the order fills.
        self._rolls_carried: Dict[str, int] = {}

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

        # First cycle of a new calendar day re-anchors the daily drawdown
        # baseline. Before the market-closed check on purpose: the baseline
        # belongs to the day, not to the first tradeable minute of it.
        if self.portfolio.ensure_session():
            self._emit("session_rolled", {"start_of_day_equity": self.portfolio.start_of_day_equity})

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
            report.exit_fills = self._reconcile_exits()
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
            return True, "clock check failed - assuming open"

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
                f"{view.bias} tape - buying convexity needs a direction to pay for the theta.",
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
                if position is not None and order.id in self._rolls_carried:
                    position.rolls = self._rolls_carried.pop(order.id)
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
                # A 204 from the cancel endpoint is the request being ACCEPTED;
                # the order can still fill while pending_cancel. Dropping on
                # the ack meant a fill racing the cancel was never adopted --
                # the desk released the risk budget, then owned a position it
                # had no record of. Keep the order pending; the next poll sees
                # the true terminal state ("canceled" drops it, "filled" books
                # it above).
                cancelled = self.executor.cancel(order.order_id)
                record["outcome"] = "cancel_requested"
                record["cancel_ok"] = cancelled

            else:
                record["outcome"] = "working"

            outcomes.append(record)
            if record["outcome"] != "working":
                self._emit("fill", record)

        return outcomes

    def _reconcile_exits(self) -> List[Dict[str, Any]]:
        """Ask the broker what happened to every working CLOSING order.

        Mirrors _reconcile_fills. Nothing here is dropped on a cancel ACK or
        a single failed status poll: an order leaves the pending book only on
        a broker-observed terminal state (filled, canceled, rejected...) or a
        streak of consecutive not-founds. A dropped exit re-arms exits_due,
        and a second close alongside a live first one is a brand-new naked
        position in the opposite direction -- so the bias is always to keep
        the record one cycle longer, never to forget an order that might
        still trade.
        """
        if not self.portfolio.pending_exits:
            return []

        outcomes: List[Dict[str, Any]] = []
        for exit_order in list(self.portfolio.pending_exits.values()):
            # Crash recovery: an exit persisted before its submit window closed
            # may not know its broker id. The deterministic client id was
            # written for exactly this -- ask by name before polling.
            if not exit_order.order_id and exit_order.client_order_id:
                rest = self.executor.rest
                if rest is not None:
                    found = rest.get_order_by_client_id(exit_order.client_order_id)
                    if found.ok and isinstance(found.data, dict) and found.data.get("id"):
                        exit_order.order_id = str(found.data["id"])
                        self.portfolio.save()

            state = self.executor.order_status(exit_order.order_id)
            status = state["status"]
            exit_order.status = status
            exit_order.checks += 1
            filled_qty = state.get("filled_qty") or 0

            record = {
                "position_id": exit_order.position_id,
                "order_id": exit_order.order_id,
                "reason": exit_order.reason,
                "status": status,
                "age_seconds": round(exit_order.age_seconds(), 1),
            }

            if state["found"]:
                exit_order.misses = 0

            if status == "filled":
                closed = self.portfolio.confirm_exit_fill(
                    exit_order.position_id, state.get("filled_avg_price")
                )
                record["outcome"] = "closed"
                if closed is not None:
                    record["realized_pnl"] = round(closed.realized_pnl, 2)

            elif status in {"canceled", "cancelled", "expired", "rejected", "suspended"}:
                if filled_qty > 0:
                    # Part of the close traded before the order died. The book
                    # cannot represent a partially closed structure, and a
                    # fresh full-size close would exit contracts that no longer
                    # exist -- rejected forever at best, an inverted naked
                    # position at worst. Freeze: the pending record stays, so
                    # exits_due() cannot resubmit, and a human reconciles.
                    exit_order.status = "partial_terminal"
                    record["outcome"] = "partial_terminal"
                    log.error(
                        "Exit for %s died %s with %s contracts already filled. "
                        "Automated exits for this position are FROZEN; reconcile "
                        "against the broker by hand.",
                        exit_order.position_id, status, filled_qty,
                    )
                else:
                    self.portfolio.drop_pending_exit(exit_order.position_id, status)
                    record["outcome"] = "dead"

            elif not state["found"]:
                # One not-found is indistinguishable from a dropped connection
                # or a rate limit: alpaca_rest maps every transport failure to
                # the same shape as a 404. Dropping here re-armed exits_due in
                # the SAME cycle -- a second close while the first still
                # rested. Only a streak means the order really is not there.
                exit_order.misses += 1
                if exit_order.misses >= 3:
                    self.portfolio.drop_pending_exit(
                        exit_order.position_id,
                        f"not found at broker on {exit_order.misses} consecutive checks",
                    )
                    record["outcome"] = "not_found"
                else:
                    record["outcome"] = "status_unknown"

            elif exit_order.age_seconds() > STALE_ORDER_SECONDS:
                if filled_qty > 0:
                    # Never cancel a partially filled close: the remainder is
                    # still doing exactly what the desk wants.
                    record["outcome"] = "partial_working"
                else:
                    # Ask for the cancel but keep the record: a 204 is the
                    # broker ACCEPTING the request, and the order can still
                    # fill while pending_cancel. Dropping on the ack lost that
                    # fill. The next poll observes the true terminal state --
                    # "canceled" drops it above, "filled" books it above.
                    self.executor.cancel(exit_order.order_id)
                    record["outcome"] = "cancel_requested"

            else:
                record["outcome"] = "partial_working" if filled_qty > 0 else "working"

            outcomes.append(record)
            if record["outcome"] not in {"working", "partial_working"}:
                self._emit("exit_fill", record)

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

        # Defend before exiting. A tested short near expiry may be worth
        # rolling out for a credit instead of realising the loss -- but only if
        # the roll pays, does not widen the risk, and clears the same gate any
        # new trade would.
        rolled_ids = self._defend(quotes, spots)

        exits = []
        for position, reason in self.portfolio.exits_due():
            if position.id in rolled_ids:
                continue
            # Intent is persisted BEFORE the order exists. The order becomes
            # live inside close(); writing the record only afterwards left a
            # window where a crash or redeploy restored a book with no memory
            # of a close resting at the broker -- and the next cycle submitted
            # another. The client id is deterministic per (position, attempt),
            # so a duplicate of the same attempt is refused by Alpaca rather
            # than doubling the close, and a record with no broker id yet can
            # still be looked up by name.
            position.exit_attempts += 1
            cid = f"deflow-x-{position.id[:12]}-{position.exit_attempts:02d}"
            self.portfolio.add_pending_exit(position.id, "", reason, client_order_id=cid)

            result = self.executor.close(
                position.proposal, reason,
                mark_premium=position.mark_premium,
                client_order_id=cid,
            )
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
            # Submission is not a fill, on the way out exactly as on the way
            # in. Booking here wrote realised P&L to the ledger and freed the
            # risk budget while the legs were still live at the broker under a
            # resting limit order -- a phantom flat. The close becomes real in
            # _reconcile_exits(), when the broker says it traded.
            if result.dry_run or not result.submitted:
                self.portfolio.drop_pending_exit(
                    position.id, "dry run" if result.dry_run else "submit failed"
                )
                record["outcome"] = "dry_run" if result.dry_run else "submit_failed"
            else:
                pending = self.portfolio.pending_exits.get(position.id)
                if pending is not None:
                    pending.order_id = result.order_id
                    pending.limit_price = result.limit_price
                    pending.simulated = result.simulated
                    self.portfolio.save()
                record["outcome"] = "exit_working"
            self._emit("exit", record)
            exits.append(record)
        return exits

    def _defend(
        self, quotes: List[Any], spots: Dict[str, float]
    ) -> set:
        """Roll tested positions out in time, where doing so genuinely helps.

        Executed as close-then-open rather than one atomic multi-expiry order.
        If the close fills and the open does not, the desk is flat -- which is
        a safe place to be. The reverse ordering could leave it holding both
        structures at once, which is not.
        """
        if not ROLL_ENABLED or not self.portfolio.open:
            return set()

        rolled: set = set()
        by_symbol: Dict[str, List[Any]] = {}
        for q in quotes:
            by_symbol.setdefault(q.symbol[:6].rstrip("0123456789"), []).append(q)

        for position in list(self.portfolio.open.values()):
            # Rolling a position whose close is already working could fill
            # both: flat plus a fresh spread the book cannot attribute. And a
            # suspect mark fails the same test here as at the exit guard.
            if position.id in self.portfolio.pending_exits or position.mark_suspect:
                continue
            spot = spots.get(position.symbol, position.proposal.underlying_price)
            why = rolls.should_consider(
                position.proposal, spot, position.unrealized_pnl, position.rolls
            )
            if why is None:
                continue

            chain = self.provider.option_chain(position.symbol, 7, 75)
            plan = rolls.build(position.proposal, chain, spot, why)
            if plan is None:
                continue

            # A roll opens new risk, so it faces the same twelve breakers as
            # any other trade. There is no privileged path to the broker.
            state = self.portfolio.state()
            verdict = self.gate.evaluate_trade(plan.proposal.to_risk_payload(), state)
            record = {**plan.to_dict(), "approved": verdict.approved, "reason": verdict.reason}
            if not verdict.approved:
                self._emit("roll_rejected", record)
                continue

            close = self.executor.close(
                position.proposal, f"rolling: {why}", mark_premium=position.mark_premium
            )
            if not close.submitted:
                record["error"] = f"close failed: {close.error}"
                self._emit("roll_rejected", record)
                continue

            # KNOWN GAP: the roll still books this close on acceptance rather
            # than through the pending-exit lifecycle, because its close-then-
            # open sequencing needs the close CONFIRMED before the new leg goes
            # out -- a bigger change than a flag flip. Rolls ship disabled
            # (DEFLOW_ROLL_ENABLED) and must not be enabled until this books on
            # fill like _manage_open_positions does.
            closed = self.portfolio.close(position.id, f"rolled out: {why}")
            plan.proposal.proposal_id = f"roll-{position.id[-8:]}-{position.rolls + 1}"
            opened = self.executor.submit(plan.proposal, self.portfolio.state(), verdict)
            if opened.submitted:
                order = self.portfolio.add_pending(
                    plan.proposal, order_id=opened.order_id,
                    limit_price=opened.limit_price, simulated=opened.simulated,
                )
                # Carry the count forward so a position cannot be rolled
                # forever by resetting its history each time.
                order.proposal.thesis = plan.reason
                self.portfolio.pending[order.id].proposal.source = "roll"
                self._rolls_carried[order.id] = position.rolls + 1
                record["new_order_id"] = opened.order_id
            else:
                record["error"] = f"reopen failed: {opened.error}"
            record["realized_on_close"] = round(closed.realized_pnl, 2) if closed else 0.0
            self._emit("roll", record)
            rolled.add(position.id)

        return rolled

    # -- status --------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        chain = self.ledger.verify()
        is_open, why = self._market_state()
        # The reopen instant, machine-readable. The detail string embeds it as
        # "closed until 2026-09-02T09:30:00-04:00", which forces every reader
        # to do timezone arithmetic in their head; a dashboard can render a
        # countdown and the viewer's local time from the timestamp alone.
        reopens = None
        if not is_open:
            m = re.search(r"\d{4}-\d{2}-\d{2}T[0-9:.]+(?:[+-]\d{2}:\d{2}|Z)?", why)
            if m:
                reopens = m.group(0)
        return {
            "mode": self.settings.mode,
            "market_open": is_open,
            "market_detail": why,
            "market_reopens_at": reopens,
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
