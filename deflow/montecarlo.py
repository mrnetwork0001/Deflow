"""Monte Carlo stress testing for defined-risk option structures.

Two things this module is careful about:

* **Fat tails.** A pure geometric-Brownian simulation understates exactly the
  scenario that kills a short-premium book: an overnight gap. Paths here are
  Merton jump-diffusion -- GBM plus a compound-Poisson jump component -- so the
  reported CVaR reflects gap risk rather than a lognormal fantasy.

* **Reproducibility.** The generator is seeded per call. Re-running the auditor
  on the same proposal yields byte-identical numbers, which is what makes the
  audit ledger worth keeping.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Sequence

from .models import CONTRACT_MULTIPLIER, Leg, SpreadProposal

DEFAULT_PATHS = 1000

# Merton jump parameters calibrated to broad US equity index behaviour:
# roughly one jump per year, mean -3%, dispersion 6%. Single names get these
# scaled up by the caller.
JUMP_INTENSITY = 1.0
JUMP_MEAN = -0.03
JUMP_STDEV = 0.06


@dataclass
class StressResult:
    """Distribution of terminal P&L for one proposal."""

    paths: int
    mean_pnl: float
    median_pnl: float
    stdev_pnl: float
    prob_profit: float
    prob_max_loss: float
    p05: float           # 5th percentile outcome
    p95: float
    cvar_05: float       # mean of the worst 5% of paths
    worst: float
    best: float
    expected_value_ratio: float   # mean P&L / capital at risk

    def to_dict(self) -> Dict[str, float]:
        return {
            "paths": self.paths,
            "mean_pnl": round(self.mean_pnl, 2),
            "median_pnl": round(self.median_pnl, 2),
            "stdev_pnl": round(self.stdev_pnl, 2),
            "prob_profit": round(self.prob_profit, 4),
            "prob_max_loss": round(self.prob_max_loss, 4),
            "p05": round(self.p05, 2),
            "p95": round(self.p95, 2),
            "cvar_05": round(self.cvar_05, 2),
            "worst": round(self.worst, 2),
            "best": round(self.best, 2),
            "expected_value_ratio": round(self.expected_value_ratio, 4),
        }


def simulate_terminal_prices(
    spot: float,
    sigma: float,
    days: int,
    paths: int = DEFAULT_PATHS,
    drift: float = 0.0,
    seed: int = 20260904,
    jump_intensity: float = JUMP_INTENSITY,
    jump_mean: float = JUMP_MEAN,
    jump_stdev: float = JUMP_STDEV,
) -> List[float]:
    """Terminal underlying prices under Merton jump-diffusion.

    Simulated risk-neutral by default (`drift=0`): the auditor's job is to
    price the tail, not to express a view. The compensator term keeps the
    process a martingale once jumps are added, so adding fat tails does not
    quietly inject a directional edge.
    """
    if spot <= 0 or days <= 0 or sigma <= 0:
        return [spot] * paths

    rng = random.Random(seed)
    T = days / 365.0
    sqrt_T = math.sqrt(T)

    # Martingale compensator for the jump component.
    kappa = math.exp(jump_mean + 0.5 * jump_stdev**2) - 1.0
    diffusion_drift = (drift - jump_intensity * kappa - 0.5 * sigma**2) * T

    out: List[float] = []
    lam_T = jump_intensity * T
    for _ in range(paths):
        z = rng.gauss(0.0, 1.0)
        log_price = diffusion_drift + sigma * sqrt_T * z

        # Poisson count of jumps over the horizon (Knuth), then their sizes.
        n_jumps, p, target = 0, 1.0, math.exp(-lam_T)
        while p > target:
            p *= rng.random()
            n_jumps += 1
        n_jumps = max(n_jumps - 1, 0)
        for _ in range(n_jumps):
            log_price += rng.gauss(jump_mean, jump_stdev)

        out.append(spot * math.exp(log_price))
    return out


def payoff_at_expiry(legs: Sequence[Leg], terminal_price: float, contracts: int) -> float:
    """Gross value of the structure at expiry, in dollars."""
    total = 0.0
    for leg in legs:
        if leg.right == "call":
            intrinsic = max(terminal_price - leg.strike, 0.0)
        else:
            intrinsic = max(leg.strike - terminal_price, 0.0)
        total += leg.ratio * intrinsic
    return total * CONTRACT_MULTIPLIER * contracts


def stress_test(
    proposal: SpreadProposal,
    paths: int = DEFAULT_PATHS,
    seed: int = 20260904,
    vol_override: float | None = None,
) -> StressResult:
    """Run `paths` jump-diffusion scenarios and summarise terminal P&L.

    Uses the *short* leg's implied vol where the structure is a credit spread
    and the average otherwise: the tail that matters is the one priced into the
    contracts being sold.
    """
    if not proposal.legs:
        return StressResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    if vol_override is not None:
        sigma = vol_override
    elif proposal.strategy.is_credit:
        shorts = [l.implied_vol for l in proposal.legs if l.ratio < 0 and l.implied_vol > 0]
        sigma = sum(shorts) / len(shorts) if shorts else 0.20
    else:
        ivs = [l.implied_vol for l in proposal.legs if l.implied_vol > 0]
        sigma = sum(ivs) / len(ivs) if ivs else 0.20

    entry_cash = proposal.net_premium * CONTRACT_MULTIPLIER * proposal.contracts

    terminals = simulate_terminal_prices(
        proposal.underlying_price, sigma, proposal.dte, paths, seed=seed
    )
    # P&L = what the structure is worth at expiry, less what we paid for it
    # (a credit spread has negative entry_cash, so this adds the credit back).
    pnls = sorted(payoff_at_expiry(proposal.legs, s, proposal.contracts) - entry_cash for s in terminals)

    n = len(pnls)
    mean = sum(pnls) / n
    median = pnls[n // 2] if n % 2 else (pnls[n // 2 - 1] + pnls[n // 2]) / 2.0
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1) if n > 1 else 0.0

    tail_n = max(int(n * 0.05), 1)
    max_loss = proposal.max_loss

    return StressResult(
        paths=n,
        mean_pnl=mean,
        median_pnl=median,
        stdev_pnl=math.sqrt(variance),
        prob_profit=sum(1 for p in pnls if p > 0) / n,
        # "At max loss" means within a dollar of the structural floor.
        prob_max_loss=sum(1 for p in pnls if p <= -max_loss + 1.0) / n if max_loss > 0 else 0.0,
        p05=pnls[max(int(n * 0.05) - 1, 0)],
        p95=pnls[min(int(n * 0.95), n - 1)],
        cvar_05=sum(pnls[:tail_n]) / tail_n,
        worst=pnls[0],
        best=pnls[-1],
        expected_value_ratio=mean / max_loss if max_loss > 0 else 0.0,
    )


__all__ = ["StressResult", "DEFAULT_PATHS", "payoff_at_expiry", "simulate_terminal_prices", "stress_test"]
