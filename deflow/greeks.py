"""Black-Scholes-Merton pricing, Greeks, and an implied-volatility solver.

Pure standard library on purpose: the Greeks feed the deterministic risk gate,
so they must be computable in any environment where risk_gate.py imports, with
no third-party numerical stack in the path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

OptionRight = Literal["call", "put"]

# Trading days, not calendar days -- theta is quoted per calendar day but the
# variance clock that matters for US equity options runs on sessions.
TRADING_DAYS = 252.0
CALENDAR_DAYS = 365.0

SQRT_2PI = math.sqrt(2.0 * math.pi)


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    """Standard normal CDF via the libm error function (full double precision)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class Greeks:
    """Per-contract Greeks. Delta/gamma are per 1 share of underlying."""

    price: float
    delta: float
    gamma: float
    vega: float          # per 1 volatility point (0.01), per share
    theta: float         # per calendar day, per share
    rho: float

    def scaled(self, quantity: float, multiplier: float = 100.0) -> Greeks:
        """Scale to a position: `quantity` contracts of `multiplier` shares each."""
        k = quantity * multiplier
        return Greeks(
            price=self.price * k,
            delta=self.delta * k,
            gamma=self.gamma * k,
            vega=self.vega * k,
            theta=self.theta * k,
            rho=self.rho * k,
        )


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    vol_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def black_scholes(
    S: float,
    K: float,
    T: float,
    sigma: float,
    right: OptionRight,
    r: float = 0.045,
    q: float = 0.0,
) -> Greeks:
    """Price and Greeks for one European option contract (per share).

    S: spot, K: strike, T: years to expiry, sigma: annualised vol,
    r: risk-free rate, q: continuous dividend yield.

    Degenerate inputs (T<=0 or sigma<=0) collapse to intrinsic value with a
    step-function delta rather than raising -- the risk gate must always get a
    number it can reason about, even for an expiring contract.
    """
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        if right == "call":
            intrinsic = max(S - K, 0.0)
            delta = 1.0 if S > K else 0.0
        else:
            intrinsic = max(K - S, 0.0)
            delta = -1.0 if S < K else 0.0
        return Greeks(price=intrinsic, delta=delta, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    sqrt_t = math.sqrt(T)
    pdf_d1 = norm_pdf(d1)

    gamma = disc_q * pdf_d1 / (S * sigma * sqrt_t)
    # Vega is reported per 1 vol point (1% = 0.01) to match how desks quote it.
    vega = S * disc_q * pdf_d1 * sqrt_t / 100.0

    if right == "call":
        price = S * disc_q * norm_cdf(d1) - K * disc_r * norm_cdf(d2)
        delta = disc_q * norm_cdf(d1)
        theta_annual = (
            -(S * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
            - r * K * disc_r * norm_cdf(d2)
            + q * S * disc_q * norm_cdf(d1)
        )
        rho = K * T * disc_r * norm_cdf(d2) / 100.0
    else:
        price = K * disc_r * norm_cdf(-d2) - S * disc_q * norm_cdf(-d1)
        delta = -disc_q * norm_cdf(-d1)
        theta_annual = (
            -(S * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
            + r * K * disc_r * norm_cdf(-d2)
            - q * S * disc_q * norm_cdf(-d1)
        )
        rho = -K * T * disc_r * norm_cdf(-d2) / 100.0

    return Greeks(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta_annual / CALENDAR_DAYS,
        rho=rho,
    )


def implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    right: OptionRight,
    r: float = 0.045,
    q: float = 0.0,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """Recover sigma from a market premium.

    Newton-Raphson with a bisection guard: Newton is fast but unstable for deep
    ITM/OTM contracts where vega collapses, so any step that leaves the bracket
    falls back to bisection. Returns 0.0 when the price is below intrinsic
    (an unmatchable quote), which the structurer treats as "no usable market".
    """
    if T <= 0.0 or market_price <= 0.0 or S <= 0.0 or K <= 0.0:
        return 0.0

    # No-arbitrage lower bound for a European option. Note this is NOT
    # `(S - K) * exp(-rT)`: only the strike is discounted, because the stock
    # leg is held spot. Using the discounted-intrinsic form instead rejects
    # legitimately priced deep in-the-money puts -- their true floor,
    # `K*exp(-rT) - S`, sits *below* `(K - S)*exp(-rT)` whenever rates are
    # positive, so real quotes land underneath the wrong bound and the solver
    # reports "no market" for a perfectly tradable contract.
    discount = math.exp(-r * T)
    floor = max(S - K * discount, 0.0) if right == "call" else max(K * discount - S, 0.0)
    if market_price < floor - tol:
        return 0.0

    sigma = 0.25  # a sane equity-index starting guess
    low, high = lo, hi

    for _ in range(max_iter):
        g = black_scholes(S, K, T, sigma, right, r, q)
        diff = g.price - market_price
        if abs(diff) < tol:
            return sigma
        # Keep the bracket tight even while running Newton.
        if diff > 0:
            high = sigma
        else:
            low = sigma
        vega_per_unit = g.vega * 100.0  # back to per-1.0-vol for Newton's step
        if vega_per_unit > 1e-8:
            step = sigma - diff / vega_per_unit
            if low < step < high:
                sigma = step
                continue
        sigma = 0.5 * (low + high)
        if high - low < tol:
            break

    return sigma


def years_to_expiry(days: float) -> float:
    """Calendar days -> year fraction used by the pricer."""
    return max(days, 0.0) / CALENDAR_DAYS


def probability_itm(S: float, K: float, T: float, sigma: float, right: OptionRight, r: float = 0.045) -> float:
    """Risk-neutral P(finish ITM) = N(d2) for calls, N(-d2) for puts."""
    if T <= 0.0 or sigma <= 0.0:
        return 1.0 if ((right == "call" and S > K) or (right == "put" and S < K)) else 0.0
    _, d2 = _d1_d2(S, K, T, r, 0.0, sigma)
    return norm_cdf(d2) if right == "call" else norm_cdf(-d2)


__all__ = [
    "Greeks",
    "OptionRight",
    "black_scholes",
    "implied_vol",
    "norm_cdf",
    "norm_pdf",
    "probability_itm",
    "years_to_expiry",
    "TRADING_DAYS",
    "CALENDAR_DAYS",
]
