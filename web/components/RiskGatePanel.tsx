"use client";

import { useState } from "react";
import { Badge, Panel } from "./ui";
import { Breaker, money, pct, postJSON } from "@/lib/api";

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

interface Verdict {
  approved: boolean;
  reason: string;
  elapsed_us: number;
  breakers: Breaker[];
}

type Envelope = Record<string, any>;

/** A field the envelope may not carry yet. Missing must read as missing. */
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const asPct = (v: unknown, digits = 0) => {
  const n = num(v);
  return n === null ? null : pct(n, digits);
};

const asMoney = (v: unknown) => {
  const n = num(v);
  return n === null ? null : money(n, 0);
};

const asFixed = (v: unknown, digits: number, prefix = "") => {
  const n = num(v);
  return n === null ? null : `${prefix}${n.toFixed(digits)}`;
};

/** Joins the parts that survived; all-missing collapses to null, never to a zero. */
const lim = (...parts: (string | null)[]) => {
  const kept = parts.filter((p): p is string => p !== null && p !== "");
  return kept.length ? kept.join(" · ") : null;
};

/**
 * The twelve, in the order risk_gate.py runs them. `rule` says what each one
 * tests; every number comes from the live envelope, so a breaker whose limit
 * the envelope does not publish shows an em dash rather than a guess. Once a
 * probe returns, the backend's own detail string replaces `rule` on the rows
 * it tripped.
 */
const BREAKERS: { id: number; name: string; rule: string; limit: (e: Envelope) => string | null }[] = [
  {
    id: 1,
    name: "defined_risk_structure",
    rule: "at least two legs, every short covered by a long of the same right",
    limit: () => null,
  },
  {
    id: 2,
    name: "max_loss_2pct",
    rule: "per-trade loss cap, a fixed share of equity",
    limit: (e) => lim(asPct(e.max_portfolio_risk_pct), asMoney(e.max_loss_per_trade)),
  },
  {
    id: 3,
    name: "trade_delta_bound",
    rule: "net delta of the structure on its own",
    limit: (e) => asFixed(e.max_delta_exposure, 2, "±"),
  },
  {
    id: 4,
    name: "probability_of_profit",
    // The rule names the two branches in this order so the paired limit
    // below reads unambiguously.
    rule: "credit: win rate · debit: that floor plus positive expectancy",
    // Breaker 4 applies two different floors, and the shipped probe is a
    // naked call -- which takes the debit branch. Publishing only the credit
    // floor puts "> 65%" in the limit column beside a backend detail string
    // reading "floor 30%": two numbers for one breaker, in one row. The
    // column is 96px, so the pair is compact and the rule carries the labels.
    limit: (e) => {
      const credit = asPct(e.min_probability_of_profit);
      const debit = asPct(e.min_probability_of_profit_debit);
      if (credit === null && debit === null) return null;
      if (debit === null) return `≥ ${credit}`;
      if (credit === null) return `≥ ${debit}`;
      return `≥ ${credit} / ${debit}`;
    },
  },
  {
    id: 5,
    name: "aggregate_risk_6pct",
    rule: "capital at risk across the whole book after the fill",
    limit: (e) => {
      const p = asPct(e.max_aggregate_risk_pct);
      return p === null ? null : `≤ ${p}`;
    },
  },
  {
    id: 6,
    name: "symbol_concentration_3pct",
    rule: "concentration in any one underlying",
    limit: (e) => {
      const p = asPct(e.max_symbol_risk_pct);
      return p === null ? null : `≤ ${p}`;
    },
  },
  {
    id: 7,
    name: "portfolio_delta_bound",
    rule: "net delta of the book after the fill",
    limit: (e) => asFixed(e.max_portfolio_net_delta, 2, "±"),
  },
  {
    id: 8,
    name: "max_open_positions",
    rule: "concurrent open structures",
    limit: (e) => {
      const n = num(e.max_open_positions);
      return n === null ? null : `≤ ${n}`;
    },
  },
  {
    id: 9,
    name: "dte_window",
    rule: "days to expiry at entry",
    limit: (e) => {
      const lo = num(e.dte_window?.[0]);
      const hi = num(e.dte_window?.[1]);
      return lo === null || hi === null ? null : `${lo}–${hi}d`;
    },
  },
  {
    id: 10,
    name: "payoff_quality",
    rule: "credit against wing width, reward:risk for debit",
    limit: (e) => {
      const credit = asPct(e.min_credit_to_width);
      const debit = asFixed(e.min_reward_risk_debit, 1);
      return lim(credit && `≥ ${credit}`, debit && `${debit}×`);
    },
  },
  {
    id: 11,
    name: "daily_drawdown_killswitch",
    rule: "halts new risk once the session is down this far",
    limit: (e) => {
      const p = asPct(e.max_daily_drawdown_pct);
      return p === null ? null : `−${p} day`;
    },
  },
  {
    id: 12,
    name: "vega_ceiling",
    rule: "book vega after the fill, scaled to equity",
    limit: () => null,
  },
];

