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
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from risk_gate import DeterministicRiskGate, PortfolioState

from .config import DATA_DIR
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
    unrealized_pnl: float = 0.0
    marked_at: str = ""
    # Set when the last mark fell outside the structure's own payoff bounds,
    # i.e. the quote data behind it could not be trusted.
    mark_suspect: bool = False

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
            "mark_premium": self.mark_premium,
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
            mark_premium=float(d.get("mark_premium", 0.0)),
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
                "order_id": self.order_id,
                "simulated": self.simulated,
            }
        )
        return d


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
        self.cash_pnl = 0.0
        self.open: Dict[str, OpenPosition] = {}
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
        return sum(p.max_loss for p in self.open.values())

    @property
    def day_pnl(self) -> float:
        return self.equity - self.start_of_day_equity

    def risk_by_symbol(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for p in self.open.values():
            out[p.symbol] = out.get(p.symbol, 0.0) + p.max_loss
        return out

    def net_delta(self) -> float:
        return sum(p.proposal.net_delta for p in self.open.values())

    def net_vega(self) -> float:
        return sum(p.proposal.portfolio_greeks().vega for p in self.open.values())

    def state(self) -> PortfolioState:
        """The immutable snapshot the risk gate reads."""
        return PortfolioState(
            equity=self.equity,
            open_positions=len(self.open),
            total_capital_at_risk=self.capital_at_risk,
            net_delta=self.net_delta(),
            net_vega=self.net_vega(),
            risk_by_symbol=self.risk_by_symbol(),
            day_pnl=self.day_pnl,
            start_of_day_equity=self.start_of_day_equity,
        )

    # -- lifecycle ----------------------------------------------------------

    def add(self, proposal: SpreadProposal, order_id: str = "", simulated: bool = False) -> OpenPosition:
        position = OpenPosition(
            proposal=proposal,
            entry_premium=proposal.net_premium,
            entry_at=utcnow(),
            order_id=order_id,
            simulated=simulated,
        )
        self.open[position.id] = position
        self.save()
        return position

    def close(self, position_id: str, reason: str) -> Optional[ClosedPosition]:
        position = self.open.pop(position_id, None)
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

    def exits_due(self) -> List[tuple[OpenPosition, str]]:
        """Positions the deterministic exit guard says to close now."""
        due = []
        for position in self.open.values():
            should_close, reason = self.gate.evaluate_exit(
                unrealized_pnl=position.unrealized_pnl,
                max_loss=position.max_loss,
                max_profit=position.max_profit,
                dte=position.dte,
            )
            if should_close:
                due.append((position, reason))
        return due

    def roll_session(self) -> None:
        """Reset the daily drawdown baseline. Called once per trading day."""
        self.start_of_day_equity = self.equity

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
            "win_rate": round(len(wins) / len(self.closed), 4) if self.closed else 0.0,
            "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
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
                        "session_date": date.today().isoformat(),
                        "starting_equity": self.starting_equity,
                        "start_of_day_equity": self.start_of_day_equity,
                        "cash_pnl": self.cash_pnl,
                        # Lossless state for restore, plus the display shape so
                        # the file stays readable by eye.
                        "open": [p.to_state() for p in self.open.values()],
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

        detail = f"{restored} open, {len(self.closed)} closed"
        if failed:
            detail += f", {failed} UNRESTORABLE — check the broker manually"
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


__all__ = ["ClosedPosition", "OpenPosition", "Portfolio"]
