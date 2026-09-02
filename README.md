# Deflow - Autonomous Multi-Agent Options Desk

> Built for the **lablab.ai × Alpaca AI Trading Agents Hackathon** (28 Aug - 4 Sep 2026)
> Four agents propose. Twelve deterministic breakers decide. No model touches capital.

Deflow is an autonomous options desk that trades **defined-risk multi-leg spreads** on a live
Alpaca paper account. Its edge is the **variance risk premium** - the measured gap between the
volatility options are priced at and the volatility the underlying is actually delivering. When
implied sits meaningfully above the desk's own jump-robust forecast, it sells defined-risk
premium; when implied is cheap and there is a trend to pay for the theta, it buys convexity;
the rest of the time it does nothing, and says why, on the record.

The design principle throughout: **the language model is the least-trusted component.**
The second principle, learned live: **an unverified number is the enemy** - the dashboard
publishes the broker's own marks, the ledger is hash-chained, and a working order is not a
position until Alpaca says it filled.

```bash
python main.py
```

One command. It creates a virtualenv, installs three dependencies, starts the API, serves the
dashboard, and begins trading. With no Alpaca keys it runs the identical pipeline against a
seeded simulated market so you can read the whole system before handing it a credential -
every simulated figure is labelled as such, everywhere it appears.

