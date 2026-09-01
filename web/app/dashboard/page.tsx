"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EquityCurve } from "@/components/EquityCurve";
import { EventStream } from "@/components/EventStream";
import { Wordmark } from "@/components/site/chrome";
import { PositionsTable } from "@/components/PositionsTable";
import { Refusals } from "@/components/Refusals";
import { RegimeGrid } from "@/components/RegimeGrid";
import { RiskGatePanel } from "@/components/RiskGatePanel";
import { Badge, Meter, Panel, Stat } from "@/components/ui";
import {
  AnalystView, Position, Status, getJSON, money, postJSON, pct, signedMoney, signedPct,
} from "@/lib/api";

function StatusItem({ dot, label, title }: { dot: string; label: string; title: string }) {
  return (
    <span
      title={title}
      className="flex items-center gap-2 px-3 py-2 font-mono text-[11px] text-muted"
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

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
        <Link href="/" className="group flex items-center gap-4" aria-label="Deflow home">
          <Wordmark height={30} className="transition-opacity group-hover:opacity-80" />
          <span className="hidden border-l border-ink-line pl-4 font-mono text-[11px] text-muted lg:inline">
            live desk
          </span>
        </Link>
        <div className="flex flex-wrap items-center gap-2.5">
          {/* STATUS — read-only. Grouped into one strip with internal
              dividers and no individual borders, so it reads as a readout
              rather than a row of things to press. Every one of these used to
              be a bordered pill identical to the buttons beside them. */}
          <div className="flex items-stretch divide-x divide-ink-line overflow-hidden rounded-md border border-ink-line bg-ink-raised">
            <StatusItem
              dot={live ? "bg-gain" : "bg-warn"}
              label={live ? "Alpaca paper" : "simulation"}
              title={live ? "Trading a live Alpaca paper account" : "No credentials — seeded simulated market"}
            />
            <StatusItem
              dot={status?.reasoning.featherless_enabled ? "bg-info" : "bg-faint"}
              label={status?.reasoning.featherless_enabled ? "Featherless" : "deterministic"}
              title={
                status?.reasoning.featherless_enabled
                  ? `Reasoning layer: ${status.reasoning.model}`
                  : "No model key — using the deterministic ranker"
              }
            />
            <StatusItem
              dot="bg-faint"
              label={status?.execution.route ?? "—"}
              title="Order routing surface"
            />
            {status?.market_open !== undefined && (
              <StatusItem
                dot={status.market_open ? "bg-gain" : "bg-faint"}
                label={status.market_open ? "open" : "closed"}
                title={status.market_open ? "US market open" : status.market_detail || "US market closed"}
              />
            )}
          </div>

          {/* ACTIONS — everything below is interactive and looks it. */}
          <Link
            href="/ledger/"
            className={`group inline-flex items-center gap-2 rounded-md border px-3 py-2 font-mono text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60 ${
              status?.ledger.valid === false
                ? "border-loss/45 bg-loss/10 text-loss hover:bg-loss/20"
                : "border-ink-hair text-muted hover:border-muted hover:text-body"
            }`}
          >
            <span className="tabular">
              Ledger {status ? status.ledger.entries.toLocaleString() : "—"}
            </span>
            <span className="text-faint group-hover:text-inherit">
              {status?.ledger.valid === false ? "chain broken" : "↗"}
            </span>
          </Link>

          <button
            onClick={runCycle}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md bg-gain px-4 py-2 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-ink transition-colors hover:bg-gain-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gain/50 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {busy && (
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-ink/30 border-t-ink" />
            )}
            {busy ? "running" : "Run cycle"}
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

      {/* ---- Equity curve ------------------------------------------------ */}
      <div className="mb-4">
        <EquityCurve />
      </div>

      {/* ---- Regime ------------------------------------------------------ */}
      <div className="mb-4">
        <RegimeGrid views={views} />
      </div>

      {/* ---- Positions + stream ------------------------------------------ */}
      <div className="mb-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <PositionsTable
          open={positions.open}
          closed={positions.closed}
          working={status?.working_orders ?? []}
        />
        <EventStream />
      </div>

      {/* ---- Refusals + risk gate ----------------------------------------
          Deliberately adjacent: roughly half of every scan ends in a refusal,
          and the gate is where the last of them happen. Together they are the
          system's actual behaviour, not an absence of it. */}
      <div className="mb-4">
        <Refusals />
      </div>

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
