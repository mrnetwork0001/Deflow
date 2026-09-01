"use client";

import React from "react";

export function Panel({
  title, right, children, className = "",
}: { title: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-ink-line bg-ink-raised ${className}`}>
      <header className="flex items-center justify-between border-b border-ink-line px-4 py-2.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({
  label, value, tone = "body", sub,
}: { label: string; value: React.ReactNode; tone?: "body" | "gain" | "loss" | "warn" | "info"; sub?: string }) {
  const tones = { body: "text-body", gain: "text-gain", loss: "text-loss", warn: "text-warn", info: "text-info" };
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted">{label}</div>
      <div className={`tabular mt-1 text-xl font-semibold ${tones[tone]}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function Badge({
  children, tone = "muted",
}: { children: React.ReactNode; tone?: "muted" | "gain" | "loss" | "warn" | "info" }) {
  const tones = {
    muted: "border-ink-line text-muted",
    gain: "border-gain/40 bg-gain/10 text-gain",
    loss: "border-loss/40 bg-loss/10 text-loss",
    warn: "border-warn/40 bg-warn/10 text-warn",
    info: "border-info/40 bg-info/10 text-info",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** Horizontal utilisation bar. `warnAt` flips the colour as a limit approaches. */
export function Meter({ value, max, warnAt = 0.8 }: { value: number; max: number; warnAt?: number }) {
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  const tone = ratio >= 1 ? "bg-loss" : ratio >= warnAt ? "bg-warn" : "bg-gain";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink">
      <div className={`h-full rounded-full transition-all duration-500 ${tone}`} style={{ width: `${ratio * 100}%` }} />
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-8 text-center text-xs text-muted">{children}</div>;
}