**Live right now:** [dashboard](https://deflow.38.49.216.120.sslip.io/dashboard/) ·
[verifiable ledger](https://deflow.38.49.216.120.sslip.io/ledger/) ·
[docs](https://deflow.38.49.216.120.sslip.io/docs/) - running unattended on a VPS since the
first session of 2026-09-01.

---

## Contents

- [What makes it different](#what-makes-it-different)
- [The strategy](#the-strategy)
- [Architecture](#architecture)
- [The risk gate](#the-risk-gate)
- [Order and exit lifecycle](#order-and-exit-lifecycle)
- [Honest numbers](#honest-numbers)
- [Alpaca integration](#alpaca-integration)
- [Quickstart](#quickstart)
- [Web app](#web-app)
- [API](#api)
- [Building in public](#building-in-public)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Notes and limitations](#notes-and-limitations)

---

## What makes it different

**The model cannot produce a number that reaches the broker.** Strikes, widths, premiums,
Greeks, position size and every risk figure are computed from live quotes by deterministic
code. The model's entire output surface is one integer index into a list of pre-built
candidates, one confidence float, and one paragraph of prose - and the index is bounds-checked
before use. A total model failure (no key, timeout, malformed JSON, an index of 9999) degrades
to a documented deterministic ranking, not to a bad trade.

**The gate runs twice.** Once in the desk pipeline, and again inside the execution agent on the
exact proposal being sent. No refactor, retry, or forgetful caller can route an order without a
fresh approval.

**Every decision is hash-chained.** Each ledger entry carries the SHA-256 of the one before it.
Editing or deleting any historical entry breaks the chain, and `verify()` reports the index
where it broke. For a competition judged on P&L, that is the difference between results you
assert and results a third party can check - the verifier runs
[in the browser](https://deflow.38.49.216.120.sslip.io/ledger/) and over `GET /api/ledger/verify`.

**Refusals are logged as loudly as fills.** A desk that only records its trades cannot be
audited. Deflow writes an entry for every stand-down, every abstention, every veto, with the
numbers that drove it - and `GET /api/refusals` attributes each one to the stage that said no.
On its first live day the desk logged 190 refusals and filled 5 structures; that ratio is the
product, and the endpoint will tell you the current one.

**The auditor argues against the trade.** It does not read the structurer's numbers - it
re-derives the Greeks from Black-Scholes and runs its own 1,000-path fat-tailed simulation. It
has fatal-objection authority and can kill a proposal the model liked.

**The dashboard shows the broker's money, not its own.** Equity and P&L come from Alpaca's
marks, labelled `broker marks`; the desk's internal quote-mid valuation is shown alongside,
labelled, because the two genuinely differ and hiding either would be lying by omission.

---

## The strategy

Under the risk-neutral measure, every vertical spread is worth exactly what it costs. Simulating
a candidate at its own implied volatility scores every trade at approximately zero - which is
the correct answer, and a useless one.

Deflow's thesis is that implied volatility systematically **misprices** what the underlying
will actually deliver, in either direction. So candidates are scored under two measures:

| Measure | Volatility used | What it tells you |
|---|---|---|
| Risk-neutral | implied | What the market says this is worth (≈ 0 EV, as it must be) |
| Physical | jump-robust forecast | What it is worth if the stock keeps moving as it has been |

The physical forecast is **bipower variation** (Barndorff-Nielsen & Shephard) blended across
21- and 63-day windows - a jump-robust estimator that a single earnings gap cannot distort the
way it distorts a plain HV60. Plain 60-day realised vol is recorded alongside for reference.

The gap between the two measures, in dollars, is the variance risk premium - and it is the only
reason to put on the trade. The auditor reports both, and refuses anything with non-positive
expectancy under the physical measure, **however high its win rate**. A 79%-probability credit
spread with a negative mean is a trap, and rejecting it is the single most valuable thing the
auditor does.

Regime → structure:

| Stance | Bias | Structure |
|---|---|---|
| Sell premium (VRP > +2%, IV rank ≥ 40%) | bullish | Bull put spread |
| Sell premium | bearish | Bear call spread |
| Sell premium | neutral | Iron condor |
| Buy convexity (VRP < -1%, IV rank ≤ 55%) | bullish | Bull call spread |
| Buy convexity | bearish | Bear put spread |
| Buy convexity | neutral | *no trade* - nothing pays for the theta |
| Inside the band | any | *no trade* - no measured edge |

The bands are deliberately asymmetric: the desk demands two vol points of edge to sell premium
and only one to buy it, because a short-vol mistake costs more than a long-vol one.

**Event awareness without an events feed.** Alpaca serves no earnings calendar, so Deflow reads
the catalyst out of the option market itself: an IV term structure inverted by more than 15%
between adjacent expiries means the market is paying up for a known event, and short-dated
premium selling stands down around it (`deflow/events.py`).

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
   (bars, option chain)   │  IV vs bipower forecast, IV rank, trend, │
                          │  term-structure event scan, regime       │
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
                    ║   DETERMINISTIC RISK GATE - risk_gate.py          ║
                    ║   12 breakers · zero LLM · microseconds · fail-closed ║
                    ╚══════════════════════════┬═══════════════════════╝
                                               │  approved + sized
                          ┌────────────────────▼─────────────────────┐
   Alpaca CLI ◀──────────│  AGENT 4 · EXECUTION AGENT               │
   (mleg order submit)    │  re-runs the gate, then routes           │
                          └────────────────────┬─────────────────────┘
                                               │  working order, not a position
                          ┌────────────────────▼─────────────────────┐
                          │  RECONCILE · next cycle                  │
                          │  fills adopted at the broker's price,    │
                          │  stale orders cancelled and confirmed    │
                          └────────────────────┬─────────────────────┘
                                               │
                          ┌────────────────────▼─────────────────────┐
                          │  HASH-CHAINED DECISION LEDGER            │
                          │  every view, veto, fill, exit, refusal   │
                          └──────────────────────────────────────────┘
```

---

## The risk gate

`risk_gate.py` is the only component with veto authority over capital. It imports nothing but
the standard library - no network, no prompt, no temperature, no retry. Given the same proposal
and the same book it returns the same verdict, forever.

| # | Breaker | Limit |
|---|---|---|
| 1 | `defined_risk_structure` | Multi-leg only; every short covered by a long of the same right |
| 2 | `max_loss_2pct` | ≤ 2% of equity per trade ($2,000 on $100k) |
| 3 | `trade_delta_bound` | \|net delta\| ≤ 0.35 per contract-equivalent |
| 4 | `probability_of_profit` | Credit: ≥ 65% simulated win rate · debit: ≥ 30% **and** positive expectancy |
| 5 | `aggregate_risk_6pct` | ≤ 6% of equity at risk across the book, working orders included |
| 6 | `symbol_concentration_3pct` | ≤ 3% of equity in any one underlying |
| 7 | `portfolio_delta_bound` | Book \|delta\| ≤ 1.20 |
| 8 | `max_open_positions` | ≤ 6 |
| 9 | `dte_window` | 7-60 days |
| 10 | `payoff_quality` | Credit ≥ 15% of wing width; debit reward:risk ≥ 0.8 |
| 11 | `daily_drawdown_killswitch` | Halts new risk at -3% on the session |
| 12 | `vega_ceiling` | Book \|vega\| ≤ 2.5 per $1,000 of equity |

Breaker 4 is two rules on purpose: a credit spread is a win-rate business, a debit spread is an
expectancy business, and holding both to one floor either blocks every debit or waves through
weak credits. The dashboard's gate panel shows both floors, labelled.

Plus a mandatory exit guard, evaluated continuously and never routed through a model: a stop at
**50% of defined max loss**, a profit target that **tightens as expiry approaches** (75% of max
profit at 30+ DTE, scaling to 40% at 7 DTE - the last quarter of a credit spread's profit
arrives exactly when gamma is largest), and a forced close inside **3 DTE** so nothing is
carried into the expiry spike.

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
[VETO] Naked call - no long wing to cap the loss
       VETO [breaker 1/defined_risk_structure]: Naked or unrecognised structure
       (naked_call, 1 legs). Only covered multi-leg spreads may reach the
       broker. (+5 further breakers failed)
       6/12 breakers passed in 12.25 µs
[VETO] Proposal with max_loss omitted entirely (fail-closed test)
       VETO [breaker 2/max_loss_2pct]: Defined max loss $1,000,000,000,000.00
       vs $2,000.00 cap (+3 further breakers failed)
       8/12 breakers passed in 5.08 µs

 Latency: 1.27 µs mean over 50,000 evaluations (786,647/sec)
```

Cheap enough that bypassing it is never a temptation. That figure is whatever your own machine
prints - hardware varies, so the benchmark ships rather than the number.

---

## Order and exit lifecycle

Most agent projects treat a submitted order as a done deal. Deflow's first live session showed
why that is wrong - multi-leg limit orders routinely rest unfilled - so the lifecycle is
engineered on both sides of a position:

- **Submitted is not filled.** Entries and exits both live as working orders, persisted to disk,
  until the broker confirms a fill. Only then does the book change, at the price actually given.
  Working orders still reserve risk budget - they might fill at any moment - but they never
  count as positions.
- **Exits are priced off the current mark, never the entry.** A closing limit derived from the
  entry price is fillable for winners and structurally unfillable for losers - a stop-loss that
  can only close profitable positions is decoration. The concession always moves toward a fill.
- **A cancel acknowledgement is not a cancel.** Alpaca's 204 accepts the request; the order can
  still fill while `pending_cancel`. Nothing is dropped from the book until the broker reports a
  terminal state, so a fill that races the cancel is booked, not lost.
- **One flaky poll cannot double an order.** A rate-limit and a "no such order" arrive in the
  same shape; an exit leaves the book only on a broker-observed terminal state or three
  consecutive not-founds.
- **Partial fills freeze rather than compound.** A close for 2 contracts that fills 1 and then
  dies flags the position for human reconciliation instead of resubmitting full-size into an
  inverted book.
- **Restarts cannot double-submit.** Closing orders carry deterministic client ids persisted
  *before* submission, so Alpaca itself rejects the duplicate a crash-and-restart would send,
  and orphaned orders can be recovered by name.
- **A suspect mark cannot fire an exit.** A quote that prices a spread outside its own payoff
  bounds is bad data by definition; it is clamped, flagged, and deferred one cycle rather than
  allowed to realise a phantom stop at the open.

---

## Honest numbers

The claim "auditable" is cheap. These are the specific mechanisms behind it:

- **Broker marks on the headline.** Deflow marks legs at the quote mid internally (correct for
  exit logic), but mid flatters both legs of a spread - on day one the two bases differed by
  43% of the P&L. The dashboard's money is Alpaca's own figure, the basis is named on the
  panel, and when the broker is unreachable the figures blank to `-` rather than substituting
  a number from a different basis.
- **No fabricated zeros.** A value that has not been fetched renders as a dash, never as $0.00.
  A win rate over zero closed trades is undefined, not 0%.
- **Series are validated against their claimed basis.** Alpaca's portfolio-history endpoint
  returned a gains series in its equity field; unvalidated, it charted as "+133.68% return".
  The equity curve refuses any series that is not on an equity basis and falls back to its own
  ledger reconstruction, labelled.
- **A shareable, checkable P&L card.** `GET /api/pnl-card?date=` summarises one trading day -
  P&L, cycles, refusals, vetoes - stamped with that day's ledger head hash, so the number on
  the picture can be checked against a chain anyone can verify. The dashboard renders and
  downloads it as a 1200×630 PNG.

---

## Alpaca integration

Deflow uses **all three** parts of the Alpaca developer stack, each for what it is best at.

### Trading API - `deflow/alpaca_rest.py`
Written directly against the HTTP surface so the multi-leg payload is visible and adjustable in
one place. Account, positions, orders (by id and by client id), portfolio history, daily bars,
option chain snapshots (NBBO + server-side Greeks), and `POST /v2/orders` with
`order_class="mleg"`.

The client **refuses to initialise against a non-paper endpoint**. This project is paper-only by
construction, not by configuration.

### Alpaca CLI - `deflow/alpaca_cli.py` *(default order route)*
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

### MCP server - `deflow/alpaca_mcp.py`
Alpaca's official FastMCP server, used for structured discovery: option chains, contract
metadata, account state as typed tools. Deflow speaks JSON-RPC over stdio directly rather than
pulling in an SDK - the surface it needs is `initialize`, `tools/list`, `tools/call` - and
discovers tool names at runtime by keyword rather than hard-coding names that a server update
would break.

> **Heads-up, and Deflow works around it:** `alpaca-mcp-server` 2.3.0 declares `fastmcp>=3.1.0`
> with no upper bound, so a plain `uvx alpaca-mcp-server` resolves fastmcp 4.x, which moved
> `fastmcp.tools.tool` - the server then dies on import before emitting a byte. Deflow launches
> it as `uvx --with 'fastmcp>=3.1,<4' alpaca-mcp-server`. Override with `DEFLOW_MCP_COMMAND`
> once upstream constrains it.

Check every integration at once:

```bash
python main.py --check
```

---

## Quickstart

**Requirements:** Python 3.11+. Optional but recommended: the Alpaca CLI (order routing), `uv`
(MCP server), Node 18+ (to rebuild the dashboard - a built copy is committed).

```bash
git clone https://github.com/mrnetwork0001/Deflow.git
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

### Deploying

`deploy/` contains what the live instance runs on: a read-only preflight, a strictly additive
installer safe for a shared VPS, a systemd unit, Caddy/nginx site fragments, and an updater
that preserves the data directory - the ledger is what makes the P&L checkable, and a deploy
that resets it would destroy exactly that. See [DEPLOYMENT.md](DEPLOYMENT.md).

---

## Web app

Next.js 14 (App Router, static export), served by the FastAPI backend - no Node process in
production. Four routes:

| Route | What it is |
|---|---|
| `/` | Landing page - the thesis, the pipeline, the twelve breakers, the live gate probe |
| `/dashboard/` | The live desk: section rail, account on broker marks, equity curve, regime grid, open structures, SSE decision stream, refusals, gate panel, P&L card |
| `/ledger/` | The hash-chained ledger with an in-browser verifier |
| `/docs/` | Full documentation in a grouped-sidebar format |

Details judges tend to ask about: the account panel names its mark basis (`broker marks` /
`mid marks`); a market-closed banner counts down to the next open **in the viewer's own
timezone**; the gate panel fires a deliberately hostile naked-call probe at the running gate
and shows which breakers trip and in how many microseconds; and every count on the page
distinguishes "not loaded yet" from "genuinely zero".

```bash
cd web && npm install && npm run build     # only needed if you change the UI
```

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Desk state, performance on broker marks, market clock, working orders |
| `GET /api/performance` | P&L and trade statistics, `mark_source` named |
| `GET /api/positions` | Open and closed structures |
| `GET /api/account` | The Alpaca account, verbatim |
| `GET /api/analysis` | Live analyst views |
| `GET /api/refusals` | Every refusal, attributed to the stage that made it |
| `GET /api/equity-curve` | Equity over time, basis-validated |
| `GET /api/pnl-card?date=` | One trading day, summarised and stamped with the ledger head |
| `GET /api/chain/{symbol}` | Option chain snapshot |
| `GET /api/ledger` | Hash-chained decision log |
| `GET /api/ledger/verify` | Recompute the chain, report any break |
| `GET /api/risk/envelope` | The twelve limits, both PoP floors included |
| `POST /api/risk/evaluate` | Run any proposal through the gate - nothing is routed |
| `POST /api/cycle` | Run one cycle now |
| `GET /api/stream` | SSE decision stream |

The API is deliberately asymmetric: everything needed to *watch* the desk is exposed, and there
is no endpoint that places an order. Orders exist only as the output of a full pipeline that has
cleared the gate.

---

## Building in public

The hackathon's social-engagement track: one post a day while the desk trades, tagging
@lablabai and @AlpacaHQ. The plan and full drafts live in
[SOCIAL_ENGAGEMENT_POSTS.md](SOCIAL_ENGAGEMENT_POSTS.md); the ground rule there is that
**no post claims a number that has not happened** - the results post is generated from the
hash-chained ledger, not hand-written.

| # | Day | Topic | Status |
|---|-----|-------|--------|
| 1 | Tue 1 Sep | The thesis - why the model must not size the trade | [posted](https://x.com/encrypt_wizard/status/2094702482274312352) |
| 2 | Wed 2 Sep | Day-1 results thread: the fill asymmetry, the flattering dashboard, the edge that said no | [posted](https://x.com/encrypt_wizard/status/2094968034544738620) |
| 3 | Wed 2 Sep | Session 2 settled: +$1,102 with zero orders, quoting the autopsy | [posted](https://x.com/encrypt_wizard/status/2095242422645362921) |
| 4 | Thu 3 Sep | Results, generated from the ledger | planned |
| 5 | Fri 4 Sep | Ship + reveal | planned |

Post 1 deliberately named neither the project nor the strategy; the reveal waits until there
are live trades to point at, and the results post is the one post that may carry performance
figures - generated from the ledger, never hand-written.

---

## Testing

```bash
python -m pytest tests/ -q      # 250 tests
```

The suites are written from the attacker's side. `test_risk_gate.py` is 66 attempts to get
capital past a breaker: omitted fields, NaN, infinity, wrong types, an empty proposal, a model
that sets `is_defined_risk_spread: true` on a $15k naked call. The pricing suite checks
closed-form identities - put-call parity to 1e-9, implied-vol round trips, and that the
jump-diffusion simulator is a martingale - rather than comparing against recorded output. The
pipeline suite asserts the invariants that cannot be wrong even once: no naked structure ever
leaves the structurer, every wing sits beyond its short, and no mark can report P&L outside the
structure's own payoff bounds. `test_exits.py` and `test_reporting.py` pin the live lessons:
one flaky status poll must not drop a working exit, a cancel-ack is not a cancel, a partial
fill freezes rather than compounds, and a broker that stops answering blanks the money figures
rather than substituting a different basis.

---

## Project layout

```
main.py                    one-command entrypoint (bootstrap, CLI, wiring)
risk_gate.py               the 12 deterministic breakers - stdlib only
deflow/
  config.py                environment, mode detection, paper-endpoint guard
  models.py                Strategy, Leg, SpreadProposal, OCC symbology
  greeks.py                Black-Scholes, Greeks, implied-vol solver
  indicators.py            bipower realised vol, IV rank, RSI, trend score
  montecarlo.py            Merton jump-diffusion stress testing
  events.py                priced-in catalyst detection from the IV term structure
  market.py                Alpaca market data + seeded simulator
  alpaca_rest.py           Trading API + Market Data API
  alpaca_cli.py            official CLI bridge (default order route)
  alpaca_mcp.py            MCP stdio client
  llm.py                   Featherless AI, bounded to one index
  ledger.py                hash-chained audit log
  portfolio.py             position book, pending orders and exits, mark-to-market
  rolls.py                 time-scaled profit targets, roll gating
  desk.py                  the six-stage cycle + reconciliation
  api.py                   FastAPI + SSE + broker-marks overlay
  demo.py                  full reasoning trace
  agents/                  analyst · structurer · auditor · executor
web/                       Next.js 14 app (landing, dashboard, ledger, docs)
deploy/                    VPS deployment: preflight, additive install, systemd, Caddy
tests/                     250 tests
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
- **The slippage buffer is a percentage of net premium**, which prices debit-spread orders more
  marketably than credit-spread orders (3% of a large debit crosses the spread; 3% of a small
  credit rests at the mid). The first live session measured exactly this - credit fills lagged
  debit fills badly - and a width-based buffer is the known fix, deliberately not shipped
  mid-competition because it changes live fill behaviour. Documented rather than hidden.
- **Rolls ship disabled** (`DEFLOW_ROLL_ENABLED`). The roll path still books its close on
  acceptance rather than through the confirmed-fill lifecycle, and it stays off until it books
  on fill like every other exit.
- **`web/` reports two high-severity npm advisories against Next 14.2.35.** They are all
  server-side - image optimizer, RSC, middleware, server actions, rewrites - and this dashboard
  is a static export served by FastAPI, so none of those code paths run. The only clean audit
  requires Next 16, a major upgrade away from the stated stack. Documented rather than silently
  carried.
- **Options are not suitable for every investor.** This is a paper-trading project. Paper
  trading is a simulation; results are hypothetical and do not represent actual trading. See
  [LICENSE](LICENSE) for the full disclaimer.

---

## License

[MIT](LICENSE) · Built by Ifeanyichukwu Onwo ([@mrnetwork0001](https://github.com/mrnetwork0001)) for the
lablab.ai × Alpaca AI Trading Agents Hackathon, September 2026.
