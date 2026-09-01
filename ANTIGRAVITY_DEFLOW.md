# Deflow — Project Directives

Persistent context for AI coding assistants working on this repository.

## What this is

An autonomous multi-agent options desk for the lablab.ai × Alpaca AI Trading Agents Hackathon.
Trades defined-risk multi-leg spreads on Alpaca paper trading, harvesting the variance risk
premium. Deadline: **4 September 2026, 16:00 WAT**.

Source of truth, in order: [DEFLOW_PROJECT_SPEC.md](DEFLOW_PROJECT_SPEC.md) →
[README.md](README.md) → the code.

## Non-negotiable invariants

Break any of these and the project's premise collapses. All are covered by tests.

1. **No model output may become a number that reaches the broker.** The reasoning layer returns
   an index, a confidence, and prose. Nothing else. The index is bounds-checked.
2. **`risk_gate.py` imports only the standard library.** No network, no model, no config that can
   widen a limit. If you need a new check, add a breaker — do not relax an existing one.
3. **Fail closed.** Every field read from a proposal uses a pessimistic default. A missing value
   is the worst case, never zero.
4. **All twelve breakers run every time.** No short-circuit on first failure — the ledger needs
   every result.
5. **Only defined-risk structures.** Every short leg covered by a long of the same right, with
   the wing strictly beyond the short. Enforced at construction, not just checked afterwards.
6. **Paper only.** `alpaca_rest.py` refuses non-paper endpoints; the CLI bridge pins
   `ALPACA_LIVE_TRADE=false`; the MCP client pins `ALPACA_PAPER_TRADE=true`.
7. **Refusals are logged as loudly as fills.**
8. **Simulated output is labelled `simulated: true` everywhere it surfaces** — API, ledger,
   dashboard, terminal — and is never reported as a trading result.

## Honesty rules

This project is judged on real P&L in a fresh paper account, and its whole thesis is that
unverified claims are the enemy.

- Never write a performance number into a document by hand. Generate it
  (`python scripts/social_post.py`) or omit it.
- Never describe an event that did not happen, in a commit message, a doc, or a social post.
- Performance claims in the README (latency, test count) must be reproducible by the commands
  the README names. If you change the code, re-run them and update the numbers.

## Environment

Credentials use Alpaca's official names — `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — because the
CLI and MCP server both read them, so one `.env` drives all three surfaces.

## Verify before claiming done

```bash
python -m pytest tests/ -q     # 172 tests
python risk_gate.py            # adversarial cases + latency benchmark
python main.py --check         # every integration
python main.py --demo          # full six-stage trace
```
