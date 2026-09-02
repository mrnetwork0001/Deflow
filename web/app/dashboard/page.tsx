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
import { MobileMenu } from "@/components/MobileMenu";
import { SectionRail } from "@/components/SectionRail";
import { Badge, Meter, Panel } from "@/components/ui";
import { PnlCard } from "@/components/PnlCard";
import {
  AnalystView, Position, Status, getJSON, money, postJSON, pct, signedMoney, signedPct,
} from "@/lib/api";

function BigStat({
  label, value, sub, tone = "body",
}: { label: string; value: string | null; sub?: string; tone?: "body" | "gain" | "loss" }) {
  const tones = { body: "text-body", gain: "text-gain", loss: "text-loss" };
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{label}</div>
      {/* A missing figure renders as an em dash, never as zero. This dashboard
          is the public face of a system whose argument is that unverified
          numbers are the enemy; showing $0.00 while data loads would be one. */}
      {/* 30px mono puts eleven digits at ~200px; two of those side by side
          overflow a phone and the figures physically collide. Scale with the
          viewport instead of wrapping money across lines. */}
      <div className={`tabular mt-2 font-mono text-[22px] font-bold leading-none sm:text-[30px] ${value ? tones[tone] : "text-faint"}`}>
        {value ?? "-"}
      </div>
      {sub && <div className="mt-2 font-mono text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function SmallStat({
  label, value, sub, tone = "body",
}: { label: string; value: string | null; sub?: string; tone?: "body" | "gain" | "loss" }) {
  const tones = { body: "text-body", gain: "text-gain", loss: "text-loss" };
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{label}</dt>
      <dd className={`tabular mt-1.5 font-mono text-[15px] font-semibold ${value ? tones[tone] : "text-faint"}`}>
        {value ?? "-"}
      </dd>
      {sub && <dd className="mt-0.5 font-mono text-[10px] text-faint">{sub}</dd>}
    </div>
  );
}

