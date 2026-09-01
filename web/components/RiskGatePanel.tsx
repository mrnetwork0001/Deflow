"use client";

import { useEffect, useState } from "react";
import { Badge, Empty, Panel } from "./ui";
import { Breaker, getJSON, postJSON } from "@/lib/api";

// A naked call: the canonical thing the gate exists to refuse. Anyone reading
// the dashboard can fire it and watch which breakers trip.
const NAKED_CALL = {
  symbol: "NVDA",
  strategy: "naked_call",
  is_defined_risk_spread: false,
  leg_count: 1,
  contracts: 10,
  max_loss: 15000,
  max_profit: 480,
  net_delta: 0.62,
  probability_of_profit: 0.72,
  dte: 21,
};

export function RiskGatePanel({ envelope }: { envelope: Record<string, any> }) {
  const [result, setResult] = useState<{ approved: boolean; reason: string; elapsed_us: number; breakers: Breaker[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const probe = async (proposal: object) => {
    setBusy(true);
    try {
      setResult(await postJSON("/api/risk/evaluate", proposal));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Deterministic risk gate"
      right={<Badge tone="info">zero&nbsp;LLM · 12 breakers</Badge>}
    >
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px] sm:grid-cols-3">
        <Limit label="Max loss / trade" value={`$${Number(envelope.max_loss_per_trade ?? 0).toLocaleString()}`} />
        <Limit label="Aggregate risk" value={`${((envelope.max_aggregate_risk_pct ?? 0) * 100).toFixed(0)}%`} />
        <Limit label="Per symbol" value={`${((envelope.max_symbol_risk_pct ?? 0) * 100).toFixed(0)}%`} />
        <Limit label="Trade delta" value={`±${envelope.max_delta_exposure}`} />
        <Limit label="Book delta" value={`±${envelope.max_portfolio_net_delta}`} />
        <Limit label="Min P(profit)" value={`${((envelope.min_probability_of_profit ?? 0) * 100).toFixed(0)}%`} />
        <Limit label="DTE window" value={`${envelope.dte_window?.[0]}–${envelope.dte_window?.[1]}d`} />
        <Limit label="Stop / target" value={`${((envelope.stop_loss_pct_of_max_loss ?? 0) * 100).toFixed(0)}% / ${((envelope.profit_target_pct_of_max_profit ?? 0) * 100).toFixed(0)}%`} />
        <Limit label="Kill switch" value={`−${((envelope.max_daily_drawdown_pct ?? 0) * 100).toFixed(0)}% day`} />
      </div>

      <div className="mt-4 flex items-center gap-2 border-t border-ink-line pt-3">
        <button
          onClick={() => probe(NAKED_CALL)}
          disabled={busy}
          className="rounded border border-loss/40 bg-loss/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-loss transition hover:bg-loss/20 disabled:opacity-40"
        >
          Probe with a naked call
        </button>
        <span className="text-[10px] text-muted">
          {envelope.evaluations ?? 0} evaluations · {envelope.vetoes ?? 0} vetoes this session
        </span>
      </div>

      {result && (
        <div className="mt-3 rounded border border-ink-line bg-ink p-3">
          <div className="flex items-center justify-between">
            <Badge tone={result.approved ? "gain" : "loss"}>{result.approved ? "approved" : "vetoed"}</Badge>
            <span className="tabular text-[10px] text-muted">{result.elapsed_us.toFixed(2)} µs</span>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-body">{result.reason}</p>
          <ul className="mt-2 space-y-0.5">
            {result.breakers.map((b) => (
              <li key={b.id} className="flex gap-2 text-[10px] leading-relaxed">
                <span className={b.passed ? "text-gain" : "text-loss"}>{b.passed ? "✓" : "✗"}</span>
                <span className="w-6 shrink-0 text-muted">{b.id}</span>
                <span className={`w-52 shrink-0 ${b.passed ? "text-muted" : "text-loss"}`}>{b.name}</span>
                <span className="text-muted">{b.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function Limit({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-ink-line/50 pb-1">
      <span className="text-muted">{label}</span>
      <span className="tabular font-semibold text-body">{value}</span>
    </div>
  );
}
