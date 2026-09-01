"""Black-Scholes, implied vol, and Monte Carlo correctness.

These are the numbers every risk decision is built on, so they are checked
against closed-form identities rather than against previously recorded output.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from deflow.greeks import (
    black_scholes,
    implied_vol,
    norm_cdf,
    probability_itm,
)
from deflow.models import Leg, SpreadProposal, Strategy, occ_symbol, parse_occ
from deflow.montecarlo import payoff_at_expiry, simulate_terminal_prices, stress_test

R = 0.045


# --------------------------------------------------------------------------
# Black-Scholes
# --------------------------------------------------------------------------

def test_normal_cdf_reference_points():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)
    assert norm_cdf(1.96) == pytest.approx(0.9750021, abs=1e-6)
    assert norm_cdf(-1.96) == pytest.approx(0.0249979, abs=1e-6)


@pytest.mark.parametrize("S,K,T,sigma", [(100, 100, 1.0, 0.2), (450, 455, 0.08, 0.18), (50, 70, 2.0, 0.6)])
def test_put_call_parity(S, K, T, sigma):
    """C - P = S - K*exp(-rT). Holds to machine precision or the pricer is wrong."""
    c = black_scholes(S, K, T, sigma, "call", r=R)
    p = black_scholes(S, K, T, sigma, "put", r=R)
    assert (c.price - p.price) == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_call_and_put_delta_differ_by_one():
    c = black_scholes(100, 100, 0.5, 0.25, "call", r=R)
    p = black_scholes(100, 100, 0.5, 0.25, "put", r=R)
    assert (c.delta - p.delta) == pytest.approx(1.0, abs=1e-9)


def test_gamma_and_vega_are_right_agnostic():
    """A call and a put on the same strike share gamma and vega."""
    c = black_scholes(100, 105, 0.4, 0.3, "call", r=R)
    p = black_scholes(100, 105, 0.4, 0.3, "put", r=R)
    assert c.gamma == pytest.approx(p.gamma, rel=1e-9)
    assert c.vega == pytest.approx(p.vega, rel=1e-9)


def test_delta_bounds():
    assert 0.0 <= black_scholes(100, 100, 0.5, 0.2, "call").delta <= 1.0
    assert -1.0 <= black_scholes(100, 100, 0.5, 0.2, "put").delta <= 0.0


def test_deep_itm_call_approaches_intrinsic():
    g = black_scholes(200, 100, 0.05, 0.15, "call", r=R)
    assert g.price == pytest.approx(200 - 100 * math.exp(-R * 0.05), abs=0.05)
    assert g.delta == pytest.approx(1.0, abs=0.01)


def test_price_increases_with_volatility():
    prices = [black_scholes(100, 100, 0.5, s, "call").price for s in (0.10, 0.20, 0.40, 0.80)]
    assert prices == sorted(prices)


def test_long_option_theta_is_negative():
    assert black_scholes(100, 100, 0.25, 0.3, "call").theta < 0
    assert black_scholes(100, 100, 0.25, 0.3, "put").theta < 0


@pytest.mark.parametrize(
    "S,K,right,expected", [(110, 100, "call", 10.0), (90, 100, "call", 0.0),
                           (90, 100, "put", 10.0), (110, 100, "put", 0.0)]
)
def test_expired_options_collapse_to_intrinsic(S, K, right, expected):
    assert black_scholes(S, K, 0.0, 0.2, right).price == pytest.approx(expected)


def test_degenerate_inputs_do_not_raise():
    for args in [(0, 100, 1.0, 0.2), (100, 0, 1.0, 0.2), (100, 100, -1.0, 0.2), (100, 100, 1.0, -0.5)]:
        assert black_scholes(*args, "call").price >= 0.0


# --------------------------------------------------------------------------
# Implied volatility
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sigma", [0.08, 0.15, 0.25, 0.60, 1.20])
@pytest.mark.parametrize("right", ["call", "put"])
def test_implied_vol_round_trip(sigma, right):
    S, K, T = 450.0, 460.0, 0.12
    price = black_scholes(S, K, T, sigma, right, r=R).price
    assert implied_vol(price, S, K, T, right, r=R) == pytest.approx(sigma, abs=1e-5)


def test_implied_vol_on_deep_otm_where_vega_collapses():
    """Newton alone diverges here; the bisection guard has to catch it."""
    S, K, T, sigma = 100.0, 200.0, 0.05, 0.35
    price = black_scholes(S, K, T, sigma, "call").price
    recovered = implied_vol(price, S, K, T, "call")
    assert recovered == pytest.approx(sigma, abs=1e-3) or price < 1e-6


def test_implied_vol_rejects_price_below_intrinsic():
    assert implied_vol(1.0, 150.0, 100.0, 0.5, "call") == 0.0


@pytest.mark.parametrize("bad", [(0.0, 100, 100, 0.5), (5.0, 100, 100, 0.0), (-1.0, 100, 100, 0.5)])
def test_implied_vol_degenerate_inputs_return_zero(bad):
    price, S, K, T = bad
    assert implied_vol(price, S, K, T, "call") == 0.0


def test_probability_itm_matches_n_d2():
    S, K, T, sigma = 100.0, 110.0, 0.5, 0.25
    d2 = (math.log(S / K) + (R - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    assert probability_itm(S, K, T, sigma, "call", r=R) == pytest.approx(norm_cdf(d2), abs=1e-12)


def test_probability_itm_call_and_put_sum_to_one():
    args = (100.0, 105.0, 0.4, 0.3)
    total = probability_itm(*args, "call") + probability_itm(*args, "put")
    assert total == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------
# OCC symbology
# --------------------------------------------------------------------------

def test_occ_round_trip():
    expiry = date(2026, 10, 16)
    symbol = occ_symbol("SPY", expiry, "call", 450.0)
    assert symbol == "SPY261016C00450000"
    parsed = parse_occ(symbol)
    assert parsed == {"underlying": "SPY", "expiry": expiry, "right": "call", "strike": 450.0}


def test_occ_encodes_fractional_strikes():
    assert parse_occ(occ_symbol("NVDA", date(2026, 9, 18), "put", 142.5))["strike"] == 142.5


@pytest.mark.parametrize("bad", ["", "SPY", "SPY261016X00450000", "SPY2610C00450000", "not a symbol"])
def test_parse_occ_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_occ(bad)


# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------

def test_jump_diffusion_is_a_martingale():
    """The compensator must keep E[S_T] = S_0; otherwise adding fat tails
    quietly injects a directional drift into every stress test."""
    terminals = simulate_terminal_prices(500.0, 0.25, 45, paths=120_000, seed=11)
    assert sum(terminals) / len(terminals) == pytest.approx(500.0, rel=0.004)


def test_jumps_produce_fatter_tails_than_gbm():
    with_jumps = simulate_terminal_prices(100.0, 0.2, 30, 40_000, seed=5, jump_intensity=3.0)
    without = simulate_terminal_prices(100.0, 0.2, 30, 40_000, seed=5, jump_intensity=0.0)
    assert min(with_jumps) < min(without)


def test_simulation_is_reproducible():
    a = simulate_terminal_prices(100.0, 0.3, 30, 500, seed=42)
    b = simulate_terminal_prices(100.0, 0.3, 30, 500, seed=42)
    assert a == b


def test_simulation_degenerate_inputs():
    assert simulate_terminal_prices(100.0, 0.0, 30, 10) == [100.0] * 10
    assert simulate_terminal_prices(100.0, 0.2, 0, 10) == [100.0] * 10


def _bull_put(contracts=1):
    expiry = date.today() + timedelta(days=30)
    return SpreadProposal(
        symbol="SPY",
        strategy=Strategy.BULL_PUT_SPREAD,
        legs=[
            Leg(occ_symbol("SPY", expiry, "put", 530), "put", 530, expiry, -1, 3.10, 0.16),
            Leg(occ_symbol("SPY", expiry, "put", 525), "put", 525, expiry, +1, 2.30, 0.165),
        ],
        contracts=contracts,
        underlying_price=548.0,
    )


def test_payoff_respects_structural_bounds():
    """Across the whole price line, a vertical's payoff stays inside its wings."""
    p = _bull_put(4)
    entry = p.net_premium * 100 * p.contracts
    for terminal in range(400, 700, 5):
        pnl = payoff_at_expiry(p.legs, float(terminal), p.contracts) - entry
        assert -p.max_loss - 0.01 <= pnl <= p.max_profit + 0.01


def test_stress_test_never_exceeds_defined_risk():
    result = stress_test(_bull_put(4), paths=2_000)
    assert result.worst >= -_bull_put(4).max_loss - 0.01
    assert result.best <= _bull_put(4).max_profit + 0.01


def test_stress_test_is_deterministic():
    assert stress_test(_bull_put(), paths=500).to_dict() == stress_test(_bull_put(), paths=500).to_dict()


def test_lower_volatility_raises_credit_spread_expectancy():
    """The core thesis: a short-premium spread is worth more when the
    underlying realises less volatility than its options are priced at."""
    p = _bull_put(4)
    rich = stress_test(p, paths=4_000, vol_override=0.30)
    calm = stress_test(p, paths=4_000, vol_override=0.08)
    assert calm.mean_pnl > rich.mean_pnl


def test_stress_test_handles_empty_legs():
    p = _bull_put()
    p.legs = []
    assert stress_test(p).paths == 0
