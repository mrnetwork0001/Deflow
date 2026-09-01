"use client";

import { useEffect, useState } from "react";
import { Status, getJSON } from "@/lib/api";
import { ButtonLink, GITHUB_URL, Pill } from "./chrome";
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
    <header className="relative overflow-hidden px-5 pb-24 pt-36 sm:pt-44">
      {/* Simulated price paths, faded into the page. Same mathematics the
          auditor stresses proposals with -- not decoration for its own sake. */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[560px] opacity-[0.5]">
        <div className="grid-bg absolute inset-0 opacity-40" />
        <PricePaths
          className="absolute inset-0 h-full w-full animate-drift"
          width={1400}
          height={520}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/30 via-ink/70 to-ink" />
      </div>

      <div className="relative mx-auto max-w-content">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={live ? (paper ? "gain" : "warn") : "muted"}>
            <span className={live ? "live-dot" : ""}>●</span>
            {live ? (paper ? "Trading live on Alpaca paper" : "Simulation mode") : "Desk offline"}
          </Pill>
          <Pill>lablab.ai × Alpaca hackathon</Pill>
        </div>

        <h1 className="mt-8 max-w-4xl font-sans text-[42px] font-bold leading-[1.05] tracking-tightest text-body sm:text-[64px]">
          An options desk where the AI is the{" "}
          <span className="text-gain">least-trusted component</span>.
        </h1>

        <p className="mt-7 max-w-2xl font-sans text-[17px] leading-[1.65] text-muted">
          Deflow trades defined-risk option spreads on Alpaca, harvesting the gap between the
          volatility options are priced at and the volatility stocks actually deliver. Four agents
          propose. Twelve deterministic circuit breakers decide.{" "}
          <span className="text-body">No model ever produces a number that reaches the broker.</span>
        </p>

        <div className="mt-10 flex flex-wrap items-center gap-3">
          <ButtonLink href="/dashboard/">Launch the desk</ButtonLink>
          <ButtonLink href={GITHUB_URL} variant="ghost" external>Read the source</ButtonLink>
        </div>

        <HeroStats status={status} />
      </div>
    </header>
  );
}

function HeroStats({ status }: { status: Status | null }) {
  const live = status !== null;
  const p = status?.performance;

  const items: [string, string, string][] = [
    ["Circuit breakers", "12", "zero-LLM, fail-closed"],
    ["Gate latency", "1.3 µs", "reproducible benchmark"],
    ["Defined risk", "100%", "no naked options, ever"],
    [
      "Decisions logged",
      live ? status!.ledger.entries.toLocaleString() : "hash-chained",
      live && status!.ledger.valid ? "chain verified intact" : "tamper-evident",
    ],
  ];

  return (
    <dl className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ink-line bg-ink-line lg:grid-cols-4">
      {items.map(([label, value, sub]) => (
        <div key={label} className="bg-ink-card px-5 py-5">
          <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{label}</dt>
          <dd className="tabular mt-2 font-mono text-[22px] font-bold text-body">{value}</dd>
          <dd className="mt-1 font-sans text-[11.5px] text-muted">{sub}</dd>
        </div>
      ))}
    </dl>
  );
}
