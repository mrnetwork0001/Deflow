#!/usr/bin/env python3
"""Fill the results post from the actual ledger. Never hand-write these numbers.

Reads the live desk state (or the persisted ledger and position file if the API
is not running) and renders Post 4 from SOCIAL_ENGAGEMENT_POSTS.md with real
figures. If the run was simulated it says so, prominently, in the rendered post
-- a simulated result posted as a live one is exactly the failure this project
exists to prevent.

    python scripts/social_post.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deflow.config import SETTINGS  # noqa: E402
from deflow.ledger import DecisionLedger  # noqa: E402
from risk_gate import benchmark  # noqa: E402

TEMPLATE = """DEFLOW live on a fresh $100,000 @AlpacaHQ paper account.

Every one of these numbers comes from a SHA-256 hash-chained decision ledger.
Change any historical entry and the chain breaks — /api/ledger/verify tells you
exactly where.

📊 Equity: {equity}
📈 P&L: {total_pnl} ({return_pct})
🎯 Closed: {closed} trades · {win_rate} win rate · profit factor {profit_factor}
🛡️ {vetoes} trades vetoed by the deterministic risk gate
⚡ Gate latency: {gate_us} µs per 12-breaker evaluation
📓 {ledger_entries} decisions logged · chain {chain_status}

100% defined-risk spreads. Max 2% of equity at risk per trade.

@lablabai #AlgoTrading #Alpaca #AITrading"""


def load_performance() -> tuple[dict, bool]:
    """Prefer the running API; fall back to the persisted position file."""
    try:
        import httpx

        base = f"http://{SETTINGS.api_host}:{SETTINGS.api_port}"
        status = httpx.get(f"{base}/api/status", timeout=5).json()
        return status["performance"], status["mode"] != "paper"
    except Exception:
        pass

    path = ROOT / "data" / "positions.json"
    if not path.exists():
        print("No data yet. Run `python main.py --once` first.", file=sys.stderr)
        raise SystemExit(1)

    saved = json.loads(path.read_text())
    closed = saved.get("closed", [])
    wins = [c for c in closed if c.get("realized_pnl", 0) > 0]
    losses = [c for c in closed if c.get("realized_pnl", 0) <= 0]
    gross_win = sum(c["realized_pnl"] for c in wins)
    gross_loss = abs(sum(c["realized_pnl"] for c in losses))
    start = saved.get("starting_equity", 100_000.0)
    unrealized = sum(p.get("unrealized_pnl", 0) for p in saved.get("open", []))
    equity = start + saved.get("cash_pnl", 0.0) + unrealized
    simulated = any(p.get("simulated") for p in saved.get("open", []) + closed)

    return {
        "equity": equity,
        "starting_equity": start,
        "total_pnl": equity - start,
        "return_pct": (equity / start - 1) * 100 if start else 0.0,
        "closed_positions": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
    }, simulated


def main() -> int:
    performance, data_looks_simulated = load_performance()
    # The authoritative signal is whether Alpaca credentials exist at all, not
    # whether some persisted record happens to carry a flag. A safety check
    # that depends on the shape of its input is not a safety check: an empty
    # position list, an older file, or a renamed field would all silently
    # report a simulated run as live.
    simulated = data_looks_simulated or not SETTINGS.has_alpaca_credentials
    ledger = DecisionLedger()
    chain = ledger.verify()
    vetoes = sum(
        1 for r in ledger.read()
        if r.get("event") == "risk_gate" and not r.get("payload", {}).get("approved", True)
    )
    latency = benchmark(20_000)["mean_us"]

    post = TEMPLATE.format(
        equity=f"${performance['equity']:,.2f}",
        total_pnl=f"{'+' if performance['total_pnl'] >= 0 else '−'}${abs(performance['total_pnl']):,.2f}",
        return_pct=f"{performance['return_pct']:+.2f}%",
        closed=performance["closed_positions"],
        win_rate=f"{performance['win_rate'] * 100:.0f}%",
        profit_factor=(
            f"{performance['profit_factor']:.2f}"
            if performance["profit_factor"] is not None
            else "n/a (no losing trades yet)"
        ),
        vetoes=vetoes,
        gate_us=f"{latency:.2f}",
        ledger_entries=len(ledger),
        chain_status="intact ✅" if chain.valid else f"BROKEN at {chain.broken_at} ❌",
    )

    print("=" * 72)
    if simulated:
        print("  ⚠️  THIS RUN WAS SIMULATED — NO ALPACA CREDENTIALS CONFIGURED.")
        print("  ⚠️  DO NOT POST THESE AS LIVE TRADING RESULTS.")
        print("  ⚠️  Set ALPACA_API_KEY / ALPACA_SECRET_KEY and let the desk trade a")
        print("  ⚠️  real paper account before publishing anything from this file.")
    else:
        print("  Live Alpaca paper account. Safe to post.")
    print("=" * 72)
    print()
    print(post)
    print()
    if performance["closed_positions"] == 0:
        print("Note: no closed trades yet — the win-rate and profit-factor lines are", file=sys.stderr)
        print("not meaningful. Let the desk run before posting.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
