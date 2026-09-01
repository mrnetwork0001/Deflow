"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EventStream } from "@/components/EventStream";
import { Mark } from "@/components/site/chrome";
import { PositionsTable } from "@/components/PositionsTable";
import { RegimeGrid } from "@/components/RegimeGrid";
import { RiskGatePanel } from "@/components/RiskGatePanel";
import { Badge, Meter, Panel, Stat } from "@/components/ui";
import {
  AnalystView, Position, Status, getJSON, money, postJSON, pct, signedMoney, signedPct,
} from "@/lib/api";

export default function Dashboard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [views, setViews] = useState<AnalystView[]>([]);
  const [positions, setPositions] = useState<{ open: Position[]; closed: Position[] }>({ open: [], closed: [] });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([
        getJSON<Status>("/api/status"),
        getJSON<{ open: Position[]; closed: Position[] }>("/api/positions"),
      ]);
      setStatus(s);
      setPositions(p);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "backend unreachable");
    }
  }, []);

  // Analyst views are a separate, slower poll: each one re-reads the chain.
  const refreshViews = useCallback(async () => {
    try {
      const a = await getJSON<{ views: AnalystView[] }>("/api/analysis");
      setViews(a.views);
    } catch { /* transient */ }
  }, []);

  useEffect(() => {
    refresh();
    refreshViews();
    const fast = setInterval(refresh, 5000);
    const slow = setInterval(refreshViews, 60000);
    return () => { clearInterval(fast); clearInterval(slow); };
  }, [refresh, refreshViews]);

  const runCycle = async () => {
    setBusy(true);
    try {
      await postJSON("/api/cycle");
      await Promise.all([refresh(), refreshViews()]);
    } finally {
      setBusy(false);
    }
  };

  if (error && !status) {
    return (
      <main className="grid min-h-screen place-items-center">
        <div className="text-center">
          <div className="text-sm font-bold text-loss">Backend unreachable</div>
          <p className="mt-2 text-xs text-muted">{error}</p>
          <p className="mt-4 text-xs text-muted">Start it with <code className="rounded bg-ink-raised px-1.5 py-0.5 text-warn">python main.py</code></p>
        </div>
      </main>
    );
  }

  const perf = status?.performance;
  const envelope = status?.risk_envelope ?? {};
  const live = status?.mode === "paper";

  return (
    <main className="mx-auto max-w-[1600px] p-4 sm:p-6">
      {/* ---- Header ---------------------------------------------------- */}
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {/* The wordmark is the way back to the marketing site, which is where
            people expect a logo to take them. */}
        <Link href="/" className="group flex items-center gap-2.5" aria-label="Deflow home">
          <Mark size={26} />
          <span className="flex items-baseline gap-3">
            <span className="text-lg font-bold tracking-tight text-gain transition-opacity group-hover:opacity-80">
              DEFLOW
            </span>
            <span className="hidden text-[11px] text-muted sm:inline">
              autonomous multi-agent options desk
            </span>
          </span>
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={live ? "gain" : "warn"}>
            {live ? "Alpaca paper trading" : "simulation — no credentials"}
          </Badge>
          <Badge tone={status?.reasoning.featherless_enabled ? "info" : "muted"}>
            {status?.reasoning.featherless_enabled ? "Featherless AI" : "deterministic ranker"}
          </Badge>
          <Badge tone="muted">route: {status?.execution.route}</Badge>
          <Badge tone={status?.ledger.valid ? "gain" : "loss"}>
            ledger {status?.ledger.entries} · {status?.ledger.valid ? "chain intact" : "CHAIN BROKEN"}
          </Badge>
          <button
            onClick={runCycle}
            disabled={busy}
            className="rounded border border-gain/40 bg-gain/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-gain transition hover:bg-gain/20 disabled:opacity-40"
          >
            {busy ? "running…" : "run cycle"}
          </button>
        </div>
      </header>

      {/* ---- Headline P&L ---------------------------------------------- */}
      <Panel title="Account" className="mb-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Equity" value={money(perf?.equity ?? 0)} sub={`from ${money(perf?.starting_equity ?? 0, 0)}`} />
          <Stat
            label="Total P&L"
            value={signedMoney(perf?.total_pnl ?? 0)}
            tone={(perf?.total_pnl ?? 0) >= 0 ? "gain" : "loss"}
            sub={signedPct(perf?.return_pct ?? 0)}
          />
          <Stat label="Realised" value={signedMoney(perf?.realized_pnl ?? 0)} tone={(perf?.realized_pnl ?? 0) >= 0 ? "gain" : "loss"} />
          <Stat label="Unrealised" value={signedMoney(perf?.unrealized_pnl ?? 0)} tone={(perf?.unrealized_pnl ?? 0) >= 0 ? "gain" : "loss"} />
          <Stat
            label="Win rate"
            value={perf?.closed_positions ? pct(perf.win_rate, 0) : "—"}
            sub={perf?.closed_positions ? `${perf.wins}W / ${perf.losses}L · PF ${perf.profit_factor ?? "n/a"}` : "no closed trades yet"}
          />
          <Stat label="Book delta" value={(perf?.net_delta ?? 0).toFixed(3)} sub={`vega ${(perf?.net_vega ?? 0).toFixed(1)}`} />
        </div>

        {/* Capital at risk against the 6% aggregate ceiling. */}
        <div className="mt-4 border-t border-ink-line pt-3">
          <div className="mb-1.5 flex items-baseline justify-between text-[10px]">
            <span className="text-muted">capital at risk</span>
            <span className="tabular text-body">
              {money(perf?.capital_at_risk ?? 0, 0)} · {(perf?.capital_at_risk_pct ?? 0).toFixed(2)}% of{" "}
              {((envelope.max_aggregate_risk_pct ?? 0.06) * 100).toFixed(0)}% ceiling
            </span>
          </div>
          <Meter value={perf?.capital_at_risk_pct ?? 0} max={(envelope.max_aggregate_risk_pct ?? 0.06) * 100} />
        </div>
      </Panel>

      {/* ---- Regime ------------------------------------------------------ */}
      <div className="mb-4">
        <RegimeGrid views={views} />
      </div>

      {/* ---- Positions + stream ------------------------------------------ */}
      <div className="mb-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <PositionsTable open={positions.open} closed={positions.closed} />
        <EventStream />
      </div>

      {/* ---- Risk gate --------------------------------------------------- */}
      <RiskGatePanel envelope={envelope} />

      <footer className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-ink-line pt-3 text-[10px] text-muted">
        <span>
          {status?.cycles_run ?? 0} cycles · risk gate v{envelope.gate_version} ·{" "}
          {envelope.evaluations ?? 0} evaluations, {envelope.vetoes ?? 0} vetoes
        </span>
        <span>
          Paper trading only. Simulated results are hypothetical and do not represent actual trading.
        </span>
      </footer>
    </main>
  );
}
