# Deflow — Build-in-Public Posts

For the lablab.ai × Alpaca social engagement prize. Tag **@lablabai** and **@AlpacaHQ** on X, and
**lablab.ai** and **Alpaca** on LinkedIn.

> **Ground rule for this file: nothing here claims a number that has not happened.**
>
> Posts 1–3 and 5 describe real events from building this system — the bugs are real bugs, with
> commits behind them. Post 4 is the only one containing performance figures, and it is a
> **template**: run `python scripts/social_post.py` to fill it from the actual hash-chained
> ledger. Do not post it with the brackets still in it, and do not hand-write the numbers.
>
> Judging is on real P&L in a fresh Alpaca paper account. Inventing results in public is both
> disqualifying and the exact failure mode this project was built to prevent.

---

### Post 1 — The thesis

```text
Most AI trading agents fail the same way: the model picks the trade AND sizes it.

Building DEFLOW for the @lablabai × @AlpacaHQ hackathon on one inverted principle —
the LLM is the least-trusted component in the system.

It never produces a number that reaches the broker. Strikes, premiums, Greeks and
position size are all computed from live Alpaca quotes by deterministic code.

The model gets exactly one output: an integer index into a list of spreads it
did not build. And that index is bounds-checked.

Building in public. 🧵

#AITrading #Options #Alpaca #lablabai
```

### Post 2 — Why probability of profit is a trap

```text
A lesson from building DEFLOW on @AlpacaHQ:

Found a credit spread with a 79% probability of profit.
Ran it through 1,000 paths of Merton jump-diffusion.

Expected value: NEGATIVE.

79% of the time you keep $320. The other 21% you lose $1,680. The losing tail is
bigger than all the wins combined.

A high win rate is not an edge. It's a way to lose money slowly and feel good
about it. DEFLOW's auditor now vetoes any structure with negative expectancy
regardless of win rate.

@lablabai #QuantFinance #Options #RiskManagement
```

### Post 3 — Two real bugs

```text
Two bugs I hit building DEFLOW on @AlpacaHQ, both caught by tests, both worth sharing:

1️⃣ My implied-vol solver used (K−S)·e^(−rT) as the no-arbitrage floor for puts.
The real European bound is K·e^(−rT) − S. Every in-the-money put quote landed
under the wrong floor and got rejected as "no market". Silent. Only showed up
against a parity test.

2️⃣ Mark-to-market fell back to Black-Scholes at the ENTRY underlying price when a
leg's quote dropped out. So the leg most likely to have moved was frozen at what
it was worth on day one. It reported +$1,051 on a spread whose max profit is $369.

Defined-risk spreads have hard payoff bounds. I now clamp every mark to them and
flag it, because an unclamped bad mark fires your stop-loss at a price that never
existed.

@lablabai #BuildInPublic #TradingSystems
```

### Post 4 — Results *(TEMPLATE — generate, never hand-write)*

```text
DEFLOW live on a fresh $100,000 @AlpacaHQ paper account.

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

@lablabai #AlgoTrading #Alpaca #AITrading
```

Generate the filled version:

```bash
python scripts/social_post.py
```

### Post 5 — Ship

```text
DEFLOW is shipped for the @lablabai × @AlpacaHQ AI Trading Agents Hackathon 🏁

An autonomous options desk that trades the variance risk premium — the gap between
the volatility options are priced at and the volatility stocks actually deliver.

✅ 4 agents: analyst → structurer → adversarial auditor → executor
✅ 12 deterministic circuit breakers, zero LLM, microseconds, fail-closed
✅ Alpaca Trading API + official CLI (mleg orders) + FastMCP server
✅ Every decision hash-chained and independently verifiable
✅ Refusals logged as loudly as fills
✅ One command from a bare clone: python main.py

The most useful thing it does is refuse. Roughly half of all symbol-cycles end in
no trade — each one logged with the numbers that produced it.

Repo + demo 👇 MIT licensed.

#AITrading #Options #Alpaca #lablabai
```

---

## Posting notes

- Post 3 works best as a carousel or thread — the parity identity and the clamped-mark screenshot
  are the shareable part.
- Screenshot `python main.py --demo` for post 1: the twelve breaker lines with real numbers beside
  them are the single most legible artefact this project produces.
- For post 4, screenshot the dashboard header — mode badge, equity, and the ledger chain-status
  badge in one frame.
