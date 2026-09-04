# Deflow - Build-in-Public Posts

The record of what was actually posted while the desk traded, for the lablab.ai x Alpaca
social-engagement track. Tag **@lablabai** and **@AlpacaHQ** on X.

## What was posted

| # | Day | Post | Link | Submitted |
|---|-----|------|------|-----------|
| 1 | Tue 1 Sep | The thesis - the model must not size the trade. Named neither the project nor the strategy | [link](https://x.com/encrypt_wizard/status/2094702482274312352) | slot 1 |
| 2 | Wed 2 Sep | Day-1 autopsy thread: the fill asymmetry, the flattering dashboard, the edge that said no | [link](https://x.com/encrypt_wizard/status/2094968034544738620) | slot 2 |
| 3 | Wed 2 Sep | Session 2 settled: +$1,102 with zero orders placed | [link](https://x.com/encrypt_wizard/status/2095242422645362921) | slot 3 |
| 4 | Thu 3 Sep | Day 3: the measurement beat the thesis, three bugs fixed in public, the flatten pre-announced | [link](https://x.com/encrypt_wizard/status/2095351339077234808) | - |
| 5 | Thu 3 Sep | First exits ever fired: 3 closed, 3 winners, $2,273.18 realised. Quotes post 4 | [link](https://x.com/encrypt_wizard/status/2095607829566832847) | slot 4 |
| 6 | Fri 4 Sep | Launch thread: final result and the demo video | pending the flatten | slot 5 |

Six posts, five submission slots. Post 4 is not submitted directly because post 5 quotes it -
the flatten promise a judge follows from the launch thread is one click away either way.

**The reveal was staged deliberately.** Post 1 named neither the project nor the strategy,
with 40+ teams competing at the time. The name, the architecture and the variance-premium
thesis went public on day 3, once there were trades on the tape to point at.

---

## The ground rule

> **No post claims a number that has not happened.**
>
> Every figure published came from the broker or from the hash-chained ledger at the moment
> of posting - never estimated, never rounded up, never hand-written. `scripts/social_post.py`
> exists to fill a results post from the live ledger for exactly this reason.
>
> Judging is on real P&L in a fresh Alpaca paper account. Inventing results in public is both
> disqualifying and the exact failure mode this project was built to prevent. Day one closed
> at **-$101.50** and was posted as such, in full, the same evening.

---

## The launch thread (day 4)

Posted after the mandate flatten completes, so every figure in it is settled rather than
marked. Placeholders in brackets are filled from the dashboard and the ledger at posting time.

**1/4 - result, with the demo video attached**

```text
7 days. One autonomous options desk. It's done.

Deflow traded a live Alpaca paper account unattended all week for the
@lablabai x @AlpacaHQ hackathon - four AI agents proposing, twelve
deterministic breakers deciding, Qwen2.5-72B on @FeatherlessAI doing the
reasoning. No model ever touched capital.

Final: [+X.XX%]. [N] round trips, [N] winners, all settled before the deadline.

Three minutes on how it works.
```

**2/4 - the receipts**

```text
Every number, session by session, from the broker - not from my own marks:

Mon  -$101.50    the day the bugs surfaced
Tue  +$1,282.53  zero orders placed; it just let winners run
Wed  +$792.15    first three exits ever fired. 3 for 3.
Thu  [flatten]   everything closed, on schedule

But the number I care about: it refused to trade [N] times.

[N] round trips out of [N] refusals. That ratio IS the product. A desk that
must trade every cycle is a random number generator with commissions.

All [N] decisions are on a hash-chained ledger you can verify yourself.
```

**3/4 - what actually went wrong**

```text
Things I shipped this week that were broken, found live, and fixed in public:

- A stop-loss that could only close winners. Exits were priced off the entry
  price, so a losing position's close order was unfillable by construction.
  The one order it existed to send.

- A dashboard flattering me by $476, because it marked at the mid while the
  broker marked at liquidation.

- A daily kill-switch whose baseline silently never rolled - found by reading
  a competitor's build-in-public thread about their own bug.

- A mandate that would have frozen the desk permanently after the deadline.
  Caught by someone asking a simple question I hadn't.

None of that is in the demo video. It's the actual week.
```

**4/4 - what happens now**

```text
24 hours ago I posted that Deflow would flatten its entire book today at
15:00 WAT. It did - [N] positions, on schedule, on the record. Unrealised
profit on the day a mandate ends is a mark, and a mark is not a result.

But the books closing isn't the desk closing. The mandate expires, ordinary
trading resumes, and it's back at work tomorrow morning. Anyone checking next
week finds a live desk, not a screenshot.

Open source, MIT - including the limitations I couldn't fix in time,
written down.

Built solo, in public, bugs posted as loudly as the wins.
Thanks @lablabai @AlpacaHQ @FeatherlessAI
```
