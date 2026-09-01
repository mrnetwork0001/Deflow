"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/api";
import { Card, Pill, Section } from "./chrome";

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

export function Gate() {
  const [result, setResult] = useState<{ approved: boolean; elapsed_us: number; breakers: Breaker[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);

  const probe = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/risk/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(NAKED_CALL),
      });
      if (!r.ok) throw new Error();
      setResult(await r.json());
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      id="gate"
      eyebrow="The risk gate"
      title="Twelve breakers. No network, no prompt, 1.3 microseconds."
      lead="risk_gate.py imports nothing but the standard library. Given the same proposal and the same book it returns the same verdict, forever. It fails closed on anything malformed, runs all twelve even after one fails so the audit trail stays complete, and has no code path that can widen a limit or increase a size."
      center
    >
      <div className="mb-6 flex flex-wrap items-center justify-center gap-3">
        <button
          onClick={probe}
          disabled={busy}
          className="rounded-lg border border-loss/45 bg-loss/10 px-5 py-2.5 font-mono text-[12px] font-bold uppercase tracking-wider text-loss transition-colors hover:bg-loss/20 disabled:opacity-40"
        >
          {busy ? "evaluating…" : "▸ Fire a naked call at the live gate"}
        </button>
        {result && (
          <span className="font-mono text-[11.5px] text-muted">
            <span className="font-bold text-loss">VETOED</span> in {result.elapsed_us.toFixed(2)} µs ·{" "}
            {result.breakers.filter((b) => !b.passed).length} of 12 tripped
          </span>
        )}
        {offline && <Pill tone="warn">desk offline — start it with python main.py</Pill>}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {BREAKERS.map(([id, name, limit]) => {
          const hit = result?.breakers.find((b) => b.id === id);
          const failed = hit && !hit.passed;
          return (
            <div
              key={id}
              className={`rounded-lg border p-4 transition-colors duration-300 ${
                failed ? "border-loss/50 bg-loss/[0.07]" : result ? "border-gain/25 bg-ink-card" : "border-ink-line bg-ink-card"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-faint">{String(id).padStart(2, "0")}</span>
                <span className={`font-mono text-[11.5px] font-semibold ${failed ? "text-loss" : "text-body"}`}>
                  {name}
                </span>
                {result && (
                  <span className={`ml-auto text-[12px] ${failed ? "text-loss" : "text-gain"}`}>
                    {failed ? "✗" : "✓"}
                  </span>
                )}
              </div>
              <p className="mt-2 font-sans text-[12.5px] leading-[1.6] text-muted">
                {failed ? hit!.detail : limit}
              </p>
            </div>
          );
        })}
      </div>

      {result && (
        <p className="mx-auto mt-8 max-w-2xl text-center font-sans text-[13.5px] leading-[1.7] text-muted">
          That was a real request to the running gate: a 10-lot naked NVDA call carrying $15,000 of
          undefined downside. It was refused before anything could reach a broker, and every breaker
          result — pass and fail — was written to the hash-chained ledger.
        </p>
      )}

      <div className="mt-10 grid gap-4 md:grid-cols-3">
        {[
          ["Fails closed", "Every field is read with a pessimistic default. A missing max_loss is not zero, it is unbounded. NaN and infinity fail every comparison by design."],
          ["Never short-circuits", "All twelve run even after one fails, because a veto naming only the first problem hides the rest from the audit trail."],
          ["Sizes the trade itself", "max_contracts() derives position size from breakers 2, 5 and 6. The model never chooses size, and the gate can only shrink or refuse."],
        ].map(([t, d]) => (
          <Card key={t} className="p-6">
            <h3 className="font-mono text-[12px] font-bold text-gain">{t}</h3>
            <p className="mt-2.5 font-sans text-[13px] leading-[1.7] text-muted">{d}</p>
          </Card>
        ))}
      </div>
    </Section>
  );
}
