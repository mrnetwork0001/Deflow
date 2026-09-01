"use client";

import React from "react";

/**
 * Controls handed to a Panel's header slot inherit the desk's focus ring, so
 * keyboard focus looks the same in every panel without each caller restating
 * it. Written as whole class names so Tailwind's scanner still sees them.
 */
// The pseudo-class must sit INSIDE the arbitrary variant. Written the other
// way round -- [&_button]:focus-visible:ring-1 -- Tailwind emits
// `.cls:focus-visible button`, binding :focus-visible to this wrapper div,
// which is not focusable and can never match. The whole rule is then dead CSS
// that looks correct in the source.
const SLOT_FOCUS =
  "[&_button:focus-visible]:outline-none [&_button:focus-visible]:ring-1 [&_button:focus-visible]:ring-gain/60 " +
  "[&_a:focus-visible]:outline-none [&_a:focus-visible]:ring-1 [&_a:focus-visible]:ring-gain/60";

export function Panel({
  title, right, children, className = "",
}: { title: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    // No .lift and no hover state: a panel is a housing, not a control, and
    // must not read as something to press.
    <section aria-label={title} className={`rounded-xl border border-ink-line bg-ink-card ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-ink-line px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* The marketing sections mark a heading with a green eyebrow; here
              the accent is a tick, so the title itself stays quiet. */}
          <span aria-hidden className="h-2.5 w-[2px] shrink-0 rounded-full bg-gain/80" />
          <h2 className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted">
            {title}
          </h2>
        </div>
        {right && <div className={`flex shrink-0 items-center gap-2 ${SLOT_FOCUS}`}>{right}</div>}
      </header>
      {/* Deliberately not overflow-hidden: panels host readouts that draw
          outside the body box (the equity curve's hover tooltip). Wide content
          scrolls inside its own container instead. */}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({
  label, value, tone = "body", sub,
}: { label: string; value: React.ReactNode; tone?: "body" | "gain" | "loss" | "warn" | "info"; sub?: string }) {
  const tones = { body: "text-body", gain: "text-gain", loss: "text-loss", warn: "text-warn", info: "text-info" };
  // An absent value is shown as absent, never coloured or coerced to zero.
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="min-w-0">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div
        className={`tabular mt-1.5 font-mono text-[19px] font-semibold leading-none ${
          missing ? "text-faint" : tones[tone]
        }`}
      >
        {missing ? "-" : value}
      </div>
      {/* Reserved even when empty so a row of stats keeps one baseline as
          subtitles appear and disappear with the data. */}
      <div className="tabular mt-1.5 min-h-[13px] font-mono text-[10.5px] leading-[13px] text-faint">{sub}</div>
    </div>
  );
}

/** A state marker. Pill-shaped and hoverless, so it never reads as a button. */
export function Badge({
  children, tone = "muted",
}: { children: React.ReactNode; tone?: "muted" | "gain" | "loss" | "warn" | "info" }) {
  const tones = {
    muted: "border-ink-hair text-muted",
    gain: "border-gain/40 bg-gain/10 text-gain",
    loss: "border-loss/40 bg-loss/10 text-loss",
    warn: "border-warn/40 bg-warn/10 text-warn",
    info: "border-info/40 bg-info/10 text-info",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[3px] font-mono text-[10px] font-semibold uppercase tracking-[0.1em] ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** Horizontal utilisation bar. `warnAt` flips the colour as a limit approaches. */
export function Meter({ value, max, warnAt = 0.8 }: { value: number; max: number; warnAt?: number }) {
  // A non-finite reading or an unknown ceiling leaves the track empty rather
  // than drawing a bar that would be read as a real measurement.
  const usable = Number.isFinite(value) && Number.isFinite(max) && max > 0;
  const ratio = usable ? Math.min(Math.max(value / max, 0), 1) : 0;
  const tone = ratio >= 1 ? "bg-loss" : ratio >= warnAt ? "bg-warn" : "bg-gain";
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      {...(usable ? { "aria-valuemax": max, "aria-valuenow": value } : {})}
      className="relative h-1.5 w-full overflow-hidden rounded-full bg-ink"
    >
      {usable && (
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${tone}`}
          style={{ width: `${ratio * 100}%` }}
        />
      )}
      {/* The warn threshold is drawn, not just implied by a colour change, so
          the bar reads as an instrument with a marked ceiling. Painted last so
          it stays visible once the fill passes it. */}
      {warnAt > 0 && warnAt < 1 && (
        <div className="absolute inset-y-0 w-px bg-ink-hair" style={{ left: `${warnAt * 100}%` }} />
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    // Height is reserved so a panel does not resize when its first data lands.
    // The caller supplies the wording, which is what separates empty from
    // loading from offline.
    <div className="flex min-h-[92px] items-center justify-center px-4 py-6 text-center">
      <p className="max-w-[46ch] font-sans text-[12.5px] leading-[1.7] text-muted">{children}</p>
    </div>
  );
}
