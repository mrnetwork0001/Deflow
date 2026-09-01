"use client";

import { useEffect, useState } from "react";
import { LedgerEntry, getJSON } from "@/lib/api";

/**
 * The hero's proof panel: the desk's most recent real decision.
 *
 * Deliberately not a mockup. A marketing card showing a specific trade with
 * specific numbers asserts that the trade happened, and this project's whole
 * argument is that unverified claims are the enemy — so it reads the actual
 * ledger and, when there is nothing to show, says so rather than inventing a
 * plausible one.
 */

interface Decision {
  symbol: string;
  strategy: string;
  contracts: number | null;
  dte: number | null;
  strikes: number[];
  maxLoss: number | null;
  maxProfit: number | null;
  pop: number | null;
  netDelta: number | null;
  breakersPassed: number | null;
  breakersTotal: number | null;
  elapsedUs: number | null;
  approved: boolean;
  reason: string;
  routed: boolean;
  at: string;
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

function extract(entries: LedgerEntry[]): Decision | null {
  // Newest first: the last gate verdict is the interesting one, and the
  // proposal that produced it sits alongside in the same payload.
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i];
    if (e.event !== "risk_gate") continue;
    const p: Record<string, any> = e.payload ?? {};
    const load: Record<string, any> = p.payload ?? {};

    // Did the order actually route? The execution entry follows the verdict.
    const routed = entries
      .slice(i + 1)
      .some((n) => n.event === "execution" && n.payload?.submitted === true);

    return {
      symbol: String(p.symbol ?? load.symbol ?? ""),
      strategy: String(load.strategy ?? "").replace(/_/g, " "),
      contracts: num(load.contracts),
      dte: num(load.dte),
      strikes: [],
      maxLoss: num(load.max_loss),
      maxProfit: num(load.max_profit),
      pop: num(load.probability_of_profit),
      netDelta: num(load.net_delta),
      breakersPassed: num(p.breakers_passed),
      breakersTotal: num(p.breakers_total),
      elapsedUs: num(p.elapsed_us),
      approved: p.approved === true,
      reason: String(p.reason ?? ""),
      routed,
      at: String(e.at ?? ""),
    };
  }
  return null;
}

export function DecisionCard() {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "offline">("loading");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const page = await getJSON<{ entries: LedgerEntry[] }>("/api/ledger?limit=120");
        if (!alive) return;
        const found = extract(page.entries ?? []);
        setDecision(found);
        setState(found ? "ready" : "empty");
      } catch {
        if (alive) setState((s) => (s === "ready" ? "ready" : "offline"));
      }
    };
    load();
    const t = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const pass = decision?.approved ?? false;

  return (
    <div className="overflow-hidden rounded-2xl border border-ink-line bg-ink-raised/80 backdrop-blur-sm">
      {/* header */}
      <div className="flex items-center justify-between gap-3 border-b border-ink-line px-5 py-3.5">
        <div className="flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.16em] text-muted">
          <span className={state === "ready" ? "live-dot text-gain" : "text-faint"}>●</span>
          {decision ? `gate · ${decision.symbol}` : "gate · standing by"}
        </div>
        <span
          className={`rounded-full border px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.12em] ${
            state !== "ready"
              ? "border-ink-hair text-faint"
              : pass
                ? "border-gain/45 bg-gain/10 text-gain"
                : "border-loss/45 bg-loss/10 text-loss"
          }`}
        >
          {state !== "ready" ? "idle" : pass ? (decision?.routed ? "routed" : "approved") : "vetoed"}
        </span>
      </div>

      <div className="space-y-4 p-5">
        {/* the structure */}
        <div className="rounded-xl border border-ink-line bg-ink/70 p-4 font-mono text-[12.5px]">
          {state === "ready" && decision ? (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-gain">
                  {decision.strategy}
                  {decision.contracts !== null && (
                    <span className="text-body"> · {decision.contracts} contracts</span>
                  )}
                </span>
                {decision.dte !== null && <span className="text-faint">{decision.dte} DTE</span>}
              </div>
              <div className="mt-2.5 leading-relaxed text-muted">
                <span className="text-faint">verdict</span>{" "}
                <span className={pass ? "text-gain" : "text-loss"}>
                  {decision.breakersPassed ?? "—"}/{decision.breakersTotal ?? 12} breakers
                </span>
                {decision.elapsedUs !== null && (
                  <span className="text-faint"> in {decision.elapsedUs.toFixed(2)} µs</span>
                )}
              </div>
              {!pass && decision.reason && (
                <div className="mt-1.5 line-clamp-2 text-[11.5px] leading-snug text-loss/90">
                  {decision.reason}
                </div>
              )}
            </>
          ) : (
            <div className="text-[12px] leading-relaxed text-faint">
              {state === "offline"
                ? "desk unreachable — nothing to show"
                : state === "empty"
                  ? "no decision recorded yet · the desk trades on US market hours"
                  : "loading the last decision…"}
            </div>
          )}
        </div>

        {/* metrics */}
        <dl className="space-y-2.5">
          <Metric
            label="max loss"
            value={decision?.maxLoss != null ? `$${decision.maxLoss.toLocaleString()}` : "—"}
            fill={decision?.maxLoss != null ? Math.min(decision.maxLoss / 2000, 1) : 0}
            tone="loss"
            cap="2% cap"
          />
          <Metric
            label="probability of profit"
            value={decision?.pop != null ? `${(decision.pop * 100).toFixed(0)}%` : "—"}
            fill={decision?.pop ?? 0}
            tone="gain"
            cap="65% floor"
          />
          <Metric
            label="net delta"
            value={decision?.netDelta != null ? decision.netDelta.toFixed(3) : "—"}
            fill={decision?.netDelta != null ? Math.min(Math.abs(decision.netDelta) / 0.35, 1) : 0}
            tone="info"
            cap="±0.35"
          />
        </dl>

        {/* the point */}
        <div className="flex items-center justify-between gap-3 rounded-xl border border-gain/25 bg-gain/[0.06] px-4 py-3">
          <span className="font-mono text-[11.5px] text-gain">
            no model output reached the broker
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-faint">
            zero LLM
          </span>
        </div>
      </div>

      {/* footer */}
      <div className="flex items-center justify-between gap-3 border-t border-ink-line px-5 py-3 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
        <span>deterministic · hash-chained</span>
        <span>{decision?.at ? decision.at.slice(11, 19) + " UTC" : "paper trading"}</span>
      </div>
    </div>
  );
}

function Metric({
  label, value, fill, tone, cap,
}: { label: string; value: string; fill: number; tone: "gain" | "loss" | "info"; cap: string }) {
  const bar = { gain: "bg-gain", loss: "bg-loss", info: "bg-info" }[tone];
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 font-mono text-[10.5px]">
        <dt className="uppercase tracking-[0.1em] text-faint">{label}</dt>
        <dd className="tabular font-semibold text-body">{value}</dd>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink">
          <div
            className={`h-full rounded-full transition-all duration-700 ${bar}`}
            style={{ width: `${Math.max(0, Math.min(fill, 1)) * 100}%` }}
          />
        </div>
        <span className="w-16 shrink-0 text-right font-mono text-[9.5px] text-faint">{cap}</span>
      </div>
    </div>
  );
}
