"use client";

import { useEffect, useState } from "react";
import { Status, getJSON } from "@/lib/api";
import { DecisionCard } from "./DecisionCard";
import { GITHUB_URL } from "./chrome";
import { PricePaths } from "./visuals";

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
    <header className="relative overflow-hidden px-6 pb-20 pt-32 sm:pt-40">
      {/* Simulated price paths — the same mathematics the auditor stresses
          proposals with. pointer-events-none so it can never eat a click. */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[620px] opacity-[0.45]">
        <div className="grid-bg absolute inset-0 opacity-40" />
        <PricePaths className="absolute inset-0 h-full w-full animate-drift" width={1400} height={620} />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/40 via-ink/75 to-ink" />
      </div>

      <div className="relative mx-auto max-w-content">
        {/* eyebrow */}
        <div
          className="flex flex-wrap items-center gap-3 font-mono text-[11px] uppercase tracking-[0.18em] animate-rise"
          style={{ animationDelay: "0ms" }}
        >
          <span className="text-gain">00</span>
          <span className="h-px w-10 bg-ink-hair" />
          <span className="text-muted">defined-risk options · alpaca paper trading</span>
          <span className="flex items-center gap-1.5 text-faint">
            <span className={live ? `live-dot ${paper ? "text-gain" : "text-warn"}` : "text-faint"}>●</span>
            {live ? (paper ? "live" : "simulation") : "offline"}
          </span>
        </div>

        <div className="mt-10 grid items-start gap-12 lg:grid-cols-[1.22fr_1fr] lg:gap-14">
          {/* ── left: the argument ─────────────────────────────────────── */}
          <div>
            <h1
              className="font-sans font-bold leading-[0.98] tracking-tightest animate-rise"
              style={{ animationDelay: "60ms", fontSize: "clamp(2.6rem, 6.2vw, 4.6rem)" }}
            >
              <span className="block text-body">An options desk</span>
              <span className="block text-muted">where the AI is the</span>
              <span className="block text-gain">least-trusted component.</span>
            </h1>

            <p
              className="mt-8 max-w-2xl font-sans text-[16.5px] leading-[1.65] text-muted animate-rise"
              style={{ animationDelay: "140ms" }}
            >
              Deflow trades defined-risk option spreads on Alpaca, harvesting the gap between the
              volatility options are priced at and the volatility stocks actually deliver. Four
              agents propose. Twelve deterministic circuit breakers decide.{" "}
              <span className="text-body">
                No model ever produces a number that reaches the broker.
              </span>
            </p>

            <div
              className="mt-9 flex flex-wrap items-center gap-3 animate-rise"
              style={{ animationDelay: "220ms" }}
            >
              <a
                href="/dashboard/"
                className="group inline-flex items-center gap-2 rounded-full bg-gain px-7 py-3.5 font-mono text-[12.5px] font-bold uppercase tracking-[0.08em] text-ink transition-colors hover:bg-gain-dim"
              >
                Launch app
                <span className="transition-transform duration-200 group-hover:translate-x-0.5">↗</span>
              </a>
              <a
                href="/ledger/"
                className="inline-flex items-center gap-2 rounded-full border border-ink-hair px-7 py-3.5 font-mono text-[12.5px] uppercase tracking-[0.08em] text-body transition-colors hover:border-muted"
              >
                <span className="text-faint">&gt;_</span> Verify it
              </a>
            </div>

            <HeroStats status={status} />
          </div>

          {/* ── right: the proof ───────────────────────────────────────── */}
          <div
            className="animate-rise lg:ml-auto lg:w-full lg:max-w-[520px] lg:pt-2"
            style={{ animationDelay: "300ms" }}
          >
            <DecisionCard />
          </div>
        </div>
      </div>
    </header>
  );
}

function HeroStats({ status }: { status: Status | null }) {
  const live = status !== null;

  const items: [string, string, string][] = [
    ["12", "breakers", "zero LLM · fail-closed"],
    ["100%", "defined risk", "no naked options, ever"],
    ["2%", "max per trade", "sized by the gate"],
    [
      live ? status!.ledger.entries.toLocaleString() : "—",
      "decisions logged",
      live && status!.ledger.valid ? "chain verified" : "hash-chained",
    ],
  ];

  return (
    <dl
      className="mt-14 grid grid-cols-2 gap-x-8 gap-y-7 border-t border-ink-line pt-7 sm:grid-cols-4 animate-rise"
      style={{ animationDelay: "380ms" }}
    >
      {items.map(([value, label, sub]) => (
        <div key={label}>
          <dt className="tabular font-mono text-[26px] font-bold leading-none text-body">{value}</dt>
          <dd className="mt-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{label}</dd>
          <dd className="mt-1 font-sans text-[11px] leading-snug text-faint">{sub}</dd>
        </div>
      ))}
    </dl>
  );
}
