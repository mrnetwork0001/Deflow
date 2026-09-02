"""Position book, mark-to-market, and the exit guard.

Deflow tracks its own book rather than deriving it from Alpaca's positions
endpoint alone. Alpaca reports *legs* -- four separate option positions for an
iron condor -- with no record that they were opened as one structure with one
defined maximum loss. The exit rules operate on structures, so the structure is
what gets persisted here, and the broker's view is reconciled against it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from risk_gate import DeterministicRiskGate, PortfolioState

from . import rolls
from .config import DATA_DIR, SETTINGS
from .greeks import black_scholes, years_to_expiry
from .models import (
    CONTRACT_MULTIPLIER,
    Leg,
    OptionQuote,
    Regime,
    SpreadProposal,
    Strategy,
    utcnow,
)

log = logging.getLogger("deflow.portfolio")


@dataclass
class OpenPosition:
    """One live multi-leg structure."""

    proposal: SpreadProposal
    entry_premium: float          # per-share net, signed (debit +, credit -)
    entry_at: str
    order_id: str = ""
    simulated: bool = False
    mark_premium: float = 0.0     # current net, same convention
    # How many closing orders have ever been submitted for this position.
    # Persisted, so the deterministic client_order_id derived from it never
    # collides with an order from before a restart.
    exit_attempts: int = 0
    unrealized_pnl: float = 0.0
    marked_at: str = ""
    # Set when the last mark fell outside the structure's own payoff bounds,
    # i.e. the quote data behind it could not be trusted.
    mark_suspect: bool = False
    # How many times this structure has been rolled out. Capped, because a
    # position rolled indefinitely is a losing view being refused rather than
    # a trade being managed.
    rolls: int = 0

    @property
    def id(self) -> str:
        return self.proposal.proposal_id

    @property
    def symbol(self) -> str:
        return self.proposal.symbol

    @property
    def max_loss(self) -> float:
        return self.proposal.max_loss

    @property
    def max_profit(self) -> float:
        return self.proposal.max_profit

    @property
    def dte(self) -> int:
        return self.proposal.dte

    def mark(self, quotes_by_symbol: Dict[str, OptionQuote], spot: float = 0.0) -> float:
        """Re-price the structure and update unrealised P&L.

        `spot` is the underlying's *current* price. It matters: legs missing
        from the quote map are re-priced from Black-Scholes, and doing that at
        the entry-time underlying price marks the leg at what it was worth when
        the position was opened. That silently freezes the risk picture of any
        leg whose quote drops out, which is exactly the leg most likely to have
        moved. Falling back on the entry price only happens when no current
        spot is available at all.
        """
        reference_spot = spot if spot > 0 else self.proposal.underlying_price
        net = 0.0
        for leg in self.proposal.legs:
            quote = quotes_by_symbol.get(leg.symbol)
            if quote is not None and quote.mid > 0:
                price = quote.mid
            else:
                dte = max((leg.expiry - date.today()).days, 0)
                price = black_scholes(
                    reference_spot, leg.strike,
                    years_to_expiry(dte), leg.implied_vol or 0.20, leg.right,
                ).price
            net += leg.ratio * price

        self.mark_premium = net
        raw_pnl = (net - self.entry_premium) * CONTRACT_MULTIPLIER * self.proposal.contracts

        # Structural clamp. A defined-risk spread cannot be worth more than its
        # maximum profit or less than its maximum loss -- those bounds are
        # properties of the geometry, not of the quotes. A mark outside them
        # means the quote data is bad (a stale leg, a crossed market, a partial
        # chain), and an unclamped bad mark does real damage: it fires the exit
        # guard's profit target or stop on a price that never existed. Clamp,
        # and say so.
        ceiling, floor = self.max_profit, -self.max_loss
        if raw_pnl > ceiling or raw_pnl < floor:
            log.warning(
                "%s mark %.2f outside structural bounds [%.2f, %.2f]; clamping. "
                "Check quote coverage for %s.",
                self.symbol, raw_pnl, floor, ceiling,
                [leg.symbol for leg in self.proposal.legs if leg.symbol not in quotes_by_symbol],
            )
            self.mark_suspect = True
            raw_pnl = max(floor, min(raw_pnl, ceiling))
        else:
            self.mark_suspect = False

        self.unrealized_pnl = raw_pnl
        self.marked_at = utcnow()
        return self.unrealized_pnl

    def to_state(self) -> Dict[str, Any]:
        """Lossless snapshot for persistence.

        Deliberately not `to_dict()`: that is the display shape, and it rounds.
        Rebuilding a position from rounded strikes and premiums would shift its
        computed max loss, and max loss is what every risk limit is measured
        against.
        """
        return {
            "proposal_id": self.proposal.proposal_id,
            "symbol": self.proposal.symbol,
            "strategy": self.proposal.strategy.value,
            "contracts": self.proposal.contracts,
            "underlying_price": self.proposal.underlying_price,
            "iv_rank": self.proposal.iv_rank,
            "regime": self.proposal.regime.value,
            "thesis": self.proposal.thesis,
            "source": self.proposal.source,
            "proposed_at": self.proposal.proposed_at,
            "legs": [
                {
                    "symbol": l.symbol, "right": l.right, "strike": l.strike,
                    "expiry": l.expiry.isoformat(), "ratio": l.ratio,
                    "price": l.price, "implied_vol": l.implied_vol,
                    "half_spread": l.half_spread,
                }
                for l in self.proposal.legs
            ],
            "entry_premium": self.entry_premium,
            "entry_at": self.entry_at,
            "order_id": self.order_id,
            "simulated": self.simulated,
            "rolls": self.rolls,
            "mark_premium": self.mark_premium,
            "exit_attempts": self.exit_attempts,
            "unrealized_pnl": self.unrealized_pnl,
            "marked_at": self.marked_at,
        }

    @staticmethod
    def from_state(d: Dict[str, Any]) -> "OpenPosition":
        proposal = SpreadProposal(
            symbol=d["symbol"],
            strategy=Strategy(d["strategy"]),
            legs=[
                Leg(
                    symbol=l["symbol"], right=l["right"], strike=float(l["strike"]),
                    expiry=date.fromisoformat(l["expiry"]), ratio=int(l["ratio"]),
                    price=float(l["price"]), implied_vol=float(l.get("implied_vol", 0.20)),
                    half_spread=float(l.get("half_spread", 0.0)),
                )
                for l in d["legs"]
            ],
            contracts=int(d["contracts"]),
            underlying_price=float(d["underlying_price"]),
            thesis=d.get("thesis", ""),
            iv_rank=float(d.get("iv_rank", 0.0)),
            regime=Regime(d.get("regime", Regime.LOW_VOL_RANGE.value)),
            proposed_at=d.get("proposed_at", ""),
            proposal_id=d.get("proposal_id", ""),
            source=d.get("source", "restored"),
        )
        return OpenPosition(
            proposal=proposal,
            entry_premium=float(d["entry_premium"]),
            entry_at=d.get("entry_at", ""),
            order_id=d.get("order_id", ""),
            simulated=bool(d.get("simulated", False)),
            rolls=int(d.get("rolls", 0)),
            mark_premium=float(d.get("mark_premium", 0.0)),
            exit_attempts=int(d.get("exit_attempts", 0)),
            unrealized_pnl=float(d.get("unrealized_pnl", 0.0)),
            marked_at=d.get("marked_at", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = self.proposal.to_dict()
        d.update(
            {
                "entry_premium": round(self.entry_premium, 4),
                "mark_premium": round(self.mark_premium, 4),
                "unrealized_pnl": round(self.unrealized_pnl, 2),
                "pnl_pct_of_max_loss": (
                    round(self.unrealized_pnl / self.max_loss, 4) if self.max_loss else 0.0
                ),
                "entry_at": self.entry_at,
                "marked_at": self.marked_at,
                "mark_suspect": self.mark_suspect,
                "rolls": self.rolls,
                "order_id": self.order_id,
                "simulated": self.simulated,
            }
        )
        return d


@dataclass
class PendingOrder:
    """A submitted order that has not been confirmed filled.

    The distinction this type exists to make: Alpaca accepting an order is not
    the same as holding a position. Deflow sends multi-leg LIMIT orders a few
    percent through the mid, and those routinely rest unfilled -- a wide spread
    may never trade at the price asked. Booking on acceptance meant the desk
    could believe it held six structures it did not own, refuse to open
    anything further because it thought it was at its position cap, and report
    P&L on trades that never happened.

    Pending orders still consume risk budget while they are live, because they
    might fill at any moment; what they do not do is count as positions.
    """

    proposal: SpreadProposal
    order_id: str
    submitted_at: str
    limit_price: float
    simulated: bool = False
    status: str = "new"
    checks: int = 0

    @property
    def id(self) -> str:
        return self.proposal.proposal_id

    @property
    def symbol(self) -> str:
        return self.proposal.symbol

    @property
    def max_loss(self) -> float:
        return self.proposal.max_loss

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        try:
            started = datetime.fromisoformat(self.submitted_at)
        except (TypeError, ValueError):
            return 0.0
        now = now or datetime.now(timezone.utc)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max((now - started).total_seconds(), 0.0)

    def to_state(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "submitted_at": self.submitted_at,
            "limit_price": self.limit_price,
            "simulated": self.simulated,
            "status": self.status,
            "checks": self.checks,
            "position": OpenPosition(
                proposal=self.proposal,
                entry_premium=self.proposal.net_premium,
                entry_at=self.submitted_at,
            ).to_state(),
        }

    @staticmethod
    def from_state(d: Dict[str, Any]) -> "PendingOrder":
        restored = OpenPosition.from_state(d["position"])
        return PendingOrder(
            proposal=restored.proposal,
            order_id=d.get("order_id", ""),
            submitted_at=d.get("submitted_at", ""),
            limit_price=float(d.get("limit_price", 0.0)),
            simulated=bool(d.get("simulated", False)),
            status=d.get("status", "new"),
            checks=int(d.get("checks", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = self.proposal.to_dict()
        d.update({
            "order_id": self.order_id,
            "submitted_at": self.submitted_at,
            "limit_price": round(self.limit_price, 2),
            "status": self.status,
            "age_seconds": round(self.age_seconds(), 1),
            "simulated": self.simulated,
        })
        return d



@dataclass
class PendingExit:
    """A submitted CLOSING order that has not been confirmed filled.

    The entry side learned this lesson first: Alpaca accepting an order says
    nothing about a fill. Booking an exit on acceptance was worse than the
    entry version of the bug -- the desk wrote realised P&L to the ledger,
    freed the risk budget and opened new positions while the "closed" legs
    were still live at the broker under a resting order. The position stays in
    the book, still marked and still consuming budget, until the broker
    confirms the close actually traded.
    """

    position_id: str
    order_id: str
    reason: str
    submitted_at: str
    limit_price: float = 0.0
    simulated: bool = False
    status: str = "new"
    checks: int = 0
    # Deterministic id written to disk BEFORE the order goes out, so a crash
    # in the submit window leaves a name the broker can be asked about -- and
    # a duplicate resubmission with the same id is rejected by Alpaca instead
    # of doubling the close.
    client_order_id: str = ""
    # Consecutive status polls where the broker claimed no such order. One
    # not-found is indistinguishable from a dropped connection or a 429; only
    # a streak of them means the order genuinely does not exist.
    misses: int = 0

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        try:
            started = datetime.fromisoformat(self.submitted_at)
        except (TypeError, ValueError):
            return 0.0
        now = now or datetime.now(timezone.utc)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max((now - started).total_seconds(), 0.0)

    def to_state(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "order_id": self.order_id,
            "reason": self.reason,
            "submitted_at": self.submitted_at,
            "limit_price": self.limit_price,
            "simulated": self.simulated,
            "status": self.status,
            "checks": self.checks,
            "client_order_id": self.client_order_id,
            "misses": self.misses,
        }

    @staticmethod
    def from_state(d: Dict[str, Any]) -> "PendingExit":
        return PendingExit(
            position_id=str(d["position_id"]),
            order_id=str(d.get("order_id", "")),
            reason=str(d.get("reason", "")),
            submitted_at=str(d.get("submitted_at", "")),
            limit_price=float(d.get("limit_price", 0.0)),
            simulated=bool(d.get("simulated", False)),
            status=str(d.get("status", "new")),
            checks=int(d.get("checks", 0)),
            client_order_id=str(d.get("client_order_id", "")),
            misses=int(d.get("misses", 0)),
        )


@dataclass
class ClosedPosition:
    position: OpenPosition
    realized_pnl: float
    reason: str
    closed_at: str = field(default_factory=utcnow)

    def to_state(self) -> Dict[str, Any]:
        return {
            "position": self.position.to_state(),
            "realized_pnl": self.realized_pnl,
            "reason": self.reason,
            "closed_at": self.closed_at,
        }

    @staticmethod
    def from_state(d: Dict[str, Any]) -> "ClosedPosition":
        return ClosedPosition(
            position=OpenPosition.from_state(d["position"]),
            realized_pnl=float(d["realized_pnl"]),
            reason=d.get("reason", ""),
            closed_at=d.get("closed_at", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.position.to_dict(),
            "realized_pnl": round(self.realized_pnl, 2),
            "close_reason": self.reason,
            "closed_at": self.closed_at,
        }


class Portfolio:
    """The desk's book: open structures, realised P&L, and the exit guard."""

    def __init__(self, gate: DeterministicRiskGate, starting_equity: float = 100_000.0) -> None:
        self.gate = gate
        self.starting_equity = starting_equity
        self.start_of_day_equity = starting_equity
        # The day the drawdown baseline belongs to. Persisted as-is: save()
        # used to stamp date.today() instead, so one save after midnight wrote
        # the new date onto the OLD baseline and every safeguard downstream
        # trusted the mislabel.
        self.session_date: str = date.today().isoformat()
        self.cash_pnl = 0.0
        self.open: Dict[str, OpenPosition] = {}
        self.pending: Dict[str, PendingOrder] = {}
        # Keyed by position_id. A position with a pending exit stays in `open`
        # -- it is still owned, still marked, still consuming risk budget --
        # but the guard must not submit a second close for it.
        self.pending_exits: Dict[str, PendingExit] = {}
        self.closed: List[ClosedPosition] = []
        self._path = DATA_DIR / "positions.json"

    # -- book state ---------------------------------------------------------

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.open.values())

    @property
    def realized_pnl(self) -> float:
        return self.cash_pnl

    @property
    def equity(self) -> float:
        return self.starting_equity + self.realized_pnl + self.unrealized_pnl

    @property
    def capital_at_risk(self) -> float:
        """Risk already committed, including orders still working.

        A resting limit order can fill at any moment, so its defined loss is
        capital the desk has already spoken for. Excluding it would let the
        gate authorise a book that breaches its own ceiling the instant the
        working orders trade.
        """
        return sum(p.max_loss for p in self.open.values()) + sum(
            o.max_loss for o in self.pending.values()
        )

    @property
    def day_pnl(self) -> float:
        return self.equity - self.start_of_day_equity

    def risk_by_symbol(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for p in self.open.values():
            out[p.symbol] = out.get(p.symbol, 0.0) + p.max_loss
        for o in self.pending.values():
            out[o.symbol] = out.get(o.symbol, 0.0) + o.max_loss
        return out

    def net_delta(self) -> float:
        return sum(p.proposal.net_delta for p in self.open.values())

    def net_vega(self) -> float:
        return sum(p.proposal.portfolio_greeks().vega for p in self.open.values())

    def state(self) -> PortfolioState:
        """The immutable snapshot the risk gate reads."""
        return PortfolioState(
            equity=self.equity,
            open_positions=len(self.open) + len(self.pending),
            total_capital_at_risk=self.capital_at_risk,
            net_delta=self.net_delta(),
            net_vega=self.net_vega(),
            risk_by_symbol=self.risk_by_symbol(),
            day_pnl=self.day_pnl,
            start_of_day_equity=self.start_of_day_equity,
        )

    # -- lifecycle ----------------------------------------------------------

    def add_pending(
        self, proposal: SpreadProposal, order_id: str, limit_price: float, simulated: bool = False
    ) -> PendingOrder:
        """Record a working order. It is not a position until it fills."""
        order = PendingOrder(
            proposal=proposal,
            order_id=order_id,
            submitted_at=utcnow(),
            limit_price=limit_price,
            simulated=simulated,
        )
        self.pending[order.id] = order
        self.save()
        return order

    def confirm_fill(
        self, proposal_id: str, filled_price: Optional[float] = None
    ) -> Optional[OpenPosition]:
        """Promote a working order to a position, at the price it actually got."""
        order = self.pending.pop(proposal_id, None)
        if order is None:
            return None
        position = self.add(
            order.proposal,
            order_id=order.order_id,
            simulated=order.simulated,
            entry_premium=filled_price,
        )
        return position

    def drop_pending(self, proposal_id: str, reason: str) -> Optional[PendingOrder]:
        """Discard a working order that will never become a position."""
        order = self.pending.pop(proposal_id, None)
        if order is not None:
            log.info("Dropped working order %s (%s): %s", proposal_id, order.symbol, reason)
            self.save()
        return order

    def add_pending_exit(
        self, position_id: str, order_id: str, reason: str,
        limit_price: float = 0.0, simulated: bool = False, client_order_id: str = "",
    ) -> PendingExit:
        """Record a working CLOSING order. The position is closed only when it fills."""
        exit_order = PendingExit(
            position_id=position_id,
            order_id=order_id,
            reason=reason,
            submitted_at=utcnow(),
            limit_price=limit_price,
            simulated=simulated,
            client_order_id=client_order_id,
        )
        self.pending_exits[position_id] = exit_order
        self.save()
        return exit_order

    def confirm_exit_fill(
        self, position_id: str, filled_net: Optional[float] = None
    ) -> Optional[ClosedPosition]:
        """Book the close at the price the broker actually gave.

        `filled_net` is the closing package price in Alpaca's convention
        (positive debit paid, negative credit received). Closing is the mirror
        of holding, so the structure's terminal value is -filled_net, and the
        realised P&L is measured from there -- not from the last mid-mark,
        which is a forecast of this number, not a record of it.
        """
        exit_order = self.pending_exits.pop(position_id, None)
        if exit_order is None:
            return None
        position = self.open.get(position_id)
        if position is not None and filled_net is not None:
            position.unrealized_pnl = (
                (-filled_net - position.entry_premium)
                * CONTRACT_MULTIPLIER
                * position.proposal.contracts
            )
        return self.close(position_id, exit_order.reason)

    def drop_pending_exit(self, position_id: str, reason: str) -> Optional[PendingExit]:
        """Discard a closing order that will never fill. The position stays
        open -- the exit guard will flag it again next cycle at a fresh mark."""
        exit_order = self.pending_exits.pop(position_id, None)
        if exit_order is not None:
            log.info("Dropped closing order for %s: %s", position_id, reason)
            self.save()
        return exit_order

    def add(
        self,
        proposal: SpreadProposal,
        order_id: str = "",
        simulated: bool = False,
        entry_premium: Optional[float] = None,
    ) -> OpenPosition:
        position = OpenPosition(
            proposal=proposal,
            # Prefer the price the order actually filled at over the mid the
            # structurer priced it from; P&L is measured against what was paid.
            entry_premium=entry_premium if entry_premium is not None else proposal.net_premium,
            entry_at=utcnow(),
            order_id=order_id,
            simulated=simulated,
        )
        self.open[position.id] = position
        self.save()
        return position

    def close(self, position_id: str, reason: str) -> Optional[ClosedPosition]:
        position = self.open.pop(position_id, None)
        # A close by any path retires the exit-order record with it; a
        # PendingExit pointing at a popped position would block nothing and
        # confuse every reconcile that walks it.
        self.pending_exits.pop(position_id, None)
        if position is None:
            return None
        realized = position.unrealized_pnl
        self.cash_pnl += realized
        record = ClosedPosition(position=position, realized_pnl=realized, reason=reason)
        self.closed.append(record)
        self.save()
        return record

    def mark_all(self, quotes: Sequence[OptionQuote], spots: Optional[Dict[str, float]] = None) -> None:
        """Re-price every open structure against the current chain."""
        by_symbol = {q.symbol: q for q in quotes}
        # Derive each underlying's current price from its own quotes when the
        # caller has not supplied one.
        spots = dict(spots or {})
        for q in quotes:
            spots.setdefault(q.symbol[:6].rstrip("0123456789"), q.underlying_price)
        for position in self.open.values():
            position.mark(by_symbol, spots.get(position.symbol, 0.0))

    def _mandate_days_left(self) -> Optional[int]:
        """Calendar days until the desk's mandate ends, or None if open-ended."""
        raw = SETTINGS.mandate_end
        if not raw:
            return None
        try:
            end = date.fromisoformat(raw)
        except ValueError:
            log.warning("DEFLOW_MANDATE_END %r is not an ISO date; ignoring it", raw)
            return None
        return (end - date.today()).days

    def _mandate_flatten_now(self, days_left: Optional[int]) -> bool:
        """True once the final session's flatten window has opened."""
        if days_left is None or days_left > 0:
            return False
        try:
            hh, mm = SETTINGS.mandate_flatten_utc.split(":")
            gate_minutes = int(hh) * 60 + int(mm)
        except (ValueError, AttributeError):
            gate_minutes = 14 * 60
        now = datetime.now(timezone.utc)
        return now.hour * 60 + now.minute >= gate_minutes

    def exits_due(self) -> List[tuple[OpenPosition, str]]:
        """Positions the deterministic exit guard says to close now.

        The gate's fixed 75% profit target still applies as the outer bound,
        but a time-scaled target closes winners earlier as expiry approaches.
        The last quarter of a credit spread's profit arrives only as the short
        decays to nothing, which is precisely when gamma is largest -- holding
        for it risks the most to earn the least.
        """
        due = []
        days_left = self._mandate_days_left()
        flatten = self._mandate_flatten_now(days_left)
        for position in self.open.values():
            # Already has a close working at the broker. Submitting another
            # would risk both filling -- a doubled exit is a new naked position
            # in the opposite direction.
            if position.id in self.pending_exits:
                continue
            if flatten:
                # The mandate's final session: every mark still on the book at
                # the deadline is provisional, and a mark is not a result. The
                # flatten ignores mark_suspect on purpose -- there is no next
                # cycle to defer to -- and the close is priced off the current
                # mark with the usual concession either way.
                due.append((position, (
                    f"MANDATE HORIZON: flattening before the mandate ends "
                    f"({SETTINGS.mandate_end}); realising "
                    f"${position.unrealized_pnl:,.2f} rather than carrying a mark."
                )))
                continue
            # A mark outside the structure's own payoff bounds is bad data by
            # definition (mark() clamps the P&L and raises this flag). Firing
            # the stop on it exits a healthy position at a price that never
            # existed; the quotes refresh next cycle, so deferring never
            # delays a real stop.
            if position.mark_suspect:
                continue
            should_close, reason = self.gate.evaluate_exit(
                unrealized_pnl=position.unrealized_pnl,
                max_loss=position.max_loss,
                max_profit=position.max_profit,
                dte=position.dte,
            )
            if not should_close and position.max_profit > 0:
                target = rolls.profit_target(position.dte)
                basis = f"at {position.dte} DTE"
                # A known end date imposes its own urgency: whichever target
                # is LOWER wins, because a target the position cannot reach
                # before the mandate ends is a refusal to realise.
                if days_left is not None:
                    ht = rolls.horizon_target(days_left)
                    if ht is not None and ht < target:
                        target = ht
                        basis = f"with {max(days_left, 0)} session(s) of mandate left"
                if position.unrealized_pnl >= target * position.max_profit:
                    should_close = True
                    reason = (
                        f"PROFIT TARGET (time-scaled): ${position.unrealized_pnl:,.2f} reached "
                        f"{target:.0%} of ${position.max_profit:,.2f} {basis}."
                    )
            if should_close:
                due.append((position, reason))
        return due

    def ensure_session(self) -> bool:
        """Roll the daily-drawdown baseline when the calendar day has changed.

        Found via a competitor's build-in-public post describing the same bug
        class: their drawdown baseline was initialised "to whatever the account
        was worth right now". Ours was subtler - roll_session existed and
        nothing called it, so the baseline only moved when a restart happened
        to cross midnight. Left unrolled after a winning day, the -3% daily
        kill-switch quietly widens: a fall measured from yesterday's lower
        baseline reads smaller than the fall the desk actually took today.
        Called at the top of every cycle; a no-op within the same day.
        """
        today = date.today().isoformat()
        if today == self.session_date:
            return False
        self.session_date = today
        self.start_of_day_equity = self.equity
        self.save()
        return True

    # -- statistics ---------------------------------------------------------

    def performance(self) -> Dict[str, Any]:
        """Trade statistics for the dashboard and the submission write-up."""
        wins = [c for c in self.closed if c.realized_pnl > 0]
        losses = [c for c in self.closed if c.realized_pnl <= 0]
        gross_win = sum(c.realized_pnl for c in wins)
        gross_loss = abs(sum(c.realized_pnl for c in losses))

        return {
            "starting_equity": round(self.starting_equity, 2),
            "equity": round(self.equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.equity - self.starting_equity, 2),
            "return_pct": round((self.equity / self.starting_equity - 1.0) * 100.0, 4),
            "day_pnl": round(self.day_pnl, 2),
            "open_positions": len(self.open),
            "closed_positions": len(self.closed),
            "wins": len(wins),
            "losses": len(losses),
            # A win rate over zero closed trades is not 0%, it is undefined --
            # and the API is as judge-facing as the dashboard, which already
            # renders these as dashes. None, not a fabricated zero.
            "win_rate": round(len(wins) / len(self.closed), 4) if self.closed else None,
            "avg_win": round(gross_win / len(wins), 2) if wins else None,
            "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
            # Profit factor is undefined with no losses; report None rather
            # than an infinity that would render as a fake headline number.
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "capital_at_risk": round(self.capital_at_risk, 2),
            "capital_at_risk_pct": round(self.capital_at_risk / self.equity * 100, 3) if self.equity else 0.0,
            "net_delta": round(self.net_delta(), 4),
            "net_vega": round(self.net_vega(), 2),
        }

    # -- persistence --------------------------------------------------------

    def save(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {
                        "saved_at": utcnow(),
                        "session_date": self.session_date,
                        "starting_equity": self.starting_equity,
                        "start_of_day_equity": self.start_of_day_equity,
                        "cash_pnl": self.cash_pnl,
                        # Lossless state for restore, plus the display shape so
                        # the file stays readable by eye.
                        "open": [p.to_state() for p in self.open.values()],
                        "pending": [o.to_state() for o in self.pending.values()],
                        "pending_exits": [e.to_state() for e in self.pending_exits.values()],
                        "closed": [c.to_state() for c in self.closed],
                        "open_readable": [p.to_dict() for p in self.open.values()],
                    },
                    indent=1,
                    default=str,
                )
            )
        except OSError as exc:
            log.warning("Could not persist positions: %s", exc)

    def load(self) -> Dict[str, Any]:
        """Restore the book from disk. Called once, at startup.

        Without this the desk forgot every open position on restart, and the
        consequences compound: the exit guard cannot stop out or take profit on
        a structure it does not know about; the risk gate sees an empty book
        and authorises another six positions on top of the ones still live at
        the broker; realised P&L resets to zero; and the daily drawdown
        baseline the kill switch measures against moves to the wrong point.

        A deploy, a crash or a reboot was enough to trigger all of it.

        The start-of-day equity baseline is only carried over when the saved
        session is today's -- otherwise the -3% kill switch would be measuring
        against a previous day's opening balance.
        """
        if not self._path.exists():
            return {"restored": 0, "detail": "no saved book"}

        try:
            saved = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Could not read the saved book (%s); starting flat", exc)
            return {"restored": 0, "detail": f"unreadable: {exc}"}

        restored, failed = 0, 0
        for record in saved.get("open", []):
            try:
                position = OpenPosition.from_state(record)
            except (KeyError, ValueError, TypeError) as exc:
                # Never drop a position silently: an unrestorable one is still
                # live at the broker and now invisible to the desk.
                log.error("Could not restore position %s: %s", record.get("proposal_id"), exc)
                failed += 1
                continue
            self.open[position.id] = position
            restored += 1

        for record in saved.get("pending", []):
            try:
                order = PendingOrder.from_state(record)
            except (KeyError, ValueError, TypeError) as exc:
                log.error("Could not restore working order: %s", exc)
                continue
            self.pending[order.id] = order

        for record in saved.get("pending_exits", []):
            try:
                exit_order = PendingExit.from_state(record)
            except (KeyError, ValueError, TypeError) as exc:
                log.error("Could not restore closing order: %s", exc)
                continue
            # An exit for a position that did not restore is unactionable.
            if exit_order.position_id in self.open:
                self.pending_exits[exit_order.position_id] = exit_order

        for record in saved.get("closed", []):
            try:
                self.closed.append(ClosedPosition.from_state(record))
            except (KeyError, ValueError, TypeError):
                continue

        self.cash_pnl = float(saved.get("cash_pnl", 0.0))
        self.starting_equity = float(saved.get("starting_equity", self.starting_equity))

        if saved.get("session_date") == date.today().isoformat():
            self.start_of_day_equity = float(saved.get("start_of_day_equity", self.equity))
        else:
            self.start_of_day_equity = self.equity
        self.session_date = date.today().isoformat()

        detail = f"{restored} open, {len(self.pending)} working, {len(self.closed)} closed"
        if failed:
            detail += f", {failed} UNRESTORABLE - check the broker manually"
        log.info("Restored book: %s", detail)
        return {"restored": restored, "failed": failed, "detail": detail}

    def sync_from_alpaca(self, alpaca_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Reconcile the local book against the broker's option positions.

        Reports rather than mutates. A mismatch means either a leg was filled
        that Deflow does not know about, or a structure Deflow believes is open
        has been closed or assigned -- both need a human to look, not an
        automatic overwrite of the risk picture.
        """
        broker_symbols = {
            p.get("symbol", "") for p in alpaca_positions if p.get("asset_class") == "us_option"
        }
        local_symbols = {leg.symbol for p in self.open.values() for leg in p.proposal.legs}
        return {
            "broker_option_legs": len(broker_symbols),
            "local_option_legs": len(local_symbols),
            "missing_at_broker": sorted(local_symbols - broker_symbols),
            "unknown_to_deflow": sorted(broker_symbols - local_symbols),
            "in_sync": broker_symbols == local_symbols,
        }


__all__ = ["ClosedPosition", "OpenPosition", "PendingOrder", "Portfolio"]
