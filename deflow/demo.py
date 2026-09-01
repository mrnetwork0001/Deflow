"""`python main.py --demo` — one cycle with the entire reasoning trace printed.

Built for the submission video and for anyone reading the repo who wants to see
*why* the desk did what it did, not just what it did. Each of the six stages is
printed with the numbers that drove it, including the stages that end in a
refusal -- which, for a risk-first system, are the interesting ones.
"""

from __future__ import annotations

import os
import sys
from typing import Any

C = {
    "g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "b": "\033[94m",
    "c": "\033[96m", "m": "\033[95m", "d": "\033[2m", "B": "\033[1m", "x": "\033[0m",
}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = dict.fromkeys(C, "")

W = 78


def rule(title: str = "", colour: str = "d") -> None:
    if title:
        pad = "─" * max(W - len(title) - 4, 0)
        print(f"{C[colour]}── {title} {pad}{C['x']}")
    else:
        print(f"{C['d']}{'─' * W}{C['x']}")


def stage(n: int, name: str, agent: str) -> None:
    print(f"\n  {C['B']}{C['b']}[{n}] {name}{C['x']}  {C['d']}{agent}{C['x']}")


def kv(label: str, value: str, colour: str = "x") -> None:
    print(f"      {C['d']}{label:<24}{C['x']} {C[colour]}{value}{C['x']}")


def run_demo(desk: Any) -> int:
    """Run one cycle, narrating every stage."""
    print()
    rule("DEFLOW · FULL REASONING TRACE", "c")
    status = desk.status()
    kv("mode", status["mode"].upper(), "g" if status["mode"] == "paper" else "y")
    kv("market data", "simulated" if status["simulated_market_data"] else "live Alpaca")
    kv("execution route", status["execution"]["route"])
    kv("reasoning", status["reasoning"]["model"])
    kv("risk gate",
       f"v{status['risk_envelope']['gate_version']} · 12 breakers · "
       f"${status['risk_envelope']['max_loss_per_trade']:,.0f} max loss/trade")

    report = desk.run_cycle()

    for outcome in report.outcomes:
        print()
        rule(f"{outcome.symbol}", "m")

        # --- Stage 1 ----------------------------------------------------
        view = outcome.view
        if not view:
            print(f"      {C['r']}{outcome.detail}{C['x']}")
            continue

        stage(1, "MACRO & VOLATILITY ANALYST", "regime classification")
        kv("price", f"${view['price']:,.2f}")
        kv("implied vol (30d)", f"{view['iv_30d']:.2%}")
        kv("realised vol (60d)", f"{view['hv_60d']:.2%}")
        vrp = view["variance_premium"]
        kv("variance risk premium", f"{vrp:+.2%}", "g" if vrp > 0.02 else "y")
        kv("IV rank", f"{view['iv_rank']:.0%}")
        kv("trend / RSI", f"{view['trend_score']:+.2f} / {view['rsi14']:.0f}")
        kv("regime", view["regime"])
        kv("stance → bias", f"{view['stance']} → {view['bias']}",
           "g" if view["tradeable"] else "d")
        for reason in view["reasons"]:
            print(f"      {C['d']}· {reason}{C['x']}")

        if outcome.stage == "analyst":
            print(f"\n      {C['y']}▸ NO TRADE{C['x']} — {outcome.detail}")
            continue

        # --- Stage 2 ----------------------------------------------------
        stage(2, "OPTIONS STRUCTURER", "defined-risk construction from live chain")
        if outcome.stage == "structurer":
            print(f"      {C['y']}▸ NO TRADE{C['x']} — {outcome.detail}")
            continue
        kv("candidates built", str(outcome.candidates))

        # --- Stage 3 ----------------------------------------------------
        choice = outcome.choice or {}
        stage(3, "REASONING LAYER", choice.get("model", "deterministic"))
        kv("engine", "Featherless AI" if choice.get("used_llm") else "deterministic ranker",
           "c" if choice.get("used_llm") else "d")
        kv("selected index", str(choice.get("index")))
        kv("confidence", f"{choice.get('confidence', 0):.0%}")
        if choice.get("error"):
            kv("fallback reason", choice["error"][:60], "y")
        print(f"      {C['d']}\"{choice.get('rationale', '')[:200]}\"{C['x']}")

        if outcome.stage == "reasoning":
            print(f"\n      {C['y']}▸ ABSTAINED{C['x']}")
            continue

        proposal = outcome.proposal or {}
        print(f"\n      {C['B']}proposed structure{C['x']}")
        kv("strategy", f"{proposal['strategy']} × {proposal['contracts']} contracts", "c")
        for leg in proposal["legs"]:
            arrow = f"{C['g']}BUY {C['x']}" if leg["ratio"] > 0 else f"{C['r']}SELL{C['x']}"
            print(f"        {arrow} {leg['symbol']}  "
                  f"{C['d']}{leg['right']} {leg['strike']:g} @ ${leg['price']:.2f} "
                  f"iv {leg['implied_vol']:.1%}{C['x']}")
        net = proposal["net_premium"]
        kv("net premium", f"${abs(net) * 100 * proposal['contracts']:,.2f} "
                          f"{'debit' if net > 0 else 'credit'}")
        kv("max loss / profit", f"${proposal['max_loss']:,.2f} / ${proposal['max_profit']:,.2f}")
        kv("breakeven(s)", ", ".join(f"${b:,.2f}" for b in proposal["breakevens"]))
        kv("P(profit)", f"{proposal['probability_of_profit']:.1%}")
        kv("net delta", f"{proposal['net_delta']:+.3f}")

        # --- Stage 4 ----------------------------------------------------
        audit = outcome.audit or {}
        stage(4, "ADVERSARIAL RISK AUDITOR", "independent Greeks + 1,000-path jump-diffusion")
        mc_p = audit.get("monte_carlo_physical", {})
        mc_q = audit.get("monte_carlo_risk_neutral", {})
        g = audit.get("greeks", {})
        kv("re-derived greeks",
           f"Δ {g.get('delta', 0):+.1f}  Γ {g.get('gamma', 0):+.3f}  "
           f"ν {g.get('vega', 0):+.1f}  Θ {g.get('theta', 0):+.2f}/day")
        kv("MC at implied vol",
           f"EV ${mc_q.get('mean_pnl', 0):+,.0f}  win {mc_q.get('prob_profit', 0):.0%}")
        kv("MC at realised vol",
           f"EV ${mc_p.get('mean_pnl', 0):+,.0f}  win {mc_p.get('prob_profit', 0):.0%}",
           "g" if mc_p.get("mean_pnl", 0) > 0 else "r")
        kv("variance edge", f"${audit.get('variance_edge_usd', 0):+,.0f}",
           "g" if audit.get("variance_edge_usd", 0) > 0 else "r")
        kv("CVaR (worst 5%)", f"${mc_p.get('cvar_05', 0):,.0f}", "y")
        kv("assignment risk", f"{audit.get('assignment_probability', 0):.0%}")
        for objection in audit.get("objections", []):
            colour = "r" if objection["severity"] == "fatal" else "y"
            print(f"      {C[colour]}⚠ {objection['severity'].upper()}{C['x']} "
                  f"{C['d']}{objection['message'][:150]}{C['x']}")
        if outcome.stage == "audit":
            print(f"\n      {C['r']}▸ VETOED BY AUDITOR{C['x']} — {outcome.detail}")
            continue

        # --- Stage 5 ----------------------------------------------------
        verdict = outcome.verdict or {}
        stage(5, "DETERMINISTIC RISK GATE", "zero-LLM · 12 circuit breakers")
        kv("evaluated in", f"{verdict.get('elapsed_us', 0):.2f} µs", "c")
        for breaker in verdict.get("breakers", []):
            mark = f"{C['g']}✓{C['x']}" if breaker["passed"] else f"{C['r']}✗{C['x']}"
            colour = "d" if breaker["passed"] else "r"
            print(f"      {mark} {C['d']}{breaker['id']:>2}{C['x']} "
                  f"{C[colour]}{breaker['name']:<28}{C['x']} "
                  f"{C['d']}{breaker['detail'][:70]}{C['x']}")
        if not verdict.get("approved", False):
            print(f"\n      {C['r']}{C['B']}▸ VETOED BY RISK GATE{C['x']} — {outcome.detail[:120]}")
            continue
        print(f"      {C['g']}{C['B']}▸ APPROVED{C['x']} — "
              f"{verdict.get('approved_contracts')} contracts authorised")

        # --- Stage 6 ----------------------------------------------------
        execution = outcome.execution or {}
        stage(6, "EXECUTION AGENT", f"route: {execution.get('route')}")
        if execution.get("simulated"):
            kv("note", "simulated fill — no Alpaca credentials configured", "y")
        if execution.get("dry_run"):
            kv("note", "dry run — request rendered, not submitted", "y")
        kv("limit price", f"${execution.get('limit_price', 0):+.2f} (net)")
        kv("client order id", execution.get("client_order_id", ""))
        kv("order id", execution.get("order_id", "") or "—")
        kv("submitted", str(execution.get("submitted")),
           "g" if execution.get("submitted") else "r")
        if execution.get("error"):
            kv("error", execution["error"][:80], "r")

    # --- Summary --------------------------------------------------------
    print()
    rule("CYCLE SUMMARY", "c")
    p = report.performance
    kv("symbols scanned", str(len(report.outcomes)))
    kv("orders routed", str(report.orders_submitted), "g")
    kv("vetoed", str(report.vetoed), "r" if report.vetoed else "d")
    kv("equity", f"${p['equity']:,.2f}")
    kv("total P&L", f"${p['total_pnl']:+,.2f} ({p['return_pct']:+.3f}%)",
       "g" if p["total_pnl"] >= 0 else "r")
    kv("capital at risk", f"${p['capital_at_risk']:,.2f} ({p['capital_at_risk_pct']:.2f}% of equity)")
    kv("book net delta", f"{p['net_delta']:+.3f}")

    chain = desk.ledger.verify()
    kv("ledger entries", str(len(desk.ledger)))
    kv("hash chain", "intact" if chain.valid else f"BROKEN at {chain.broken_at}",
       "g" if chain.valid else "r")
    kv("chain head", desk.ledger.head[:32] + "…")
    print()
    return 0


__all__ = ["run_demo"]
