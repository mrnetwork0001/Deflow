# Deflow — AI Logic, Risk Gates, and Alpaca Infrastructure

**lablab.ai × Alpaca AI Trading Agents Hackathon** · Ifeanyichukwu Onwo ([@mrnetwork0001](https://github.com/mrnetwork0001))
**Alpaca paper account:** `PA3KERV81N47` · starting balance $100,000
**Repository:** https://github.com/mrnetwork0001/Deflow · MIT

> Account `PA3KERV81N47` was created fresh for this hackathon with a $100,000 balance and no
> prior trading history, so every position and every dollar of P&L in it is this agent's.

---

## 1. The edge being traded

Deflow harvests the **variance risk premium**: the persistent gap between the volatility options
are priced at and the volatility the underlying actually delivers.

This matters because under the risk-neutral measure every vertical spread is worth exactly what
it costs. Scoring a candidate at its own implied volatility returns approximately zero expected
value for every trade — the correct answer, and a useless one. Deflow therefore scores each
candidate under **two** measures and trades the difference:

| Measure | Volatility | Meaning |
|---|---|---|
| Risk-neutral | implied | What the market says it is worth (≈ 0 EV, as arbitrage requires) |
| Physical | realised (HV60) | What it is worth if the underlying keeps moving as it has |

The dollar gap between them *is* the edge. Anything with non-positive expectancy under the
physical measure is refused — **however high its win rate**. A 79%-probability credit spread
with a negative mean is the classic short-premium trap, and rejecting it is the single most
valuable judgement the system makes.

Regime decides the structure: implied rich and IV rank ≥ 40% → sell defined-risk premium (bull
put / bear call spread, or an iron condor on a neutral tape); implied cheap with a trend to pay
for the theta → buy a debit spread; otherwise stand down. Roughly half of all symbol-cycles end
in no trade, and each one is logged with the numbers that produced it.

## 2. AI logic — the model is the least-trusted component

Four agents run in sequence: **Analyst** (regime and variance premium from Alpaca bars) →
**Structurer** (delta-targeted strikes, a width ladder, a hard liquidity floor, and sizing taken
from the risk gate itself) → **Reasoning layer** → **Adversarial Auditor** (independent
Black-Scholes Greeks and a 1,000-path Merton jump-diffusion stress test, with fatal-objection
authority) → **Execution**.

The contract with the language model is deliberately narrow:

> **The model never produces a number that reaches the broker.**

Strikes, widths, premiums, Greeks, position size and every risk figure are computed from live
quotes by deterministic code. Featherless AI (Qwen2.5-72B) is shown finished, priced candidates
and returns exactly three things: **one integer index**, one confidence float, and one paragraph
of prose. The index is bounds-checked before use. A model that hallucinates index 9999 is
ignored, not indexed with. Total model failure — no key, timeout, malformed JSON — degrades to a
documented deterministic ranker, and the ledger records which brain made every call.

The auditor is genuinely adversarial: it does not read the Structurer's numbers, it re-derives
them, and it can kill a proposal the model liked.

## 3. Risk gates — twelve deterministic breakers, zero LLM

`risk_gate.py` imports nothing but the standard library. No network, no prompt, no temperature,
no retry. Same proposal plus same book returns the same verdict, forever.

| # | Breaker | Limit | | # | Breaker | Limit |
|---|---|---|---|---|---|---|
| 1 | defined-risk structure | shorts covered | | 7 | portfolio delta | ±1.20 |
| 2 | max loss per trade | 2% ($2,000) | | 8 | open positions | ≤ 6 |
| 3 | trade delta | ±0.35 | | 9 | DTE window | 7–60 |
| 4 | probability of profit | ≥ 65% | | 10 | payoff quality | credit ≥ 15% of width |
| 5 | aggregate book risk | 6% | | 11 | daily drawdown | kill switch at −3% |
| 6 | per-symbol risk | 3% | | 12 | vega ceiling | 2.5 per $1k equity |

Plus a mandatory exit guard that never consults a model: close at **50% of defined max loss**,
close at **75% of max profit**, force-close inside **3 DTE**.

Four properties are enforced by construction:

1. **Fail closed.** Every field is read with a pessimistic default — a missing `max_loss` is not
   zero, it is unbounded. NaN and infinity fail every comparison by design.
2. **No short-circuit.** All twelve run even after one fails, so the audit trail shows every
   result rather than only the first problem.
3. **The gate sizes the trade.** `max_contracts()` returns the largest size satisfying breakers
   2, 5 and 6. The gate has no code path that increases a size or widens a limit.
4. **It runs twice** — in the pipeline, and again inside the execution agent on the exact
   proposal being sent, so no refactor or retry can route an unapproved order.

Measured at **1.3 µs** per full twelve-breaker evaluation (~750,000/sec), reproducible on any
machine via `python risk_gate.py`. Cheap enough that bypassing it is never a temptation.

Every decision — each analyst view, proposal, audit, verdict, order and exit — is appended to a
**SHA-256 hash-chained ledger**. Modifying or deleting any historical entry breaks the chain and
`GET /api/ledger/verify` reports the exact index where it broke. For a competition judged on
P&L, that is the difference between results asserted and results independently checkable.

## 4. Alpaca infrastructure — all three surfaces

- **Trading API** (`deflow/alpaca_rest.py`) — written directly against the HTTP surface so the
  multi-leg payload is visible in one place: account, positions, portfolio history, daily bars,
  option-chain snapshots with NBBO and server-side Greeks, and `POST /v2/orders` with
  `order_class="mleg"`. The client **refuses to initialise against a non-paper endpoint** —
  paper-only by construction, not by configuration.
- **Alpaca CLI** (`deflow/alpaca_cli.py`) — the official `github.com/alpacahq/cli` binary is the
  **default order route**, because it is the interface an unattended agent gets deployed behind:
  its own 429/5xx backoff, its own credential resolution, and `--dry-run` to render the exact
  request body without sending it. Every order carries a `--client-order-id`, so a retry after
  an ambiguous failure is rejected as a duplicate rather than opening a second position.
- **MCP server** (`deflow/alpaca_mcp.py`) — Alpaca's official FastMCP server for structured
  discovery, spoken as JSON-RPC over stdio with no SDK dependency, discovering tool names at
  runtime by keyword so a server update cannot break the integration. *(Note: the published
  server declares `fastmcp>=3.1.0` unbounded and dies on import against fastmcp 4.x; Deflow
  launches it pinned to the 3.x line.)*
- **Featherless AI** — serverless open-model inference for the bounded reasoning layer.

## 5. Verification

`python main.py` runs the whole system from a bare clone — it bootstraps a virtualenv, installs
three dependencies, starts the API, serves the dashboard, and begins trading. Without Alpaca
credentials it runs the identical pipeline against a seeded simulated market, so every claim
here is inspectable before a credential is issued; **all simulated figures are labelled
`simulated: true` in the API, the ledger, the dashboard and the terminal, and are never reported
as trading results.**

`python main.py --demo` prints the full six-stage trace for one cycle. `pytest tests/` runs 172
tests written from the attacker's side — 66 of them are attempts to get capital past a breaker.

---

*Paper trading only. Paper-trading results are hypothetical, do not involve actual securities
transactions, and do not guarantee future results. Options carry substantial risk of loss and
are not suitable for every investor.*