export function RiskGatePanel({ envelope }: { envelope: Record<string, any> }) {
  const [result, setResult] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const probe = async (proposal: object) => {
    setBusy(true);
    // Clear first: a previous verdict must not sit there reading as this one.
    setResult(null);
    setError(null);
    try {
      setResult(await postJSON<Verdict>("/api/risk/evaluate", proposal));
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  };

  const loaded = Object.keys(envelope ?? {}).length > 0;
  const failed = result?.breakers.filter((b) => !b.passed) ?? [];
  const evaluations = num(envelope?.evaluations);
  const vetoes = num(envelope?.vetoes);

  return (
    <Panel
      title="Deterministic risk gate"
      right={
        <div className="flex items-center gap-2.5">
          {!loaded && (
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
              awaiting envelope
            </span>
          )}
          <Badge tone="info">zero&nbsp;LLM · 12 breakers</Badge>
        </div>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        {/* ── the probe ──────────────────────────────────────────────── */}
        <div className="flex flex-col rounded-lg border border-ink-line bg-ink-raised p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
            Probe
          </div>
          <p className="mt-2.5 font-sans text-[12.5px] leading-[1.65] text-muted">
            Sends a 10-lot naked NVDA call carrying{" "}
            <span className="text-body">$15,000 of undefined downside</span> to the gate running
            right now. It is evaluated against the live book; nothing is routed.
          </p>

          <button
            onClick={() => probe(NAKED_CALL)}
            disabled={busy}
            className="mt-3.5 w-full rounded-md border border-loss/45 bg-loss/10 px-4 py-2.5 font-mono text-[11px] font-bold uppercase tracking-[0.1em] text-loss transition-colors hover:bg-loss/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "evaluating…" : "▸ Probe with a naked call"}
          </button>

          {/* Reserved height so the panel does not jump when the verdict lands. */}
          <div className="mt-3.5 min-h-[172px] rounded-md border border-ink-line bg-ink p-3 font-mono text-[11px]">
            {error ? (
              <div className="text-warn">
                gate unreachable
                <div className="mt-1 break-words text-[10.5px] text-faint">{error}</div>
              </div>
            ) : busy ? (
              <span className="text-faint">running twelve breakers…</span>
            ) : result ? (
              <div className="animate-rise">
                <div className="flex items-baseline justify-between gap-3">
                  <span
                    className={`text-[14px] font-bold uppercase tracking-[0.08em] ${
                      result.approved ? "text-gain" : "text-loss"
                    }`}
                  >
                    {result.approved ? "approved" : "vetoed"}
                  </span>
                  {num(result.elapsed_us) !== null && (
                    <span className="tabular text-[10.5px] text-faint">
                      {result.elapsed_us.toFixed(2)} µs
                    </span>
                  )}
                </div>
                <div className="tabular mt-1 text-[10.5px] text-faint">
                  {failed.length} of {result.breakers.length} breakers tripped
                </div>
                <p className="mt-2.5 font-sans text-[12px] leading-[1.6] text-body">
                  {result.reason}
                </p>
              </div>
            ) : (
              <span className="text-faint">
                awaiting a proposal - the verdict and its timing appear here
              </span>
            )}
          </div>

          <div className="tabular mt-3 border-t border-ink-line pt-2.5 font-mono text-[10px] text-faint">
            {evaluations === null ? "-" : evaluations.toLocaleString()} evaluations ·{" "}
            {vetoes === null ? "-" : vetoes.toLocaleString()} vetoes this session
          </div>
        </div>

        {/* ── the twelve ─────────────────────────────────────────────── */}
        <div className="overflow-hidden rounded-lg border border-ink-line bg-ink-raised">
          <div className="hidden items-baseline gap-3 border-b border-ink-line px-4 py-2 font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint sm:flex">
            <span className="w-5">#</span>
            <span className="w-[184px]">breaker</span>
            <span className="min-w-0 flex-1">rule</span>
            <span className="w-24 text-right">limit</span>
            <span className="w-3" />
          </div>

          <ol className="divide-y divide-ink-line">
            {BREAKERS.map(({ id, name, rule, limit }) => {
              const hit = result?.breakers.find((b) => b.id === id);
              const tripped = hit && !hit.passed;
              const value = loaded ? limit(envelope) : null;
              return (
                <li
                  key={id}
                  className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-[9px] transition-colors duration-500 ${
                    tripped ? "bg-loss/[0.08]" : ""
                  }`}
                >
                  <span className="tabular w-5 shrink-0 font-mono text-[10px] text-faint">
                    {String(id).padStart(2, "0")}
                  </span>
                  <span
                    className={`w-[128px] shrink-0 truncate font-mono text-[11px] sm:w-[184px] sm:text-[11.5px] ${
                      tripped ? "font-semibold text-loss" : "text-body"
                    }`}
                  >
                    {name}
                  </span>

                  <span className="order-last w-full min-w-0 font-sans text-[11.5px] leading-snug text-muted sm:order-none sm:w-auto sm:flex-1 sm:text-[12px]">
                    {tripped ? hit!.detail : rule}
                  </span>

                  <span
                    className={`tabular ml-auto w-20 shrink-0 text-right font-mono text-[11px] sm:w-24 ${
                      value === null ? "text-faint" : tripped ? "text-loss" : "text-body"
                    }`}
                  >
                    {value ?? "-"}
                  </span>

                  {/* Held in the layout at all times so the rows do not reflow on a verdict. */}
                  <span
                    className={`w-3 shrink-0 text-right text-[11px] transition-opacity duration-500 ${
                      hit ? "opacity-100" : "opacity-0"
                    } ${tripped ? "text-loss" : "text-gain"}`}
                  >
                    {tripped ? "✗" : "✓"}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </Panel>
  );
}