function ReopenCountdown({ iso, detail }: { iso?: string | null; detail?: string }) {
  // The backend publishes the reopen instant; older deployments only embed it
  // inside the detail string, so parse that as a fallback.
  const parsed =
    iso ?? detail?.match(/\d{4}-\d{2}-\d{2}T[0-9:.]+(?:[+-]\d{2}:\d{2}|Z)?/)?.[0];
  const target = parsed ? new Date(parsed).getTime() : NaN;

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // Tick every second only while a valid countdown is on screen.
    if (!Number.isFinite(target)) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [target]);

  if (!Number.isFinite(target)) {
    // No parseable instant: the raw detail beats showing nothing.
    return detail ? <span className="font-mono text-[10.5px] text-faint">{detail}</span> : null;
  }

  const remaining = Math.max(0, target - now);
  const h = Math.floor(remaining / 3_600_000);
  const m = Math.floor((remaining % 3_600_000) / 60_000);
  const sec = Math.floor((remaining % 60_000) / 1000);
  // toLocaleString with no arguments resolves to the BROWSER's locale and
  // timezone: a reader in Lagos sees WAT, one in Milan sees CEST -- nobody
  // converts a -04:00 offset in their head.
  const local = new Date(target).toLocaleString(undefined, {
    weekday: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });
  return (
    <span className="tabular font-mono text-[10.5px] text-faint">
      {remaining === 0 ? (
        "opening - waiting for the desk to confirm"
      ) : (
        <>
          opens in{" "}
          <span className="text-warn">
            {h > 0 ? `${h}h ` : ""}{m}m {h === 0 ? `${sec}s ` : ""}
          </span>
          · {local}
        </>
      )}
    </span>
  );
}

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
  // `views` starts empty and refreshViews swallows its error, so views.length === 0
  // covers a first load, a failed poll and a genuinely empty scan identically.
  // Without this flag the rail's "3/5" badge would render "0/0" - a claim about
  // the universe that has never been made.
  const [viewsLoaded, setViewsLoaded] = useState(false);
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
      setViewsLoaded(true);
      // Deliberately not cleared in the catch: a failed poll does not unmake the
      // last good scan, which is still the last thing that was true.
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
  // The broker owns the book. When it has not answered -- which is every
  // restart, until the first call lands -- our own mid-marks are NOT a
  // stand-in for its balance: on 2026-09-01 they said +$375.00 while the
  // account said -$101.50. Blank is the honest render; the badge says why.
  const money$ = perf && perf.mark_source !== "unavailable" ? perf : undefined;
  const envelope = status?.risk_envelope ?? {};
  const live = status?.mode === "paper";

  // Rail badges. Every one of these is null until its own source has answered;
  // SectionRail renders a null as no badge at all, never as 0.
  //
  // Structures reads positions.open.length and NOT perf.open_positions. Both are
  // in scope, and they come from two different responses in the same Promise.all,
  // so a partial failure can leave them one apart. The rail sits directly beside
  // PositionsTable, whose own header renders open.length behind the same
  // loaded={status !== null} gate; matching the visible neighbour beats matching
  // a different response. The next person to add a row will reach for perf -
  // this comment is why not.
  const railCounts = {
    regime: viewsLoaded ? `${views.filter((v) => v.tradeable).length}/${views.length}` : null,
    structures: status !== null ? String(positions.open.length) : null,
    // envelope is `?? {}`, so vetoes is undefined before load and `?? 0` would
    // fabricate a zero. Number.isFinite still lets a genuine zero through.
    gate: Number.isFinite(envelope.vetoes) ? String(envelope.vetoes) : null,
  };

  return (
    <main className="mx-auto max-w-[1600px] p-4 sm:p-6 xl:max-w-[1776px]">
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
          {/* STATUS - read-only. Grouped into one strip with internal
              dividers and no individual borders, so it reads as a readout
              rather than a row of things to press. Every one of these used to
              be a bordered pill identical to the buttons beside them. */}
          <div className="hidden items-stretch divide-x divide-ink-line overflow-hidden rounded-md border border-ink-line bg-ink-raised md:flex">
            {/* Both of these used to assert a mode before the desk had said
                anything - "simulation" and "deterministic" are claims, and a
                null status is not evidence for either. Same three-state shape
                the market item two rows down already uses. */}
            <StatusItem
              dot={status === null ? "bg-faint" : live ? "bg-gain" : "bg-warn"}
              label={status === null ? "-" : live ? "Alpaca paper" : "simulation"}
              title={
                status === null
                  ? "Waiting for the desk to report its trading mode"
                  : live
                    ? "Trading a live Alpaca paper account"
                    : "No credentials - seeded simulated market"
              }
            />
            <StatusItem
              dot={status?.reasoning.featherless_enabled ? "bg-info" : "bg-faint"}
              label={status === null ? "-" : status.reasoning.featherless_enabled ? "Featherless" : "deterministic"}
              title={
                status === null
                  ? "Waiting for the desk to report its reasoning layer"
                  : status.reasoning.featherless_enabled
                    ? `Reasoning layer: ${status.reasoning.model}`
                    : "No model key - using the deterministic ranker"
              }
            />
            <StatusItem
              dot="bg-faint"
              label={status?.execution.route ?? "-"}
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

          {/* ACTIONS - everything below is interactive and looks it. */}
          <Link
            href="/ledger/"
            className={`group hidden items-center gap-2 rounded-md border px-3 py-2 font-mono text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60 md:inline-flex ${
              status?.ledger.valid === false
                ? "border-loss/45 bg-loss/10 text-loss hover:bg-loss/20"
                : "border-ink-hair text-muted hover:border-muted hover:text-body"
            }`}
          >
            <span className="tabular">
              Ledger {status ? status.ledger.entries.toLocaleString() : "-"}
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

          {/* Everything hidden above reappears inside this drawer. */}
          <MobileMenu
            status={status}
            live={live}
            equity={money$ ? money(money$.equity) : null}
            pnl={money$ ? signedMoney(money$.total_pnl) : null}
            pnlTone={money$ ? (money$.total_pnl >= 0 ? "gain" : "loss") : null}
          />
        </div>
      </header>

      {/* ---- Market state -------------------------------------------------
          A grey dot in the status strip was not enough: with the market shut,
          every panel below still animates, the stream still replays and the
          book still marks, so the page reads as a desk that is working when
          it is a desk that is waiting. Say it in words, once, in the one place
          nobody can miss. */}
      {status?.market_open === false && (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-warn/35 bg-warn/[0.07] px-4 py-2.5">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
          <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-warn">
            Market closed
          </span>
          <span className="font-sans text-[12.5px] text-muted">
            The desk is idle - no cycles run and no orders are placed until the
            next session. Positions and P&L below are last marks.
          </span>
          <span className="ml-auto">
            <ReopenCountdown iso={status.market_reopens_at} detail={status.market_detail} />
          </span>
        </div>
      )}

      {/* The rail column and the content column. minmax(0,1fr) here AND min-w-0
          on the content div are both required: a grid item's default
          min-width:auto lets PositionsTable's min-w-[860px] table size the track
          and scroll the whole page sideways.

          This wrapper must NEVER gain overflow-hidden. That is the reflexive fix
          when a horizontal scrollbar appears, and it silently kills the rail's
          position:sticky with no error. The fix is always min-w-0. */}
      <div className="xl:grid xl:grid-cols-[148px_minmax(0,1fr)] xl:gap-x-7">
        <SectionRail
          counts={railCounts}
          working={(status?.working_orders?.length ?? 0) > 0}
          equity={money$ ? money(money$.equity) : null}
          pnl={money$ ? signedMoney(money$.total_pnl) : null}
          pnlTone={money$ ? (money$.total_pnl >= 0 ? "gain" : "loss") : null}
          stale={Boolean(error) && status !== null}
          ledgerBroken={status?.ledger.valid === false}
        />

        <div className="min-w-0">

          {/* ---- Account ----------------------------------------------------
              Equity and P&L are the two numbers anyone opens this page for, so
              they are set larger than the rest rather than sharing a six-column
              grid with book delta.

              The scroll targets below are plain divs, never sections: Panel already
              renders <section aria-label>, and a second region would nest or go
              unnamed. tabIndex={-1} lets a rail row hand focus into the section. */}
          <div id="account" tabIndex={-1} className="scroll-mt-20 focus:outline-none xl:scroll-mt-6">
            <Panel
              title="Account"
              right={
                perf ? (
                  <div className="flex items-center gap-3">
                    <PnlCard />
                    {/* Which basis these figures are on. A money number with no
                        stated source is the thing this project argues against,
                        and the two bases genuinely disagree: on 2026-09-01 our
                        mid-marks read $581.55 against the broker's $405.60 on
                        the same four positions. */}
                    <Badge
                      tone={
                        perf.mark_source === "unavailable"
                          ? "loss"
                          : perf.mark_source !== "alpaca"
                            ? "warn"
                            : (perf.broker?.stale_seconds ?? 0) > 0
                              ? "warn"
                              : "info"
                      }
                    >
                      {perf.mark_source === "unavailable"
                        ? "broker unreachable"
                        : perf.mark_source !== "alpaca"
                          ? "mid marks"
                          : (perf.broker?.stale_seconds ?? 0) > 0
                            ? `broker marks ${Math.round(perf.broker!.stale_seconds!)}s old`
                            : "broker marks"}
                    </Badge>
                    <span className="tabular font-mono text-[10px] text-faint">
                      {perf.closed_positions} closed · {perf.open_positions} open
                    </span>
                  </div>
                ) : null
              }
              className="mb-4"
            >
              <div className="grid gap-6 lg:grid-cols-[1.1fr_1.4fr]">
                <div className="grid min-w-0 grid-cols-2 gap-4 sm:gap-6">
                  <BigStat
                    label="Equity"
                    value={money$ ? money(money$.equity) : null}
                    sub={
                      money$
                        ? `from ${money(money$.starting_equity, 0)}`
                        : perf?.mark_source === "unavailable"
                          ? "broker not answering"
                          : "waiting for the desk"
                    }
                  />
                  <BigStat
                    label="Total P&L"
                    value={money$ ? signedMoney(money$.total_pnl) : null}
                    tone={money$ ? (money$.total_pnl >= 0 ? "gain" : "loss") : "body"}
                    // The mid-mark gap is roughly what crossing every bid/ask
                    // would cost to unwind the book, so it belongs on screen
                    // rather than being thrown away once the broker's figure
                    // takes the headline. Shown only once it rounds to a dollar.
                    sub={
                      money$
                        ? money$.desk_mark &&
                          Math.abs(money$.desk_mark.total_pnl - money$.total_pnl) >= 1
                          ? `${signedPct(money$.return_pct)} · mid ${signedMoney(money$.desk_mark.total_pnl)}`
                          : signedPct(money$.return_pct)
                        : "-"
                    }
                  />
                </div>

                <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
                  <SmallStat label="Realised" value={money$ ? signedMoney(money$.realized_pnl) : null}
                             tone={money$ && money$.realized_pnl < 0 ? "loss" : "gain"} />
                  <SmallStat label="Unrealised" value={money$ ? signedMoney(money$.unrealized_pnl) : null}
                             tone={money$ && money$.unrealized_pnl < 0 ? "loss" : "gain"} />
                  <SmallStat
                    label="Win rate"
                    // A win rate over zero closed trades is not 0%, it is
                    // undefined -- and the API now agrees, sending null.
                    value={perf?.win_rate != null ? pct(perf.win_rate, 0) : null}
                    sub={perf?.closed_positions ? `${perf.wins}W / ${perf.losses}L` : "no closed trades"}
                  />
                  <SmallStat label="Book delta" value={perf ? perf.net_delta.toFixed(3) : null}
                             sub={perf ? `vega ${perf.net_vega.toFixed(1)}` : undefined} />
                </dl>
              </div>

              {/* Capital at risk against the 6% aggregate ceiling. */}
              <div className="mt-6 border-t border-ink-line pt-4">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 font-mono text-[10px]">
                  <span className="uppercase tracking-[0.12em] text-faint">capital at risk</span>
                  <span className="tabular text-muted">
                    {perf ? (
                      <>
                        <span className="text-body">{money(perf.capital_at_risk, 0)}</span>
                        {" · "}
                        {perf.capital_at_risk_pct.toFixed(2)}% of{" "}
                        {((envelope.max_aggregate_risk_pct ?? 0.06) * 100).toFixed(0)}% ceiling
                      </>
                    ) : (
                      "-"
                    )}
                  </span>
                </div>
                {/* Not drawn at all before perf lands, matching Meter's own !usable
                    behaviour and the em dash in the row above. A zero-width bar is a
                    measurement, and there is nothing to measure yet. */}
                {perf && (
                  <Meter
                    value={perf.capital_at_risk_pct}
                    max={(envelope.max_aggregate_risk_pct ?? 0.06) * 100}
                  />
                )}
              </div>
            </Panel>
          </div>

          {/* ---- Equity curve ------------------------------------------------ */}
          <div id="equity" tabIndex={-1} className="mb-4 scroll-mt-20 focus:outline-none xl:scroll-mt-6">
            <EquityCurve
              headline={
                money$
                  ? {
                      equity: money(money$.equity),
                      pnl: signedMoney(money$.total_pnl),
                      retPct: signedPct(money$.return_pct),
                    }
                  : null
              }
            />
          </div>

          {/* ---- Regime ------------------------------------------------------ */}
          <div id="regime" tabIndex={-1} className="mb-4 scroll-mt-20 focus:outline-none xl:scroll-mt-6">
            <RegimeGrid views={views} />
          </div>

          {/* ---- Positions + stream ------------------------------------------
              The anchor rides the existing grid container rather than a new wrapper
              around PositionsTable: the table carries its own min-w-0 as a direct
              grid child, and a wrapper would have to re-carry it or the 1.35fr
              column gets sized by its min-w-[860px]. */}
          <div id="structures" tabIndex={-1} className="mb-4 grid gap-4 scroll-mt-20 focus:outline-none xl:scroll-mt-6 xl:grid-cols-[1.35fr_1fr]">
            <PositionsTable
              open={positions.open}
              closed={positions.closed}
              working={status?.working_orders ?? []}
              loaded={status !== null}
              stale={Boolean(error) && status !== null}
            />
            {/* min-w-0 is mandatory - this div is now the grid item. */}
            <div id="stream" tabIndex={-1} className="min-w-0 scroll-mt-20 focus:outline-none xl:scroll-mt-6">
              <EventStream />
            </div>
          </div>

          {/* ---- Refusals + risk gate ----------------------------------------
              Deliberately adjacent: roughly half of every scan ends in a refusal,
              and the gate is where the last of them happen. Together they are the
              system's actual behaviour, not an absence of it. */}
          <div id="refusals" tabIndex={-1} className="mb-4 scroll-mt-20 focus:outline-none xl:scroll-mt-6">
            <Refusals />
          </div>

          {/* No bottom margin: the footer's mt-6 still supplies the gap. */}
          <div id="gate" tabIndex={-1} className="scroll-mt-20 focus:outline-none xl:scroll-mt-6">
            <RiskGatePanel envelope={envelope} />
          </div>

        </div>
      </div>

      <footer className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-ink-line pt-3 text-[10px] text-muted">
        {/* This line used to read "0 cycles · risk gate vundefined · 0
            evaluations, 0 vetoes" before the first response. Number.isFinite
            rather than ?? so a genuine zero still prints as zero. */}
        <span>
          {status ? status.cycles_run : "-"} cycles · risk gate{" "}
          {envelope.gate_version ? `v${envelope.gate_version}` : "-"} ·{" "}
          {Number.isFinite(envelope.evaluations) ? envelope.evaluations : "-"} evaluations,{" "}
          {Number.isFinite(envelope.vetoes) ? envelope.vetoes : "-"} vetoes
        </span>
        <span>
          Paper trading only. Simulated results are hypothetical and do not represent actual trading.
        </span>
      </footer>
    </main>
  );
}
