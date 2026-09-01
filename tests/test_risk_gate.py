"""Adversarial tests for the deterministic risk gate.

The gate is the only thing standing between a hallucinating model and a
brokerage account, so these tests are written from the attacker's side: every
case is an attempt to get capital past a breaker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_gate import (  # noqa: E402
    MAX_DELTA_EXPOSURE,
    MAX_PORTFOLIO_RISK_PCT,
    MIN_PROBABILITY_OF_PROFIT,
    DeterministicRiskGate,
    PortfolioState,
    benchmark,
)

EQUITY = 100_000.0


def good_trade(**overrides):
    """A proposal that passes all twelve breakers, so each test perturbs one axis."""
    base = {
        "symbol": "SPY",
        "strategy": "bull_put_spread",
        "is_defined_risk_spread": True,
        "leg_count": 2,
        "contracts": 4,
        "max_loss": 1600.0,
        "max_profit": 400.0,
        "net_delta": 0.18,
        "net_vega": -12.0,
        "probability_of_profit": 0.78,
        "dte": 30,
    }
    base.update(overrides)
    return base


@pytest.fixture
def gate():
    return DeterministicRiskGate(EQUITY)


@pytest.fixture
def flat():
    return PortfolioState(equity=EQUITY)


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------

def test_well_formed_trade_is_approved(gate, flat):
    v = gate.evaluate_trade(good_trade(), flat)
    assert v.approved, v.reason
    assert v.passed_count == 12
    assert v.approved_contracts == 4


def test_verdict_unpacks_as_legacy_two_tuple(gate, flat):
    approved, reason = gate.evaluate_trade(good_trade(), flat)
    assert approved is True
    assert reason.startswith("APPROVED")


# --------------------------------------------------------------------------
# Breaker 1 -- structure
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"is_defined_risk_spread": False},
        {"strategy": "naked_call", "leg_count": 1},
        {"strategy": "short_strangle"},          # not on the allow-list
        {"leg_count": 1},                        # single leg cannot be covered
        {"strategy": ""},
    ],
    ids=["flag_false", "naked_call", "unlisted_strategy", "single_leg", "no_strategy"],
)
def test_undefined_risk_structures_are_vetoed(gate, flat, overrides):
    v = gate.evaluate_trade(good_trade(**overrides), flat)
    assert not v.approved
    assert any(b.id == 1 for b in v.failed)


def test_lying_about_defined_risk_still_caught_by_dollar_cap(gate, flat):
    """A model can set the flag, but it cannot make a $15k loss fit in $2k."""
    v = gate.evaluate_trade(
        good_trade(strategy="bull_put_spread", is_defined_risk_spread=True, max_loss=15_000.0), flat
    )
    assert not v.approved
    assert any(b.id == 2 for b in v.failed)


# --------------------------------------------------------------------------
# Breaker 2 -- per-trade loss cap
# --------------------------------------------------------------------------

def test_max_loss_at_exactly_the_cap_is_allowed(gate, flat):
    v = gate.evaluate_trade(good_trade(max_loss=EQUITY * MAX_PORTFOLIO_RISK_PCT, max_profit=600.0), flat)
    assert v.approved, v.reason


def test_one_cent_over_the_cap_is_vetoed(gate, flat):
    v = gate.evaluate_trade(good_trade(max_loss=EQUITY * MAX_PORTFOLIO_RISK_PCT + 0.01), flat)
    assert not v.approved
    assert v.failed[0].id == 2


def test_cap_scales_with_supplied_equity(gate):
    """The cap follows the live account, not the value the gate was built with."""
    small = PortfolioState(equity=25_000.0)
    v = gate.evaluate_trade(good_trade(max_loss=1_600.0), small)
    assert not v.approved  # 2% of 25k is 500
    assert any(b.id == 2 for b in v.failed)


# --------------------------------------------------------------------------
# Fail-closed behaviour on malformed input
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field", ["max_loss", "net_delta", "probability_of_profit", "dte"]
)
def test_missing_required_field_fails_closed(gate, flat, field):
    proposal = good_trade()
    del proposal[field]
    v = gate.evaluate_trade(proposal, flat)
    assert not v.approved, f"omitting {field} must not produce an approval"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_max_loss_is_vetoed(gate, flat, bad):
    v = gate.evaluate_trade(good_trade(max_loss=bad), flat)
    assert not v.approved


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_delta_is_vetoed(gate, flat, bad):
    v = gate.evaluate_trade(good_trade(net_delta=bad), flat)
    assert not v.approved


@pytest.mark.parametrize("bad", ["", "abc", None, [], {}])
def test_garbage_typed_max_loss_is_vetoed(gate, flat, bad):
    v = gate.evaluate_trade(good_trade(max_loss=bad), flat)
    assert not v.approved


def test_completely_empty_proposal_is_vetoed(gate, flat):
    v = gate.evaluate_trade({}, flat)
    assert not v.approved
    assert v.passed_count < 12


# --------------------------------------------------------------------------
# Breaker 3 / 7 -- delta
# --------------------------------------------------------------------------

def test_delta_bound_is_two_sided(gate, flat):
    assert not gate.evaluate_trade(good_trade(net_delta=0.40), flat).approved
    assert not gate.evaluate_trade(good_trade(net_delta=-0.40), flat).approved
    assert gate.evaluate_trade(good_trade(net_delta=-MAX_DELTA_EXPOSURE), flat).approved


def test_portfolio_delta_accumulates(gate):
    """A trade that is fine alone is refused once the book is already long."""
    loaded = PortfolioState(equity=EQUITY, net_delta=1.10)
    v = gate.evaluate_trade(good_trade(net_delta=0.30), loaded)
    assert not v.approved
    assert any(b.id == 7 for b in v.failed)


def test_opposing_delta_is_welcomed_by_breaker_7(gate):
    """A hedge that reduces book delta must not be blocked by breaker 7."""
    loaded = PortfolioState(equity=EQUITY, net_delta=1.10)
    v = gate.evaluate_trade(good_trade(net_delta=-0.30, strategy="bear_call_spread"), loaded)
    assert not any(b.id == 7 for b in v.failed), v.reason


# --------------------------------------------------------------------------
# Breaker 4 -- probability of profit
# --------------------------------------------------------------------------

def test_low_probability_of_profit_is_vetoed(gate, flat):
    v = gate.evaluate_trade(good_trade(probability_of_profit=MIN_PROBABILITY_OF_PROFIT - 0.001), flat)
    assert not v.approved
    assert any(b.id == 4 for b in v.failed)


# --------------------------------------------------------------------------
# Breaker 5 / 6 -- portfolio and concentration limits
# --------------------------------------------------------------------------

def test_aggregate_risk_ceiling(gate):
    loaded = PortfolioState(equity=EQUITY, total_capital_at_risk=5_000.0)
    v = gate.evaluate_trade(good_trade(symbol="QQQ", max_loss=1_600.0), loaded)
    assert not v.approved
    assert any(b.id == 5 for b in v.failed)


def test_symbol_concentration_ceiling(gate):
    loaded = PortfolioState(equity=EQUITY, risk_by_symbol={"SPY": 2_000.0})
    v = gate.evaluate_trade(good_trade(symbol="SPY", max_loss=1_600.0), loaded)
    assert not v.approved
    assert any(b.id == 6 for b in v.failed)


def test_concentration_is_per_symbol_not_global(gate):
    """Risk parked in SPY must not block an otherwise-fine QQQ trade."""
    loaded = PortfolioState(equity=EQUITY, risk_by_symbol={"SPY": 2_900.0}, total_capital_at_risk=2_900.0)
    v = gate.evaluate_trade(good_trade(symbol="QQQ", max_loss=1_600.0), loaded)
    assert v.approved, v.reason


def test_symbol_matching_is_case_insensitive(gate):
    loaded = PortfolioState(equity=EQUITY, risk_by_symbol={"SPY": 2_900.0})
    v = gate.evaluate_trade(good_trade(symbol="spy", max_loss=1_600.0), loaded)
    assert not v.approved
    assert any(b.id == 6 for b in v.failed)


# --------------------------------------------------------------------------
# Breaker 8 / 9 / 10 / 11 / 12
# --------------------------------------------------------------------------

def test_position_count_ceiling(gate):
    full = PortfolioState(equity=EQUITY, open_positions=6)
    assert not gate.evaluate_trade(good_trade(), full).approved


@pytest.mark.parametrize("dte", [0, 1, 6, 61, 120, -5])
def test_dte_outside_window_is_vetoed(gate, flat, dte):
    v = gate.evaluate_trade(good_trade(dte=dte), flat)
    assert not v.approved
    assert any(b.id == 9 for b in v.failed)


@pytest.mark.parametrize("dte", [7, 30, 60])
def test_dte_inside_window_is_allowed(gate, flat, dte):
    assert gate.evaluate_trade(good_trade(dte=dte), flat).approved


def test_thin_credit_relative_to_width_is_vetoed(gate, flat):
    """$50 of credit on a $2,000-wide condor is not worth the tail."""
    v = gate.evaluate_trade(
        good_trade(strategy="iron_condor", leg_count=4, max_profit=50.0, max_loss=1_950.0), flat
    )
    assert not v.approved
    assert any(b.id == 10 for b in v.failed)


def test_poor_reward_risk_debit_spread_is_vetoed(gate, flat):
    v = gate.evaluate_trade(
        good_trade(strategy="bull_call_spread", max_loss=1_600.0, max_profit=400.0), flat
    )
    assert not v.approved
    assert any(b.id == 10 for b in v.failed)


def test_daily_drawdown_killswitch_halts_new_risk(gate):
    hit = PortfolioState(equity=96_500.0, start_of_day_equity=100_000.0, day_pnl=-3_500.0)
    v = gate.evaluate_trade(good_trade(), hit)
    assert not v.approved
    assert any(b.id == 11 for b in v.failed)


def test_vega_ceiling(gate):
    loaded = PortfolioState(equity=EQUITY, net_vega=-240.0)
    v = gate.evaluate_trade(good_trade(net_vega=-30.0), loaded)
    assert not v.approved
    assert any(b.id == 12 for b in v.failed)


# --------------------------------------------------------------------------
# Position sizing
# --------------------------------------------------------------------------

def test_max_contracts_respects_the_tightest_limit(gate, flat):
    # $400 of risk per contract, 2% cap = $2,000 -> 5 contracts.
    assert gate.max_contracts(400.0, flat, "SPY") == 5


def test_max_contracts_shrinks_as_the_book_fills(gate):
    loaded = PortfolioState(equity=EQUITY, total_capital_at_risk=5_000.0)
    assert gate.max_contracts(400.0, loaded, "SPY") == 2  # $1,000 aggregate headroom


def test_max_contracts_returns_zero_when_no_room(gate):
    full = PortfolioState(equity=EQUITY, total_capital_at_risk=6_000.0)
    assert gate.max_contracts(400.0, full, "SPY") == 0


def test_max_contracts_rejects_nonpositive_risk(gate, flat):
    assert gate.max_contracts(0.0, flat) == 0
    assert gate.max_contracts(-100.0, flat) == 0


def test_sized_position_always_passes_its_own_dollar_caps(gate, flat):
    """Whatever the sizer returns must survive the gate it was sized against."""
    per_contract = 337.0
    n = gate.max_contracts(per_contract, flat, "SPY")
    v = gate.evaluate_trade(
        good_trade(contracts=n, max_loss=per_contract * n, max_profit=per_contract * n * 0.4), flat
    )
    assert not any(b.id in (2, 5, 6) for b in v.failed), v.reason


# --------------------------------------------------------------------------
# Exit guard
# --------------------------------------------------------------------------

def test_stop_loss_fires_at_half_of_max_loss():
    g = DeterministicRiskGate(EQUITY)
    close, why = g.evaluate_exit(unrealized_pnl=-1_000.0, max_loss=2_000.0, max_profit=500.0, dte=20)
    assert close and "STOP LOSS" in why


def test_profit_target_fires_at_three_quarters():
    g = DeterministicRiskGate(EQUITY)
    close, why = g.evaluate_exit(unrealized_pnl=375.0, max_loss=2_000.0, max_profit=500.0, dte=20)
    assert close and "PROFIT TARGET" in why


def test_expiry_guard_forces_a_close():
    g = DeterministicRiskGate(EQUITY)
    close, why = g.evaluate_exit(unrealized_pnl=10.0, max_loss=2_000.0, max_profit=500.0, dte=2)
    assert close and "EXPIRY GUARD" in why


def test_position_inside_all_bands_is_held():
    g = DeterministicRiskGate(EQUITY)
    close, _ = g.evaluate_exit(unrealized_pnl=100.0, max_loss=2_000.0, max_profit=500.0, dte=20)
    assert not close


def test_stop_loss_takes_precedence_over_expiry():
    """A blown-through stop must report as a stop, not as a routine roll-off."""
    g = DeterministicRiskGate(EQUITY)
    close, why = g.evaluate_exit(unrealized_pnl=-1_900.0, max_loss=2_000.0, max_profit=500.0, dte=1)
    assert close and "STOP LOSS" in why


# --------------------------------------------------------------------------
# Determinism, auditability, performance
# --------------------------------------------------------------------------

def test_identical_input_yields_identical_verdict(gate, flat):
    """The whole premise: no randomness, no state leakage between calls."""
    p = good_trade(max_loss=2_500.0)
    first = gate.evaluate_trade(p, flat)
    for _ in range(200):
        again = gate.evaluate_trade(p, flat)
        assert again.approved == first.approved
        assert again.reason == first.reason


def test_gate_never_mutates_the_proposal(gate, flat):
    p = good_trade()
    before = dict(p)
    gate.evaluate_trade(p, flat)
    assert p == before


def test_every_breaker_is_recorded_even_when_one_fails(gate, flat):
    """No short-circuit: the audit log must show all twelve results."""
    v = gate.evaluate_trade(good_trade(max_loss=99_000.0, dte=0, net_delta=5.0), flat)
    assert len(v.records) == 12
    assert len(v.breakers) == 12
    assert len(v.failed) >= 3


def test_breaker_details_render(gate, flat):
    v = gate.evaluate_trade(good_trade(max_loss=99_000.0), flat)
    for b in v.breakers:
        assert isinstance(b.detail, str) and b.detail
    assert "$99,000.00" in next(b.detail for b in v.failed if b.id == 2)


def test_verdict_serialises_for_the_audit_log(gate, flat):
    import json

    d = gate.evaluate_trade(good_trade(), flat).to_dict()
    assert json.loads(json.dumps(d))["breakers_total"] == 12


def test_gate_counts_its_own_decisions(flat):
    g = DeterministicRiskGate(EQUITY)
    g.evaluate_trade(good_trade(), flat)
    g.evaluate_trade(good_trade(max_loss=99_000.0), flat)
    assert g.evaluations == 2 and g.vetoes == 1


def test_latency_stays_in_the_microsecond_budget():
    """The gate must stay cheap enough that bypassing it is never a temptation."""
    stats = benchmark(20_000)
    assert stats["mean_us"] < 15.0, f"risk gate regressed to {stats['mean_us']:.2f} us"


def test_constructor_rejects_nonpositive_equity():
    with pytest.raises(ValueError):
        DeterministicRiskGate(0.0)
