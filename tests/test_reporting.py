"""The dashboard's money figures must be the broker's money figures.

Two defects on 2026-09-01 motivated every test here, and both were live on a
public dashboard before they were caught:

  1. The account panel read $100,581.55 while Alpaca read $100,405.60. Deflow
     marks every leg at the quote mid; Alpaca marks at liquidation, long legs
     toward the bid and short legs toward the ask. A spread has one of each, so
     the mid flatters both ends and the book reads high every time.

  2. The equity panel read "EQUITY $444.00, +133.68%". Alpaca's portfolio
     history for that account returned base_value 100000.0 with an equity array
     of [0]*29 + [190.0, 444.0] -- gains, not equity. The only filter was
     `> 0.0`, which 190 and 444 pass, so the first point became the baseline.
"""

from __future__ import annotations

import types

import pytest

from deflow import api


class _Result:
    def __init__(self, data, ok=True, error=""):
        self.data, self.ok, self.error = data, ok, error


class _Rest:
    """Minimal stand-in for AlpacaClient. No network."""

    def __init__(self, equity="100405.60", legs=(-155.0, 309.0)):
        self._equity, self._legs = equity, legs
        self.account_calls = 0

    def get_account(self):
        self.account_calls += 1
        return _Result({"equity": self._equity})

    def get_positions(self):
        return _Result([{"unrealized_pl": str(v)} for v in self._legs])


def _desk(rest):
    return types.SimpleNamespace(executor=types.SimpleNamespace(rest=rest))


def _settings(monkeypatch, *, dry_run: bool, creds: bool = True):
    """Settings is a frozen dataclass, so the object is replaced rather than
    mutated. _broker_truth reads exactly these two fields."""
    monkeypatch.setattr(
        api, "SETTINGS",
        types.SimpleNamespace(dry_run=dry_run, has_alpaca_credentials=creds),
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    api._broker_cache["snapshot"] = None
    api._broker_cache["at"] = 0.0
    yield
    api._broker_cache["snapshot"] = None
    api._broker_cache["at"] = 0.0


def test_broker_truth_reports_the_brokers_numbers(monkeypatch):
    _settings(monkeypatch, dry_run=False, creds=True)
    rest = _Rest()
    truth = api._broker_truth(_desk(rest))
    assert truth["equity"] == 100405.60
    assert truth["unrealized_pnl"] == 154.0  # -155 + 309


def test_broker_truth_is_cached_so_a_5s_poll_is_not_a_5s_broker_call(monkeypatch):
    _settings(monkeypatch, dry_run=False, creds=True)
    rest = _Rest()
    desk = _desk(rest)
    for _ in range(5):
        api._broker_truth(desk)
    assert rest.account_calls == 1


def test_dry_run_never_borrows_the_brokers_equity(monkeypatch):
    """Simulated fills are a different book. A real balance beside imaginary
    trades is worse than mid-marks that say they are mid-marks."""
    _settings(monkeypatch, dry_run=True, creds=True)
    assert api._broker_truth(_desk(_Rest())) is None


def test_no_credentials_returns_none_rather_than_guessing(monkeypatch):
    _settings(monkeypatch, dry_run=False, creds=False)
    assert api._broker_truth(_desk(_Rest())) is None


def test_a_broker_error_is_not_silently_papered_over(monkeypatch):
    _settings(monkeypatch, dry_run=False, creds=True)

    class Broken(_Rest):
        def get_account(self):
            return _Result(None, ok=False, error="503")

    assert api._broker_truth(_desk(Broken())) is None


def test_unusable_equity_field_returns_none(monkeypatch):
    _settings(monkeypatch, dry_run=False, creds=True)

    class NoEquity(_Rest):
        def get_account(self):
            return _Result({"cash": "1"})

    assert api._broker_truth(_desk(NoEquity())) is None


# -- the equity-curve basis check -----------------------------------------

def _rejects(base_value, equity_points, starting_equity=100_000.0):
    """Mirror of the guard in /api/equity-curve."""
    points = [{"equity": float(e)} for e in equity_points if e and float(e) > 0.0]
    reference = float(base_value or 0.0) or starting_equity
    if points and reference > 0:
        return min(p["equity"] for p in points) < reference * 0.5
    return False


def test_the_exact_series_that_rendered_133_percent_is_refused():
    """base_value 100000 with points [190, 444] is a gains series, not equity."""
    assert _rejects(100_000.0, [0.0] * 29 + [190.0, 444.0]) is True


def test_a_real_equity_series_is_kept():
    assert _rejects(100_000.0, [100_000.0, 100_405.60, 100_581.55]) is False


def test_a_genuine_50pct_drawdown_is_still_charted():
    """The guard must reject a wrong basis, not a bad day."""
    assert _rejects(100_000.0, [100_000.0, 74_000.0, 51_000.0]) is False
