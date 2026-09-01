"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/api";
import { Section } from "./chrome";
import { RevealGroup } from "./Reveal";

const BREAKERS: [number, string, string][] = [
  [1, "defined_risk_structure", "every short covered by a long of the same right"],
  [2, "max_loss_2pct", "≤ 2% of equity per trade"],
  [3, "trade_delta_bound", "|net delta| ≤ 0.35"],
  [4, "probability_of_profit", "65% win rate for credit; expectancy for debit"],
  [5, "aggregate_risk_6pct", "≤ 6% of equity at risk across the book"],
  [6, "symbol_concentration_3pct", "≤ 3% in any one underlying"],
  [7, "portfolio_delta_bound", "book |delta| ≤ 1.20"],
  [8, "max_open_positions", "≤ 6 concurrent structures"],
  [9, "dte_window", "7–60 days to expiry"],
  [10, "payoff_quality", "credit ≥ 15% of wing width"],
  [11, "daily_drawdown_killswitch", "halts new risk at −3% on the session"],
  [12, "vega_ceiling", "|vega| ≤ 2.5 per $1,000 of equity"],
];

/** The canonical thing the gate exists to refuse. */
const NAKED_CALL = {
  symbol: "NVDA", strategy: "naked_call", is_defined_risk_spread: false,
  leg_count: 1, contracts: 10, max_loss: 15000, max_profit: 480,
  net_delta: 0.62, probability_of_profit: 0.72, dte: 21,
};

interface Breaker { id: number; name: string; passed: boolean; detail: string }
interface Verdict { approved: boolean; elapsed_us: number; breakers: Breaker[]; reason: string }

export function Gate() {
  const [result, setResult] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);

  const probe = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await fetch(`${API_BASE}/api/risk/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(NAKED_CALL),
      });
      if (!r.ok) throw new Error();
      // A hold just long enough that the verdict reads as an event rather than
      // appearing to have been there all along.
      await new Promise((res) => setTimeout(res, 260));
      setResult(await r.json());
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setBusy(false);
    }
  };

  const failed = result?.breakers.filter((b) => !b.passed) ?? [];

  return (
    <Section
      id="gate"
      eyebrow="The risk gate"
      title={
        <>
          Twelve breakers.
          <br />
          <span className="text-muted">No network, no prompt, no model.</span>
        </>
      }
      lead="risk_gate.py imports nothing but the standard library. Given the same proposal and the same book it returns the same verdict, forever."
    >
      <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        {/* ── the probe ──────────────────────────────────────────────── */}
        <div className="flex flex-col rounded-xl border border-ink-line bg-ink-card p-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
            Test it yourself
          </div>
          <p className="mt-3 font-sans text-[13.5px] leading-[1.7] text-muted">
            This sends a genuinely hostile order to the gate running right now: a 10-lot naked NVDA
            call carrying <span className="text-body">$15,000 of undefined downside</span>. Nothing
            is routed and no state changes.
          </p>

          <button
            onClick={probe}
            disabled={busy}
            className="mt-5 w-full rounded-lg border border-loss/45 bg-loss/10 px-5 py-3 font-mono text-[12px] font-bold uppercase tracking-[0.1em] text-loss transition-colors hover:bg-loss/20 disabled:opacity-40"
          >
            {busy ? "evaluating…" : "▸ Fire a naked call at the gate"}
          </button>

          {/* Reserved height so the layout does not jump when the verdict lands. */}
          <div className="mt-5 min-h-[168px] rounded-lg border border-ink-line bg-ink p-4 font-mono text-[11.5px]">
            {offline ? (
              <span className="text-warn">
                desk unreachable — start it with <span className="text-body">python main.py</span>
              </span>
            ) : busy ? (
              <span className="text-faint">running twelve breakers…</span>
            ) : result ? (
              <div className="animate-rise">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[15px] font-bold text-loss">VETOED</span>
                  <span className="tabular text-faint">
                    {result.elapsed_us.toFixed(2)} µs
                  </span>
                </div>
                <div className="mt-1 text-faint">
                  {failed.length} of {result.breakers.length} breakers tripped
                </div>
                <ul className="mt-3 space-y-1.5">
                  {failed.slice(0, 4).map((b) => (
                    <li key={b.id} className="flex gap-2 leading-snug">
                      <span className="text-loss">✗</span>
                      <span className="text-loss/90">{b.name}</span>
                    </li>
                  ))}
                  {failed.length > 4 && (
                    <li className="text-faint">+{failed.length - 4} more</li>
                  )}
                </ul>
              </div>
            ) : (
              <span className="text-faint">
                awaiting a proposal — the verdict and its timing appear here
              </span>
            )}
          </div>
        </div>

        {/* ── the twelve ─────────────────────────────────────────────── */}
        <ol className="divide-y divide-ink-line overflow-hidden rounded-xl border border-ink-line bg-ink-card">
          <RevealGroup step={38} y={8}>
          {BREAKERS.map(([id, name, limit]) => {
            const hit = result?.breakers.find((b) => b.id === id);
            const tripped = hit && !hit.passed;
            const cleared = hit && hit.passed;
            return (
              <li
                key={id}
                className={`flex items-baseline gap-3 px-5 py-[11px] transition-colors duration-500 ${
                  tripped ? "bg-loss/[0.08]" : ""
                }`}
              >
                <span className="w-5 shrink-0 font-mono text-[10px] text-faint">
                  {String(id).padStart(2, "0")}
                </span>
                <span
                  className={`w-52 shrink-0 font-mono text-[11.5px] ${
                    tripped ? "font-semibold text-loss" : "text-body"
                  }`}
                >
                  {name}
                </span>
                <span className="flex-1 font-sans text-[12.5px] leading-snug text-muted">
                  {tripped ? hit!.detail : limit}
                </span>
                <span
                  className={`w-4 shrink-0 text-right text-[12px] transition-opacity duration-500 ${
                    hit ? "opacity-100" : "opacity-0"
                  } ${tripped ? "text-loss" : "text-gain"}`}
                >
                  {tripped ? "✗" : cleared ? "✓" : ""}
                </span>
              </li>
            );
          })}
          </RevealGroup>
        </ol>
      </div>

      {/* ── the three properties ───────────────────────────────────────── */}
      <div className="mt-4 grid gap-px overflow-hidden rounded-xl border border-ink-line bg-ink-line md:grid-cols-3">
        {[
          ["Fails closed",
           "Every field is read with a pessimistic default. A missing max_loss is not zero, it is unbounded. NaN and infinity fail every comparison by design."],
          ["Never short-circuits",
           "All twelve run even after one fails, because a veto naming only the first problem hides the rest from the audit trail."],
          ["Sizes the trade itself",
           "max_contracts() derives position size from breakers 2, 5 and 6. The model never chooses size, and the gate can only shrink or refuse."],
        ].map(([t, d]) => (
          <div key={t} className="bg-ink-card p-6">
            <h3 className="font-mono text-[12px] font-bold text-gain">{t}</h3>
            <p className="mt-2.5 font-sans text-[13px] leading-[1.7] text-muted">{d}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}
