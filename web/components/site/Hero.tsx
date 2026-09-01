"use client";

import { useEffect, useState } from "react";
import { Status, getJSON } from "@/lib/api";
import { ButtonLink, GITHUB_URL, Pill } from "./chrome";
import { PricePaths } from "./visuals";

// The `rise` keyframe fills backwards, so an animation-delay would hold an
// element at opacity 0 until it fires. `motion-reduce:animate-none` drops the
// animation entirely rather than shortening it, which leaves the resting
// state -- fully visible, untranslated -- as the default for anyone who has
// asked for less motion, and for anyone whose CSS never loads.
const RISE = "animate-rise motion-reduce:animate-none";
const after = (ms: number) => ({ animationDelay: `${ms}ms` });

export function Hero() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    const load = () => getJSON<Status>("/api/status").then(setStatus).catch(() => setStatus(null));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const live = status !== null;
  const paper = status?.mode === "paper";

  return (
    <header className="relative overflow-hidden px-5 pb-24 pt-36 sm:pt-44">
      {/* Simulated price paths, faded into the page. Same mathematics the
          auditor stresses proposals with -- not decoration for its own sake. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] select-none overflow-hidden opacity-[0.5] sm:h-[560px]"
      >
        <div className="grid-bg absolute inset-0 opacity-40" />
        {/* Bled 2rem past each side: animate-drift slides the paths sideways,
            and without the bleed it would expose a bare strip at one edge.
            The wrapper clips it, so the bleed can never widen the page. */}
        <PricePaths
          className="absolute -left-8 top-0 h-full w-[calc(100%+4rem)] animate-drift"
          width={1400}
          height={520}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/30 via-ink/70 to-ink" />
      </div>

      <div className="relative mx-auto max-w-content">
        <div className={`flex flex-wrap items-center gap-2 ${RISE}`} style={after(0)}>
          <Pill tone={live ? (paper ? "gain" : "warn") : "muted"}>
            <span className={live ? "live-dot" : ""}>●</span>
            {live ? (paper ? "Trading live on Alpaca paper" : "Simulation mode") : "Desk offline"}
          </Pill>
          <Pill>lablab.ai × Alpaca hackathon</Pill>
        </div>

        {/* Fluid rather than a 42px/64px step: the two-line break lands badly
            at the widths in between, and 42px overflows a 320px viewport. */}
        <h1
          className={`mt-8 max-w-4xl text-balance font-sans text-[clamp(2.125rem,4.4vw+1.35rem,4rem)] font-bold leading-[1.06] tracking-tightest text-body ${RISE}`}
          style={after(70)}
        >
          An options desk where the AI is the{" "}
          <span className="text-gain">least-trusted component</span>.
        </h1>

        <p
          className={`mt-7 max-w-2xl font-sans text-[16px] leading-[1.65] text-muted sm:text-[17px] ${RISE}`}
          style={after(140)}
        >
          Deflow trades defined-risk option spreads on Alpaca, harvesting the gap between the
          volatility options are priced at and the volatility stocks actually deliver. Four agents
          propose. Twelve deterministic circuit breakers decide.{" "}
          <span className="text-body">No model ever produces a number that reaches the broker.</span>
        </p>

        <div className={`mt-10 flex flex-wrap items-center gap-3 ${RISE}`} style={after(210)}>
          <ButtonLink href="/dashboard/">Launch the desk</ButtonLink>
          <ButtonLink href={GITHUB_URL} variant="ghost" external>Read the source</ButtonLink>
        </div>

        <div className={RISE} style={after(280)}>
          <HeroStats status={status} />
        </div>
      </div>
    </header>
  );
}

/**
 * Dividers are drawn on the cells themselves rather than by a `gap-px`
 * background showing through: a 1px grid gap lands on fractional device pixels
 * and drops or doubles hairlines depending on zoom and DPR. Explicit edges are
 * snapped by the same rounding as the cell, so every seam is exactly one rule.
 *
 * The layout is 2-up below `lg` and 4-up at or above it, and the item count is
 * fixed at four, so the seams reduce to: a left edge on the second cell of each
 * visual row, and a top edge only while the grid is wrapped to two rows.
 */
function seams(i: number) {
  const rules = ["border-ink-line"];
  if (i % 2 === 1) rules.push("border-l");            // 2-up: split each pair
  if (i >= 2) rules.push("border-t", "lg:border-t-0"); // 2-up: split the rows
  if (i % 4 !== 0) rules.push("lg:border-l");          // 4-up: split all four
  return rules.join(" ");
}

function HeroStats({ status }: { status: Status | null }) {
  const live = status !== null;

  const items: [string, string, string][] = [
    ["Circuit breakers", "12", "zero-LLM, fail-closed"],
    ["Gate latency", "microseconds", "run risk_gate.py to measure"],
    ["Defined risk", "100%", "no naked options, ever"],
    [
      "Decisions logged",
      live ? status!.ledger.entries.toLocaleString() : "hash-chained",
      live && status!.ledger.valid ? "chain verified intact" : "tamper-evident",
    ],
  ];

  return (
    <dl className="mt-16 grid grid-cols-2 overflow-hidden rounded-xl border border-ink-line bg-ink-card lg:grid-cols-4">
      {items.map(([label, value, sub], i) => (
        <div key={label} className={`px-4 py-5 sm:px-5 ${seams(i)}`}>
          <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{label}</dt>
          {/* Values here are words as often as numbers ("microseconds"), and a
              half-width column at 320px cannot hold one at 22px. */}
          <dd className="tabular mt-2 break-words font-mono text-[clamp(0.95rem,3.6vw,1.375rem)] font-bold leading-tight text-body">
            {value}
          </dd>
          <dd className="mt-1 font-sans text-[11.5px] leading-snug text-muted">{sub}</dd>
        </div>
      ))}
    </dl>
  );
}
