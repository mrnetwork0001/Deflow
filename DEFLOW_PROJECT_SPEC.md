# Deflow — Technical Specification

> **Event:** lablab.ai × Alpaca AI Trading Agents Hackathon (28 Aug – 4 Sep 2026)
> **Author:** Ifeanyichukwu Onwo ([@mrnetwork0001](https://github.com/mrnetwork0001))
> **License:** MIT · **Stack:** Python 3.11+ · FastAPI · Next.js 14 · Alpaca Trading API + CLI + MCP
> **Account:** fresh Alpaca paper account, $100,000 starting balance

This document describes what the system does and why it is built the way it is. For setup and
usage see [README.md](README.md); for the submission summary see
[ONE_PAGE_WRITEUP.md](ONE_PAGE_WRITEUP.md).

---

## 1. Problem

Autonomous LLM trading agents fail in two characteristic ways. Either the model has direct
execution authority and a hallucination becomes an order, or the strategy is undefined-risk
(naked options, unhedged directional bets) and a single gap move erases weeks of gains.

Deflow addresses both structurally rather than by prompting. It trades **only** defined-risk
multi-leg option spreads, and it places every order behind a deterministic gate that no model
can influence.

## 2. Strategy: the variance risk premium

Under the risk-neutral measure every vertical spread is priced at fair value — simulating a
candidate at its own implied volatility yields ≈ 0 expected value for every trade. That is
correct, and useless for selection.

Deflow's thesis is that implied volatility systematically overstates delivered volatility. Each
candidate is therefore simulated under two measures, and the dollar gap between them is the edge:

- **Risk-neutral** (σ = implied): what the market says the structure is worth.
- **Physical** (σ = realised HV60): what it is worth if the underlying keeps moving as it has.

A structure is only tradable if its expectancy under the physical measure is positive.
Probability of profit alone is explicitly *not* sufficient: a 79%-win-rate credit spread with a
negative mean is rejected.

### Regime → structure

| Stance | Trigger | Bias | Structure |
|---|---|---|---|
| Sell premium | IV − HV ≥ +2.0 pts **and** IV rank ≥ 40% | bullish | Bull put spread |
| | | bearish | Bear call spread |
| | | neutral | Iron condor |
| Buy convexity | IV − HV ≤ −1.0 pt **and** IV rank ≤ 55% | bullish | Bull call spread |
| | | bearish | Bear put spread |
| | | neutral | *no trade* |
| Stand down | otherwise | any | *no trade* |

**Universe:** SPY, QQQ, IWM, NVDA, AAPL, MSFT, AMD, TSLA — chosen for penny-wide option markets.
A defined-risk desk lives or dies on being able to exit.

**IV rank basis.** Alpaca does not serve historical implied volatility. Deflow ranks current ATM
IV against the trailing year of *realised* vol from day one (`basis="hv_proxy"`), while recording
observed ATM IV each cycle; after 20 sessions it switches to true implied-vol history
(`basis="iv_history"`). The basis is always reported with the number.

## 3. Pipeline

Six stages per symbol per cycle. Every stage writes to the ledger, including the ones that
refuse.

| # | Stage | Module | Responsibility |
|---|---|---|---|
| 0 | Position management | `portfolio.py` | Mark the book; honour exit-guard closes |
| 1 | Analyst | `agents/analyst.py` | Regime, variance premium, stance, bias, conviction |
| 2 | Structurer | `agents/structurer.py` | Delta-targeted strikes, width ladder, liquidity floor, gate-derived sizing |
| 3 | Reasoning | `llm.py` | Featherless AI picks one index or abstains |
| 4 | Auditor | `agents/auditor.py` | Independent Greeks, 1,000-path stress, fatal objections |
| 5 | Risk gate | `risk_gate.py` | Twelve breakers, zero LLM |
| 6 | Executor | `agents/executor.py` | Re-runs the gate, then routes to Alpaca |

### The model's contract

> The model never produces a number that reaches the broker.

The reasoning layer receives finished, priced candidates and returns exactly: one integer index
(bounds-checked), one confidence float (clamped to [0,1]), one paragraph of prose. Any failure —
missing key, timeout, unparseable JSON, out-of-range index — falls back to the deterministic
composite ranker, and the ledger records which brain decided.

### Structurer construction rules

- Liquidity floor: bid ≥ $0.05, bid/ask width ≤ 15% of mid, open interest ≥ 100.
- Short-leg delta ladder: 0.16 / 0.20 / 0.25 / 0.30 (credit); long 0.50–0.70, short 0.20–0.30 (debit).
- Wing widths: 1.0% / 1.5% / 2.0% / 3.0% of spot, so the ladder scales from NVDA to SPY.
- Expiry: restricted to 21–45 DTE when the chain offers it.
- **Wing geometry is enforced by construction** — strike search is restricted to the correct side
  of the short leg, so a target outside the listed range cannot collapse onto the short strike
  and silently produce a naked position.
- **Gate-aware**: candidates that could not pass breaker 10 are never emitted. The gate stays
  authoritative and runs regardless.

Scoring weights: expectancy 0.26, variance edge 0.17, liquidity 0.18, tail quality 0.13,
probability 0.12, DTE fit 0.07, delta fit 0.04, conviction 0.03.

## 4. Risk gate

`risk_gate.py`, standard library only. Twelve breakers; see
[README](README.md#the-risk-gate) for the full table. Key properties:

- **Fail closed** — pessimistic defaults; NaN/inf fail every comparison by design.
- **No short-circuit** — all twelve run, so the audit trail is complete.
- **The gate sizes the trade** — `max_contracts()` derives size from breakers 2, 5 and 6.
- **Runs twice** — in the pipeline and again inside the executor.
- **~1.3 µs** per evaluation, reproducible via `python risk_gate.py`.

Exit guard (never model-consulted): −50% of max loss, +75% of max profit, forced close ≤ 3 DTE.

## 5. Auditability

Every decision is appended to a SHA-256 hash-chained JSONL ledger. Each record carries the hash
of its predecessor; `verify()` recomputes the chain and reports the index of any break. Exposed
at `GET /api/ledger/verify`.

Events recorded: `cycle_start`, `analyst_view`, `candidates_built`, `reasoning_choice`, `audit`,
`risk_gate`, `execution`, `exit`, `cycle_end`.

## 6. Alpaca integration

| Surface | Module | Role |
|---|---|---|
| Trading API | `alpaca_rest.py` | Account, positions, bars, option chain, `mleg` orders. Refuses non-paper endpoints. |
| Alpaca CLI (`github.com/alpacahq/cli`) | `alpaca_cli.py` | **Default order route.** Own backoff, `--dry-run`, `--client-order-id` idempotency. |
| MCP server (FastMCP) | `alpaca_mcp.py` | Structured discovery over JSON-RPC/stdio, runtime tool-name resolution. |
| Featherless AI | `llm.py` | Bounded reasoning layer. |

Known upstream issue: `alpaca-mcp-server` 2.3.0 declares `fastmcp>=3.1.0` unbounded and fails to
import against fastmcp 4.x. Deflow pins the launch to `fastmcp>=3.1,<4`.

## 7. Operating modes

| Mode | Trigger | Behaviour |
|---|---|---|
| `paper` | Alpaca credentials present | Live paper trading, real market data |
| `simulation` | no credentials | Seeded synthetic market, identical pipeline, everything tagged `simulated: true` |

Simulation exists so the system is inspectable before a credential is issued. Its output is
never presented as a trading result.

## 8. Submission checklist

- [x] Public GitHub repository, MIT licensed
- [x] Autonomous agent on Alpaca Trading API
- [x] Alpaca MCP server **and** CLI both integrated
- [x] Options strategies throughout (100% defined-risk multi-leg)
- [x] Featherless AI (partner technology) integrated
- [x] One-page write-up — [ONE_PAGE_WRITEUP.md](ONE_PAGE_WRITEUP.md)
- [x] Web dashboard + demo application URL
- [ ] **Fresh** paper account ID, $100,000 balance — replace the placeholder in the write-up
- [ ] 3-minute video presentation
- [ ] Slide presentation and cover image
- [ ] Up to 5 social posts — [SOCIAL_ENGAGEMENT_POSTS.md](SOCIAL_ENGAGEMENT_POSTS.md)
