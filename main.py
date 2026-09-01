#!/usr/bin/env python3
"""
Deflow — Autonomous Multi-Agent Options Desk on Alpaca
======================================================

One command, from a bare clone:

    python main.py

That call bootstraps a virtual environment, installs dependencies, starts the
FastAPI backend, and runs the four-agent trading loop against Alpaca paper
trading. With no credentials configured it runs the identical pipeline against
a seeded simulated market, so the system is inspectable before anyone hands it
an API key -- every simulated figure is labelled as such, everywhere it appears.

Other entry points:

    python main.py --once        run a single cycle, print the report, exit
    python main.py --no-serve    trade on the schedule without the web API
    python main.py --check       environment and integration diagnostics
    python main.py --dry-run     full pipeline, orders rendered but not sent
    python main.py --demo        one cycle with the full reasoning trace printed
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"

# Import names, not distribution names -- checked before any dependency is used.
REQUIRED_MODULES = ("fastapi", "uvicorn", "httpx")


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _dependencies_present() -> bool:
    from importlib.util import find_spec

    return all(find_spec(m) is not None for m in REQUIRED_MODULES)


def bootstrap() -> None:
    """Create .venv, install requirements, and re-exec inside it.

    Runs only when dependencies are actually missing, so a correctly
    provisioned environment (CI, Docker, an active venv) is never disturbed.
    Set DEFLOW_NO_BOOTSTRAP=1 to disable entirely.
    """
    if _dependencies_present() or os.environ.get("DEFLOW_NO_BOOTSTRAP"):
        return

    venv_python = _venv_python()
    if _in_venv() and not venv_python.exists():
        # Already inside someone else's venv that lacks our deps. Installing
        # into it silently would be rude; say what to run instead.
        print("Deflow: dependencies missing in the active environment. Run:")
        print(f"    {sys.executable} -m pip install -r {REQUIREMENTS}")
        sys.exit(1)

    if not venv_python.exists():
        print("Deflow: creating .venv …")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)

    print("Deflow: installing dependencies …")
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=False
    )
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)], check=False
    )
    if result.returncode != 0:
        print("Deflow: dependency installation failed. Install manually:")
        print(f"    {venv_python} -m pip install -r {REQUIREMENTS}")
        sys.exit(1)

    print("Deflow: restarting inside .venv …\n")
    os.execv(str(venv_python), [str(venv_python), str(ROOT / "main.py"), *sys.argv[1:]])


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

C = {
    "g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "b": "\033[94m",
    "c": "\033[96m", "d": "\033[2m", "B": "\033[1m", "x": "\033[0m",
}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = dict.fromkeys(C, "")


def banner(settings) -> None:
    live = settings.mode == "paper"
    print(f"{C['g']}{C['B']}")
    print("  ██████  ███████ ███████ ██       ██████  ██     ██")
    print("  ██   ██ ██      ██      ██      ██    ██ ██     ██")
    print("  ██   ██ █████   █████   ██      ██    ██ ██  █  ██")
    print("  ██   ██ ██      ██      ██      ██    ██ ██ ███ ██")
    print("  ██████  ███████ ██      ███████  ██████   ███ ███ ")
    print(f"{C['x']}")
    print(f"  {C['B']}Autonomous Multi-Agent Options Desk{C['x']} · Alpaca paper trading")
    print(f"  {C['d']}lablab.ai × Alpaca AI Trading Agents Hackathon{C['x']}\n")
    mode = (
        f"{C['g']}PAPER TRADING{C['x']} (live Alpaca account)"
        if live
        else f"{C['y']}SIMULATION{C['x']} (no credentials — seeded synthetic market)"
    )
    print(f"  Mode      : {mode}")
    print(f"  Universe  : {', '.join(settings.universe)}")
    print(f"  Equity    : ${settings.starting_equity:,.0f}")
    print(f"  Risk cap  : {settings.max_risk_pct:.0%} per trade "
          f"(${settings.starting_equity * settings.max_risk_pct:,.0f})")
    print()


def print_cycle(report) -> None:
    print(f"\n{C['B']}── cycle {report.cycle_id} ─────────────────────────────────{C['x']}")
    for outcome in report.outcomes:
        if outcome.accepted:
            mark, colour = "FILL", C["g"]
        elif outcome.stage == "execution" and (outcome.execution or {}).get("dry_run"):
            mark, colour = "DRY ", C["y"]
        elif outcome.stage in {"risk_gate", "audit"}:
            mark, colour = "VETO", C["r"]
        else:
            mark, colour = "PASS", C["d"]
        print(f"  {colour}{mark}{C['x']} {outcome.symbol:<6} {C['d']}{outcome.stage:<12}{C['x']} "
              f"{outcome.detail[:88]}")

    for exit_record in report.exits:
        print(f"  {C['y']}EXIT{C['x']} {exit_record['symbol']:<6} "
              f"{C['d']}{exit_record['reason'][:80]}{C['x']}")

    p = report.performance
    pnl = p["total_pnl"]
    colour = C["g"] if pnl >= 0 else C["r"]
    print(
        f"  {C['d']}equity{C['x']} ${p['equity']:,.2f}  "
        f"{C['d']}P&L{C['x']} {colour}{pnl:+,.2f} ({p['return_pct']:+.2f}%){C['x']}  "
        f"{C['d']}open{C['x']} {p['open_positions']}  "
        f"{C['d']}at risk{C['x']} ${p['capital_at_risk']:,.0f} ({p['capital_at_risk_pct']:.2f}%)  "
        f"{C['d']}Δ{C['x']} {p['net_delta']:+.3f}"
    )
    for error in report.errors:
        print(f"  {C['r']}error{C['x']} {error}")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def build_desk(dry_run: bool = False):
    from risk_gate import DeterministicRiskGate

    from deflow.agents.executor import ExecutionAgent
    from deflow.alpaca_cli import AlpacaCLI
    from deflow.alpaca_rest import AlpacaClient
    from deflow.config import SETTINGS
    from deflow.desk import TradingDesk
    from deflow.ledger import DecisionLedger
    from deflow.llm import ReasoningEngine
    from deflow.market import build_provider
    from deflow.portfolio import Portfolio

    rest = AlpacaClient() if SETTINGS.has_alpaca_credentials else None
    cli = AlpacaCLI()
    provider = build_provider(SETTINGS, rest)

    equity = SETTINGS.starting_equity
    if rest is not None:
        account = rest.get_account()
        if account.ok and isinstance(account.data, dict):
            # Trade against the account's real equity, not the configured
            # default -- the risk caps are percentages of whatever is actually
            # there.
            equity = float(account.data.get("equity", equity) or equity)
            print(f"  {C['g']}✓{C['x']} Alpaca account {account.data.get('account_number', '?')} "
                  f"— equity ${equity:,.2f}")
        else:
            print(f"  {C['r']}✗{C['x']} Alpaca credentials rejected: {account.error[:100]}")

    gate = DeterministicRiskGate(equity)
    portfolio = Portfolio(gate, equity)
    executor = ExecutionAgent(
        gate, cli=cli, rest=rest,
        preferred_route=SETTINGS.execution_route,
        dry_run=dry_run or SETTINGS.dry_run,
    )
    return TradingDesk(
        provider=provider, gate=gate, portfolio=portfolio, executor=executor,
        reasoning=ReasoningEngine(), ledger=DecisionLedger(), settings=SETTINGS,
    )


def diagnostics() -> int:
    """Report on every external integration without trading."""
    from deflow.alpaca_cli import AlpacaCLI
    from deflow.alpaca_mcp import AlpacaMCPClient
    from deflow.alpaca_rest import AlpacaClient
    from deflow.config import SETTINGS
    from deflow.llm import FeatherlessClient
    from risk_gate import DeterministicRiskGate, benchmark

    ok, warn = f"{C['g']}✓{C['x']}", f"{C['y']}○{C['x']}"
    print(f"{C['B']}Deflow diagnostics{C['x']}\n")

    print(f"{C['B']}Environment{C['x']}")
    print(f"  {ok} Python {sys.version.split()[0]}")
    print(f"  {ok} Mode: {SETTINGS.mode}")
    print(f"  {ok} Paper endpoint: {SETTINGS.trading_base_url}")

    print(f"\n{C['B']}Risk gate{C['x']}")
    stats = benchmark(20_000)
    gate = DeterministicRiskGate(SETTINGS.starting_equity)
    print(f"  {ok} v{DeterministicRiskGate.VERSION}: 12 breakers, "
          f"{stats['mean_us']:.2f} µs mean ({stats['evaluations_per_second']:,.0f}/sec)")
    print(f"  {ok} Max loss per trade: ${gate.max_allowed_loss:,.2f}")

    print(f"\n{C['B']}Alpaca Trading API{C['x']}")
    if SETTINGS.has_alpaca_credentials:
        result = AlpacaClient().get_account()
        if result.ok:
            d = result.data
            print(f"  {ok} Account {d.get('account_number')} — equity ${float(d.get('equity', 0)):,.2f}, "
                  f"status {d.get('status')}")
            print(f"  {ok} Options level: {d.get('options_trading_level', 'n/a')}")
        else:
            print(f"  {C['r']}✗{C['x']} {result.error[:120]}")
    else:
        print(f"  {warn} No credentials — set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")

    print(f"\n{C['B']}Alpaca CLI{C['x']}")
    cli = AlpacaCLI()
    if cli.available:
        print(f"  {ok} {cli.binary} ({cli.version()})")
        if SETTINGS.has_alpaca_credentials:
            account = cli.account()
            print(f"  {ok if account.ok else C['r'] + '✗' + C['x']} "
                  f"{'account reachable' if account.ok else account.stderr[:90]}")
    else:
        print(f"  {warn} not installed")
        for line in cli.install_hint().splitlines()[1:]:
            print(f"      {line.strip()}")

    print(f"\n{C['B']}Alpaca MCP server{C['x']}")
    mcp = AlpacaMCPClient()
    if mcp.available:
        started = mcp.start()
        if started.ok:
            print(f"  {ok} {mcp.server_info.get('name')} v{mcp.server_info.get('version')} — "
                  f"{len(mcp.tools)} tools")
            for keywords in (("option", "chain"), ("option", "contract"), ("account",)):
                print(f"      {'·'.join(keywords):22} -> {mcp.find_tool(*keywords) or 'not exposed'}")
        else:
            print(f"  {C['r']}✗{C['x']} {started.error[:150]}")
        mcp.stop()
    else:
        print(f"  {warn} unavailable (needs uv + Alpaca credentials)")

    print(f"\n{C['B']}Featherless AI{C['x']}")
    fl = FeatherlessClient()
    if fl.enabled:
        content, error = fl.complete("Reply with the single word: ready.", "ping", max_tokens=10)
        print(f"  {ok} {fl.model} — {content.strip()[:60]}" if not error
              else f"  {C['r']}✗{C['x']} {error[:120]}")
    else:
        print(f"  {warn} No FEATHERLESS_API_KEY — reasoning falls back to the deterministic ranker")
    fl.close()
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="deflow", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--demo", action="store_true", help="one cycle with the full reasoning trace")
    parser.add_argument("--no-serve", action="store_true", help="trade on schedule without the web API")
    parser.add_argument("--check", action="store_true", help="run integration diagnostics and exit")
    parser.add_argument("--dry-run", action="store_true", help="render orders without submitting them")
    parser.add_argument("--port", type=int, default=None, help="API port (default 8000)")
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from deflow.config import SETTINGS

    if args.check:
        banner(SETTINGS)
        return diagnostics()

    banner(SETTINGS)
    if args.dry_run:
        print(f"  {C['y']}DRY RUN{C['x']} — orders are rendered and logged, never submitted.\n")

    desk = build_desk(dry_run=args.dry_run)

    if args.demo:
        from deflow.demo import run_demo

        return run_demo(desk)

    if args.once:
        print_cycle(desk.run_cycle())
        chain = desk.ledger.verify()
        print(f"\n  {C['d']}ledger{C['x']} {len(desk.ledger)} entries · "
              f"chain {'intact' if chain.valid else 'BROKEN'} · head {desk.ledger.head[:16]}")
        return 0

    if args.no_serve:
        import time

        print(f"  Trading every {SETTINGS.cycle_seconds}s. Ctrl-C to stop.\n")
        try:
            while True:
                print_cycle(desk.run_cycle())
                time.sleep(SETTINGS.cycle_seconds)
        except KeyboardInterrupt:
            print("\n  Stopped.")
            return 0

    import uvicorn

    from deflow.api import create_app

    port = args.port or SETTINGS.api_port
    print(f"  {C['c']}Dashboard{C['x']} http://{SETTINGS.api_host}:{port}")
    print(f"  {C['c']}API docs {C['x']} http://{SETTINGS.api_host}:{port}/docs")
    print(f"  {C['d']}Trading cycle every {SETTINGS.cycle_seconds}s. Ctrl-C to stop.{C['x']}\n")

    # Run one cycle immediately so the dashboard has content on first paint.
    print_cycle(desk.run_cycle())
    print()

    uvicorn.run(create_app(desk), host=SETTINGS.api_host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    bootstrap()
    sys.exit(main())
