# Deflow — Autonomous Multi-Agent Options Desk

> Built for the **lablab.ai × Alpaca AI Trading Agents Hackathon** (28 Aug – 4 Sep 2026)
> Four agents propose. Twelve deterministic breakers decide. No model touches capital.

Deflow is an autonomous options desk that trades **defined-risk multi-leg spreads** on Alpaca
paper trading. Its edge is the **variance risk premium** — the persistent gap between the
volatility options are priced at and the volatility the underlying actually delivers. When
implied sits meaningfully above realised, it sells defined-risk premium; when implied is
cheap and there is a trend to pay for the theta, it buys convexity; the rest of the time it
does nothing, and says why.

The design principle throughout: **the language model is the least-trusted component.**

```bash
python main.py
```

One command. It creates a virtualenv, installs three dependencies, starts the API, serves the
dashboard, and begins trading. With no Alpaca keys it runs the identical pipeline against a
seeded simulated market so you can read the whole system before handing it a credential —
every simulated figure is labelled as such, everywhere it appears.

---

## Contents

- [What makes it different](#what-makes-it-different)
- [The strategy](#the-strategy)
- [Architecture](#architecture)
- [The risk gate](#the-risk-gate)
- [Alpaca integration](#alpaca-integration)
- [Quickstart](#quickstart)
- [Dashboard](#dashboard)
- [API](#api)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Notes and limitations](#notes-and-limitations)

---

## What makes it different

**The model cannot produce a number that reaches the broker.** Strikes, widths, premiums,
Greeks, position size and every risk figure are computed from live quotes by deterministic
code. The model's entire output surface is one integer index into a list of pre-built
candidates, one confidence float, and one paragraph of prose — and the index is bounds-checked
before use. A total model failure (no key, timeout, malformed JSON, an index of 9999) degrades
to a documented deterministic ranking, not to a bad trade.

**The gate runs twice.** Once in the desk pipeline, and again inside the execution agent on the
exact proposal being sent. No refactor, retry, or forgetful caller can route an order without a
fresh approval.

**Every decision is hash-chained.** Each ledger entry carries the SHA-256 of the one before it.
Editing or deleting any historical entry breaks the chain, and `verify()` reports the index
where it broke. For a competition judged on P&L, that is the difference between results you
assert and results a third party can check.

**Refusals are logged as loudly as fills.** A desk that only records its trades cannot be
audited. Deflow writes an entry for every stand-down, every abstention, every veto, with the
numbers that drove it.

**The auditor argues against the trade.** It does not read the structurer's numbers — it
re-derives the Greeks from Black-Scholes and runs its own 1,000-path fat-tailed simulation. It
has fatal-objection authority and can kill a proposal the model liked.

---

## The strategy

Under the risk-neutral measure, every vertical spread is worth exactly what it costs. Simulating
a candidate at its own implied volatility scores every trade at approximately zero — which is
the correct answer, and a useless one.

Deflow's thesis is that implied volatility systematically **overstates** what the underlying
will actually deliver. So candidates are scored under two measures:

| Measure | Volatility used | What it tells you |
|---|---|---|
| Risk-neutral | implied | What the market says this is worth (≈ 0 EV, as it must be) |
| Physical | realised (HV60) | What it is worth if the stock keeps moving as it has been |

The gap between them, in dollars, is the variance risk premium — and it is the only reason to
put on the trade. The auditor reports both, and refuses anything with non-positive expectancy
under the physical measure, **however high its win rate**. A 79%-probability credit spread with
a negative mean is a trap, and rejecting it is the single most valuable thing the auditor does.

Regime → structure:

| Stance | Bias | Structure |
|---|---|---|
| Sell premium (IV ≫ HV, IV rank ≥ 40%) | bullish | Bull put spread |
| Sell premium | bearish | Bear call spread |
| Sell premium | neutral | Iron condor |
| Buy convexity (IV < HV, IV rank ≤ 55%) | bullish | Bull call spread |
| Buy convexity | bearish | Bear put spread |
| Buy convexity | neutral | *no trade* — nothing pays for the theta |
| Stand down | any | *no trade* |

**On IV rank.** A true IV rank needs a year of implied-vol observations, and Alpaca (like most
brokers) does not serve historical IV. Deflow is explicit about which basis it is using: from
day one it ranks current ATM IV against the trailing year of *realised* vol, reported as
`basis="hv_proxy"`. It also records observed ATM IV every cycle, and once 20 sessions have
accumulated it switches to the real implied-vol history and reports `basis="iv_history"`.

---

## Architecture

```
                          ┌──────────────────────────────────────────┐
   Alpaca Market Data ───▶│  AGENT 1 · MACRO & VOLATILITY ANALYST    │
   (bars, option chain)   │  IV vs HV, IV rank, trend, regime        │
                          └────────────────────┬─────────────────────┘
                                               │  stance + bias
                          ┌────────────────────▼─────────────────────┐
   Alpaca FastMCP ───────▶│  AGENT 2 · OPTIONS STRUCTURER            │
   (chain, contracts)     │  delta-targeted strikes, width ladder,   │
                          │  liquidity floor, gate-aware sizing      │
                          └────────────────────┬─────────────────────┘
                                               │  8 priced candidates
                          ┌────────────────────▼─────────────────────┐
   Featherless AI ───────▶│  REASONING LAYER (bounded)               │
   (Qwen2.5-72B)          │  picks ONE index, or abstains. Nothing   │
                          │  else. Falls back to a deterministic     │
                          │  ranker on any failure.                  │
                          └────────────────────┬─────────────────────┘
                                               │  one proposal
                          ┌────────────────────▼─────────────────────┐
                          │  AGENT 3 · ADVERSARIAL RISK AUDITOR      │
                          │  independent Greeks · 1,000-path Merton  │
                          │  jump-diffusion · fatal objections       │
                          └────────────────────┬─────────────────────┘
                                               │
                    ╔══════════════════════════▼═══════════════════════╗
                    ║   DETERMINISTIC RISK GATE — risk_gate.py         ║
                    ║   12 breakers · zero LLM · ~1.3 µs · fail-closed ║
                    ╚══════════════════════════┬═══════════════════════╝
                                               │  approved + sized
                          ┌────────────────────▼─────────────────────┐
   Alpaca CLI ◀──────────│  AGENT 4 · EXECUTION AGENT               │
   (mleg order submit)    │  re-runs the gate, then routes           │
                          └────────────────────┬─────────────────────┘
                                               │
                          ┌────────────────────▼─────────────────────┐
                          │  HASH-CHAINED DECISION LEDGER            │
                          │  every view, veto, fill and exit         │
                          └──────────────────────────────────────────┘
```

---

## The risk gate

`risk_gate.py` is the only component with veto authority over capital. It imports nothing but
the standard library — no network, no prompt, no temperature, no retry. Given the same proposal
and the same book it returns the same verdict, forever.

| # | Breaker | Limit |
|---|---|---|
| 1 | `defined_risk_structure` | Multi-leg only; every short covered by a long of the same right |
| 2 | `max_loss_2pct` | ≤ 2% of equity per trade ($2,000 on $100k) |
| 3 | `trade_delta_bound` | \|net delta\| ≤ 0.35 per contract-equivalent |
| 4 | `probability_of_profit` | ≥ 65%, from the simulated win rate |
| 5 | `aggregate_risk_6pct` | ≤ 6% of equity at risk across the book |
| 6 | `symbol_concentration_3pct` | ≤ 3% of equity in any one underlying |
| 7 | `portfolio_delta_bound` | Book \|delta\| ≤ 1.20 |
| 8 | `max_open_positions` | ≤ 6 |
| 9 | `dte_window` | 7–60 days |
| 10 | `payoff_quality` | Credit ≥ 15% of wing width; debit reward:risk ≥ 0.8 |
| 11 | `daily_drawdown_killswitch` | Halts new risk at −3% on the session |
| 12 | `vega_ceiling` | Book \|vega\| ≤ 2.5 per $1,000 of equity |

Plus a mandatory exit guard, evaluated continuously and never routed through a model: close at
**50% of defined max loss**, close at **75% of max profit**, and force a close inside **3 DTE**
so nothing is carried into the gamma spike at expiry.

Three properties are enforced by construction:

- **Fail closed.** Every field is read with a *pessimistic* default. A missing `max_loss` is not
  zero, it is unbounded. NaN and infinity fail every comparison by design. A malformed proposal
  is vetoed, never approved.
- **No short-circuit.** All twelve breakers run even after one fails, so the ledger records every
  result rather than only the first problem.
- **The gate sizes the trade.** `max_contracts()` returns the largest size satisfying breakers 2,
  5 and 6. The model never chooses size, and the gate has no code path that increases one.

See it work:

```bash
python risk_gate.py       # five adversarial cases + a latency benchmark
```

```
[VETO] Naked call — no long wing to cap the loss
       VETO [breaker 1/defined_risk_structure]: Naked or unrecognised structure
       7/12 breakers passed in 10.04 µs
[VETO] Proposal with max_loss omitted entirely (fail-closed test)
       VETO [breaker 2/max_loss_2pct]: Defined max loss $1,000,000,000,000.00 vs $2,000.00 cap

 Latency: 1.27 µs mean over 50,000 evaluations (786,647/sec)
```

The gate is cheap enough that bypassing it is never a temptation. That figure is measured on
your machine by the command above, not quoted from ours.

---

## Alpaca integration

Deflow uses **all three** parts of the Alpaca developer stack, each for what it is best at.

### Trading API — `deflow/alpaca_rest.py`
Written directly against the HTTP surface so the multi-leg payload is visible and adjustable in
one place. Account, positions, orders, portfolio history, daily bars, option chain snapshots
(NBBO + server-side Greeks), and `POST /v2/orders` with `order_class="mleg"`.

The client **refuses to initialise against a non-paper endpoint**. This project is paper-only by
construction, not by configuration.

### Alpaca CLI — `deflow/alpaca_cli.py` *(default order route)*
The official CLI, `github.com/alpacahq/cli` (binary: `alpaca`).

```bash
go install github.com/alpacahq/cli/cmd/alpaca@latest   # or: brew install alpacahq/tap/cli
```

Orders route through the CLI rather than raw REST because it is the interface an unattended
agent actually gets deployed behind: it carries its own 429/5xx backoff, resolves credentials
itself, and supports `--dry-run`, which renders the exact request body without sending it. Every
order carries a `--client-order-id`, so a retry after an ambiguous failure is rejected as a
duplicate instead of opening a second position.

```bash
alpaca order submit --order-class mleg --qty 4 --type limit --limit-price -1.35 \
  --legs '[{"symbol":"SPY261016P00540000","ratio_qty":"1","side":"sell","position_intent":"sell_to_open"},
           {"symbol":"SPY261016P00535000","ratio_qty":"1","side":"buy","position_intent":"buy_to_open"}]'
```

### MCP server — `deflow/alpaca_mcp.py`
Alpaca's official FastMCP server, used for structured discovery: option chains, contract
metadata, account state as typed tools. Deflow speaks JSON-RPC over stdio directly rather than
pulling in an SDK — the surface it needs is `initialize`, `tools/list`, `tools/call` — and
discovers tool names at runtime by keyword rather than hard-coding names that a server update
would break.

> **Heads-up, and Deflow works around it:** `alpaca-mcp-server` 2.3.0 declares `fastmcp>=3.1.0`
> with no upper bound, so a plain `uvx alpaca-mcp-server` resolves fastmcp 4.x, which moved
> `fastmcp.tools.tool` — the server then dies on import before emitting a byte. Deflow launches
> it as `uvx --with 'fastmcp>=3.1,<4' alpaca-mcp-server`. Override with `DEFLOW_MCP_COMMAND`
> once upstream constrains it.

Check every integration at once:

```bash
python main.py --check
```

---

## Quickstart

**Requirements:** Python 3.11+. Optional but recommended: the Alpaca CLI (order routing), `uv`
(MCP server), Node 18+ (to rebuild the dashboard — a built copy is committed).

```bash
git clone https://github.com/mrnetwork/Deflow.git
cd Deflow
python main.py
```

To trade a real Alpaca paper account, create a **fresh** one (reused accounts are not eligible
for judging), set its starting balance to $100,000, and:

```bash
cp .env.example .env
# add ALPACA_API_KEY and ALPACA_SECRET_KEY
python main.py
```

### Modes

| Command | What it does |
|---|---|
| `python main.py` | API + dashboard + trading loop |
| `python main.py --once` | One cycle, print the report, exit |
| `python main.py --demo` | One cycle with the full six-stage reasoning trace |
| `python main.py --dry-run` | Full pipeline; orders rendered and logged, never sent |
| `python main.py --no-serve` | Trade on the schedule with no web API |
| `python main.py --check` | Diagnose every integration |

`--demo` is the fastest way to understand the system: it prints each agent's inputs and
outputs, all twelve breaker results with their numbers, and the routing decision.

---

## Web app

Next.js 14 (App Router, static export), served by the FastAPI backend at
`http://127.0.0.1:8000`. Two routes:

| Route | What it is |
|---|---|
| `/` | Landing page — the thesis, the pipeline, the twelve breakers, and a **Launch app** button |
| `/dashboard/` | The live desk |

The dashboard carries a live SSE decision stream, per-symbol variance-premium bars, the open book
with Greeks, capital-at-risk metered against the 6% ceiling, and a **"probe with a naked call"**
button that fires a hostile proposal at the running gate and shows which breakers trip and in how
many microseconds. The landing page has the same probe, wired to the same endpoint — so the
headline claim is demonstrable before anyone opens the app.

```bash
cd web && npm install && npm run build     # only needed if you change the UI
```

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Desk state, risk envelope, ledger integrity |
| `GET /api/performance` | P&L and trade statistics |
| `GET /api/positions` | Open and closed structures |
| `GET /api/analysis` | Live analyst views |
| `GET /api/chain/{symbol}` | Option chain snapshot |
| `GET /api/ledger` | Hash-chained decision log |
| `GET /api/ledger/verify` | Recompute the chain, report any break |
| `GET /api/risk/envelope` | The twelve limits |
| `POST /api/risk/evaluate` | Run any proposal through the gate — nothing is routed |
| `POST /api/cycle` | Run one cycle now |
| `GET /api/stream` | SSE decision stream |

The API is deliberately asymmetric: everything needed to *watch* the desk is exposed, and there
is no endpoint that places an order. Orders exist only as the output of a full pipeline that has
cleared the gate.

---

## Testing

```bash
python -m pytest tests/ -q      # 172 tests
```

The suites are written from the attacker's side. `test_risk_gate.py` is 66 attempts to get
capital past a breaker: omitted fields, NaN, infinity, wrong types, an empty proposal, a model
that sets `is_defined_risk_spread: true` on a $15k naked call. The pricing suite checks
closed-form identities — put-call parity to 1e-9, implied-vol round trips, and that the
jump-diffusion simulator is a martingale — rather than comparing against recorded output. The
pipeline suite asserts the invariants that cannot be wrong even once: no naked structure ever
leaves the structurer, every wing sits beyond its short, and no mark can report P&L outside the
structure's own payoff bounds.

---

## Project layout

```
main.py                    one-command entrypoint (bootstrap, CLI, wiring)
risk_gate.py               the 12 deterministic breakers — stdlib only
deflow/
  config.py                environment, mode detection, paper-endpoint guard
  models.py                Strategy, Leg, SpreadProposal, OCC symbology
  greeks.py                Black-Scholes, Greeks, implied-vol solver
  indicators.py            realised vol, IV rank, RSI, trend score
  montecarlo.py            Merton jump-diffusion stress testing
  market.py                Alpaca market data + seeded simulator
  alpaca_rest.py           Trading API + Market Data API
  alpaca_cli.py            official CLI bridge (default order route)
  alpaca_mcp.py            MCP stdio client
  llm.py                   Featherless AI, bounded to one index
  ledger.py                hash-chained audit log
  portfolio.py             position book, mark-to-market, exit guard
  desk.py                  the six-stage cycle
  api.py                   FastAPI + SSE
  demo.py                  full reasoning trace
  agents/                  analyst · structurer · auditor · executor
web/                       Next.js 14 dashboard (static export)
tests/                     172 tests
```

---

## Notes and limitations

Stated plainly, because a risk system that oversells itself is the wrong kind of risk system.

- **Simulation mode is a demonstration, not a backtest.** Without credentials Deflow runs a
  seeded synthetic market so the pipeline is inspectable end to end. Those numbers are labelled
  `simulated: true` in the API, the ledger, the dashboard and the CLI output. They are not
  evidence of profitability and are not reported as such.
- **IV rank starts as a realised-vol proxy** and becomes a true implied-vol rank after 20
  sessions of observation. The basis is reported alongside the number, always.
- **Mid-price fills are optimistic.** Live limits cross the spread by a 3% buffer, but real
  multi-leg fills can be worse than modelled, and the simulator does not model queue position or
  partial fills.
- **`web/` reports two high-severity npm advisories against Next 14.2.35.** They are all
  server-side — image optimizer, RSC, middleware, server actions, rewrites — and this dashboard
  is a static export served by FastAPI, so none of those code paths run. The only clean audit
  requires Next 16, a major upgrade away from the stated stack. Documented rather than silently
  carried.
- **Options are not suitable for every investor.** This is a paper-trading project. See
  [LICENSE](LICENSE) for the full disclaimer.

---

## License

[MIT](LICENSE) · Built by Ifeanyichukwu Onwo ([@mrnetwork](https://github.com/mrnetwork)) for the
lablab.ai × Alpaca AI Trading Agents Hackathon, September 2026.
