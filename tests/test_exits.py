"""The exit path must be able to close losers, and must book on fill.

Both defects here were found in the live book on 2026-09-01, before either had
cost money only because no exit had ever fired:

  1. ExecutionAgent.close() derived its limit from proposal.net_premium -- the
     ENTRY price. Closing a long spread bought at $4.20 demanded at least
     $4.33 back, which a winner clears and a loser structurally cannot. The
     one order a stop-loss exists to send was unfillable by construction.

  2. The desk booked portfolio.close() the moment the broker ACCEPTED the
     closing order. For a loser under defect 1 that meant: realised P&L
     written to the hash-chained ledger, risk budget freed, new positions
     opened -- while the "closed" legs were still live at Alpaca under a
     resting order that could never fill.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from deflow.agents.executor import ExecutionAgent, SLIPPAGE_BUFFER
from deflow.models import Leg, SpreadProposal, Strategy, occ_symbol
from deflow.portfolio import PendingExit, Portfolio
from risk_gate import DeterministicRiskGate

EXPIRY = date.today() + timedelta(days=30)


def leg(right, strike, ratio, price, iv=0.20, half_spread=0.02):
    return Leg(occ_symbol("SPY", EXPIRY, right, strike), right, strike, EXPIRY,
               ratio, price, iv, half_spread)


def debit_spread(contracts=1):
    """Long 450/460 call spread for a 4.75 debit."""
    return SpreadProposal("SPY", Strategy.BULL_CALL_SPREAD,
                          [leg("call", 450, +1, 9.10), leg("call", 460, -1, 4.35)],
                          contracts=contracts, underlying_price=452.0)


def credit_spread(contracts=1):
    """Short 530/525 put spread for a 1.05 credit."""
    return SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                          [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.05)],
                          contracts=contracts, underlying_price=540.0)


def offline_executor():
    """No credentials, no CLI: close() falls through to the simulated route,
    which still computes the limit price under test."""
    return ExecutionAgent(gate=DeterministicRiskGate(100_000.0))


# -- defect 1: the closing limit must come from the current mark ------------

def test_a_losing_debit_spread_gets_a_fillable_exit():
    """Bought at 4.75, now marks 3.00. The close must ask ~2.91 -- the old
    entry-derived limit demanded 4.89, which no market would ever pay."""
    ex = offline_executor()
    result = ex.close(debit_spread(), "stop", mark_premium=3.00)
    assert result.limit_price == pytest.approx(-3.00 * (1 - SLIPPAGE_BUFFER), abs=0.01)


def test_a_losing_credit_spread_gets_a_fillable_exit():
    """Sold at 1.05 credit, buying back now costs ~1.50. The close must be
    willing to PAY ~1.55 -- the old limit offered only entry-derived $1.02."""
    ex = offline_executor()
    result = ex.close(credit_spread(), "stop", mark_premium=-1.50)
    assert result.limit_price == pytest.approx(1.50 * (1 + SLIPPAGE_BUFFER), abs=0.01)


def test_the_concession_still_moves_against_us_on_winners():
    ex = offline_executor()
    result = ex.close(debit_spread(), "profit", mark_premium=8.00)
    # Selling the winner: accept slightly less than its value.
    assert result.limit_price == pytest.approx(-8.00 * (1 - SLIPPAGE_BUFFER), abs=0.01)


def test_no_mark_falls_back_to_the_entry_price_rather_than_refusing():
    ex = offline_executor()
    result = ex.close(debit_spread(), "exit", mark_premium=None)
    assert result.limit_price == pytest.approx(-4.75 * (1 + SLIPPAGE_BUFFER), abs=0.01)


# -- defect 2: exits book on fill, through a pending-exit ------------------

def _portfolio():
    pf = Portfolio(DeterministicRiskGate(100_000.0), starting_equity=100_000.0)
    pf._path = pf._path.with_name("test_exits_positions.json")
    return pf


def test_a_pending_exit_does_not_close_the_position(tmp_path, monkeypatch):
    pf = _portfolio()
    monkeypatch.setattr(pf, "_path", tmp_path / "p.json")
    pos = pf.add(debit_spread(), order_id="o-1")
    pf.add_pending_exit(pos.id, "x-1", "stop", limit_price=-2.91)
    assert pos.id in pf.open, "still owned until the broker confirms"
    assert pf.capital_at_risk > 0, "risk budget stays reserved"


def test_exits_due_never_doubles_up_on_a_working_close(tmp_path, monkeypatch):
    pf = _portfolio()
    monkeypatch.setattr(pf, "_path", tmp_path / "p.json")
    pos = pf.add(debit_spread(), order_id="o-1")
    pos.unrealized_pnl = -pos.max_loss  # deep loser: the guard would fire
    pf.add_pending_exit(pos.id, "x-1", "stop")
    assert pf.exits_due() == [], "a second close could fill alongside the first"


def test_exit_books_at_the_brokers_fill_price_not_the_mark(tmp_path, monkeypatch):
    """Filled the close at a 3.10 credit against a 4.75 entry: the realised
    loss is measured from what the broker paid, not from our last mid-mark."""
    pf = _portfolio()
    monkeypatch.setattr(pf, "_path", tmp_path / "p.json")
    pos = pf.add(debit_spread(), order_id="o-1")
    pos.unrealized_pnl = -123.45  # stale mark; must not be what gets booked
    pf.add_pending_exit(pos.id, "x-1", "stop")
    closed = pf.confirm_exit_fill(pos.id, filled_net=-3.10)
    assert closed is not None
    assert closed.realized_pnl == pytest.approx((3.10 - 4.75) * 100)
    assert pos.id not in pf.open


def test_a_dropped_exit_leaves_the_position_open_for_another_try(tmp_path, monkeypatch):
    pf = _portfolio()
    monkeypatch.setattr(pf, "_path", tmp_path / "p.json")
    pos = pf.add(debit_spread(), order_id="o-1")
    pf.add_pending_exit(pos.id, "x-1", "stop")
    pf.drop_pending_exit(pos.id, "stale")
    assert pos.id in pf.open
    assert pos.id not in pf.pending_exits


def test_pending_exits_survive_a_restart(tmp_path, monkeypatch):
    """A restart that forgets a working close would resubmit next cycle --
    and if the forgotten order then fills too, the desk is short a structure
    it thinks it exited once."""
    pf = _portfolio()
    monkeypatch.setattr(pf, "_path", tmp_path / "p.json")
    pos = pf.add(debit_spread(), order_id="o-1")
    pf.add_pending_exit(pos.id, "x-77", "stop", limit_price=-2.91)

    reborn = Portfolio(DeterministicRiskGate(100_000.0), starting_equity=100_000.0)
    monkeypatch.setattr(reborn, "_path", tmp_path / "p.json")
    reborn.load()
    assert pos.id in reborn.pending_exits
    assert reborn.pending_exits[pos.id].order_id == "x-77"
