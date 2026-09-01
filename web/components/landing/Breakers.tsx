"use client";

import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";

const FALLBACK: [number, string, string][] = [
  [1, "defined_risk_structure", "every short covered by a long of the same right"],
  [2, "max_loss_2pct", "≤ 2% of equity per trade"],
  [3, "trade_delta_bound", "|net delta| ≤ 0.35"],
  [4, "probability_of_profit", "≥ 65%, from the simulated win rate"],
  [5, "aggregate_risk_6pct", "≤ 6% of equity at risk across the book"],
  [6, "symbol_concentration_3pct", "≤ 3% in any one underlying"],
  [7, "portfolio_delta_bound", "book |delta| ≤ 1.20"],
  [8, "max_open_positions", "≤ 6 concurrent structures"],
  [9, "dte_window", "7–60 days to expiry"],
  [10, "payoff_quality", "credit ≥ 15% of wing width"],
  [11, "daily_drawdown_killswitch", "halts new risk at −3% on the session"],
  [12, "vega_ceiling", "|vega| ≤ 2.5 per $1,000 of equity"],
];

/** The naked call the gate exists to refuse. Fired at the live backend. */
const NAKED_CALL = {
  symbol: "NVDA", strategy: "naked_call", is_defined_risk_spread: false,
  leg_count: 1, contracts: 10, max_loss: 15000, max_profit: 480,
  net_delta: 0.62, probability_of_profit: 0.72, dte: 21,
};

interface Breaker { id: number; name: string; passed: boolean; detail: string }

export function Breakers() {
  const [result, setResult] = useState<{ approved: boolean; reason: string; elapsed_us: number; breakers: Breaker[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);

  const probe = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${window.location.origin}/api/risk/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(NAKED_CALL),
      });
      if (!response.ok) throw new Error();
      setResult(await response.json());
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {FALLBACK.map(([id, name, limit]) => {
          const hit = result?.breakers.find((b) => b.id === id);
          const failed = hit && !hit.passed;
          return (
            <div
              key={id}
              className={`rounded-lg border p-3.5 transition ${
                failed ? "border-loss/50 bg-loss/[0.07]" : result ? "border-gain/25 bg-ink-raised" : "border-ink-line bg-ink-raised"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-muted">{String(id).padStart(2, "0")}</span>
                <span className={`font-mono text-[11px] font-semibold ${failed ? "text-loss" : "text-body"}`}>
                  {name}
                </span>
                {result && (
                  <span className={`ml-auto text-[11px] ${failed ? "text-loss" : "text-gain"}`}>
                    {failed ? "✗" : "✓"}
                  </span>
                )}
              </div>
              <p className="mt-1.5 font-sans text-[12px] leading-snug text-muted">
                {failed ? hit!.detail : limit}
              </p>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          onClick={probe}
          disabled={busy}
          className="rounded-md border border-loss/45 bg-loss/10 px-4 py-2 font-mono text-[11px] font-bold uppercase tracking-wider text-loss transition hover:bg-loss/20 disabled:opacity-40"
        >
          {busy ? "evaluating…" : "▸ Fire a naked call at the gate"}
        </button>
        {result && (
          <span className="font-mono text-[11px] text-muted">
            <span className="font-bold text-loss">VETOED</span> in {result.elapsed_us.toFixed(2)} µs ·{" "}
            {result.breakers.filter((b) => !b.passed).length} of 12 breakers tripped
          </span>
        )}
        {offline && (
          <span className="font-mono text-[11px] text-warn">
            backend offline — start it with <code className="text-body">python main.py</code>
          </span>
        )}
      </div>

      {result && (
        <p className="mt-4 max-w-2xl font-sans text-[13px] leading-relaxed text-muted">
          That was a real request to the running gate: a 10-lot naked NVDA call with $15,000 of
          undefined downside. It was refused before anything could reach a broker, and every
          breaker result — pass and fail — was written to the hash-chained ledger.
        </p>
      )}
    </>
  );
}
