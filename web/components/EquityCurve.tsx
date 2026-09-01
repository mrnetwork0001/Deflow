"use client";

import React, { useEffect, useId, useMemo, useState } from "react";
import {
  EquityCurve as EquityCurveData,
  getJSON,
  money,
  pointMillis,
  signedMoney,
  signedPct,
} from "@/lib/api";
import { Badge, Panel, Stat } from "./ui";

// The viewBox is stretched to the container by preserveAspectRatio="none", so
// these units are arbitrary — only their ratios matter.
const VW = 1000;
const VH = 100;

// Token hexes, repeated here because SVG paint attributes cannot take Tailwind
// classes. Keep in sync with tailwind.config.ts.
const GAIN = "#00e08a";
const LOSS = "#ff5a5a";
const HAIR = "#262b33"; // ink-hair — the dashed base reference
const CROSS = "#7c8595"; // muted — the scrub crosshair

// One height for the plot well in every state, so loading, offline, empty and
// a drawn curve all occupy the same box and the panel never resizes under the
// reader when a poll lands.
const WELL = "h-44 sm:h-52";

const stamp = (ms: number) =>
  new Date(ms).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-GB", { hour12: false });

interface Plotted {
  fx: number; // 0..1 across the chart, left to right
  fy: number; // 0..1 down the chart, top to bottom
  ms: number;
  equity: number;
  pnl: number;
}

interface Geometry {
  pts: Plotted[];
  line: string;
  area: string;
  baseFy: number;
  base: number;
  last: Plotted;
  up: boolean;
}

function geometry(data: EquityCurveData | null): Geometry | null {
  const clean = (data?.points ?? [])
    .map((p) => ({ ms: pointMillis(p.t), equity: p.equity, pnl: p.pnl }))
    // A single malformed row from the ledger must not poison the whole curve.
    .filter((p) => Number.isFinite(p.ms) && Number.isFinite(p.equity))
    .sort((a, b) => a.ms - b.ms);

  if (clean.length < 2) return null;

  const base = Number.isFinite(data?.base_value) ? (data as EquityCurveData).base_value : clean[0].equity;

  // The base line is drawn, so it belongs in the domain — otherwise a big run
  // either way would push the reference off-canvas.
  let min = base;
  let max = base;
  for (const p of clean) {
    if (p.equity < min) min = p.equity;
    if (p.equity > max) max = p.equity;
  }

  // A flat series (or a single repeated value) has zero range; inventing a pad
  // keeps every later division defined.
  const spread = max - min;
  const pad = spread > 0 ? spread * 0.08 : Math.max(Math.abs(max) * 0.08, 1);
  const lo = min - pad;
  const hi = max + pad;
  const range = hi - lo;

  const first = clean[0].ms;
  const span = clean[clean.length - 1].ms - first;
  const n = clean.length;

  const pts: Plotted[] = clean.map((p, i) => ({
    ...p,
    // Bars stamped at the same instant would collapse to one x; fall back to
    // even spacing so the curve stays readable.
    fx: span > 0 ? (p.ms - first) / span : i / (n - 1),
    fy: 1 - (p.equity - lo) / range,
  }));

  const line = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${(p.fx * VW).toFixed(2)},${(p.fy * VH).toFixed(2)}`)
    .join(" ");
  const area = `${line} L${(pts[n - 1].fx * VW).toFixed(2)},${VH} L${(pts[0].fx * VW).toFixed(2)},${VH} Z`;

  const last = pts[n - 1];
  return { pts, line, area, baseFy: 1 - (base - lo) / range, base, last, up: last.equity >= base };
}

/** Shared shell for the non-drawing states, so all four wells are one size. */
function Well({ children }: { children: React.ReactNode }) {
  return (
    <div className={`flex ${WELL} items-center justify-center rounded-lg border border-ink-line bg-ink px-4`}>
      <div className="text-center">{children}</div>
    </div>
  );
}

export function EquityCurve() {
  const [data, setData] = useState<EquityCurveData | null>(null);
  const [error, setError] = useState("");
  const [readAt, setReadAt] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  // useId keeps the gradient unique if the panel is ever mounted twice; its
  // colons are stripped because the id is referenced from a url().
  const gradient = `eq-fill-${useId().replace(/:/g, "")}`;

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const next = await getJSON<EquityCurveData>("/api/equity-curve");
        if (!alive) return;
        setData(next);
        setReadAt(Date.now());
        setError("");
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "backend unreachable");
      }
    };
    load();
    const poll = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(poll);
    };
  }, []);

  const chart = useMemo(() => geometry(data), [data]);

  // A poll that lands while the pointer rests can shorten the series, so the
  // held index is re-validated rather than trusted.
  const held = chart && hover !== null ? chart.pts[hover] ?? null : null;

  // The last good payload is still on screen while the poll is failing. It is
  // dimmed, badged and dated below, because it must not read as current.
  const stale = Boolean(error && data);
  const offline = Boolean(error && !data);

  const track = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!chart) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    // Bounding rect, not clientX alone: the SVG is stretched to the container,
    // so viewBox units and screen pixels are unrelated.
    const frac = (e.clientX - rect.left) / rect.width;
    let best = 0;
    let bestDelta = Infinity;
    for (let i = 0; i < chart.pts.length; i++) {
      const delta = Math.abs(chart.pts[i].fx - frac);
      if (delta < bestDelta) {
        bestDelta = delta;
        best = i;
      }
    }
    setHover(best);
  };

  // The tooltip is the only place the per-point figures exist, so the scrub is
  // reachable from the keyboard as well as the pointer.
  const keys = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!chart) return;
    const end = chart.pts.length - 1;
    const to = (i: number) => {
      e.preventDefault();
      setHover(Math.min(end, Math.max(0, i)));
    };
    const from = hover ?? end;
    if (e.key === "ArrowLeft") to(from - 1);
    else if (e.key === "ArrowRight") to(from + 1);
    else if (e.key === "Home") to(0);
    else if (e.key === "End") to(end);
    else if (e.key === "Escape") setHover(null);
  };

  const stroke = chart?.up ? GAIN : LOSS;

  const header = (
    <>
      {stale && <Badge tone="warn">stale</Badge>}
      {offline && <Badge tone="loss">offline</Badge>}
      {data && <Badge tone={data.source === "alpaca" ? "info" : "muted"}>{data.source}</Badge>}
    </>
  );

  let well: React.ReactNode;

  if (offline) {
    well = (
      <Well>
        <div className="font-mono text-[11px] font-bold uppercase tracking-[0.14em] text-loss">
          Curve unavailable
        </div>
        <p className="mt-2 break-words font-mono text-[11px] text-muted">{error}</p>
        <p className="mx-auto mt-3 max-w-[44ch] font-sans text-[12.5px] leading-[1.7] text-faint">
          Showing nothing beats showing a number we cannot verify.
        </p>
      </Well>
    );
  } else if (!data) {
    well = (
      <Well>
        <span className="flex items-center gap-2 font-mono text-[11px] text-faint">
          <span className="live-dot h-1.5 w-1.5 rounded-full bg-faint" />
          Reading the curve…
        </span>
      </Well>
    );
  } else if (!chart) {
    // Points the backend recorded, not points the curve could use: the two
    // differ only when a row is malformed, and claiming the smaller number
    // would hide that.
    const recorded = data.points?.length ?? 0;
    well = (
      <Well>
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">No curve yet</div>
        <p className="mx-auto mt-2.5 max-w-[46ch] font-sans text-[12.5px] leading-[1.7] text-muted">
          Not enough history yet. The curve fills in as the desk trades.
        </p>
        <p className="tabular mt-2.5 font-mono text-[10.5px] text-faint">
          {recorded} point{recorded === 1 ? "" : "s"} recorded · 2 needed to draw a line
        </p>
      </Well>
    );
  } else {
    well = (
      <div className="rounded-lg border border-ink-line bg-ink p-3 transition-colors hover:border-ink-hair">
        {/* No .lift: the curve is scrubbed, and a surface that rises 2px under
            a moving cursor moves the reading away from the pointer. The hover
            affordance is the border, the focus affordance is the ring. */}
        <div
          className={`relative ${WELL} w-full cursor-crosshair touch-pan-y select-none rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60 ${
            stale ? "opacity-60" : ""
          }`}
          tabIndex={0}
          role="img"
          aria-label={
            `Equity curve, ${chart.pts.length} points from ${stamp(chart.pts[0].ms)} to ${stamp(chart.last.ms)}. ` +
            `Latest equity ${money(chart.last.equity)}, P&L ${signedMoney(chart.last.pnl)} against a base of ${money(chart.base, 0)}. ` +
            `Arrow keys read one point at a time.`
          }
          onPointerMove={track}
          onPointerDown={track}
          onPointerLeave={() => setHover(null)}
          onPointerCancel={() => setHover(null)}
          onKeyDown={keys}
          onBlur={() => setHover(null)}
        >
          <svg
            className="absolute inset-0 h-full w-full overflow-visible"
            viewBox={`0 0 ${VW} ${VH}`}
            preserveAspectRatio="none"
            aria-hidden
          >
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
                <stop offset="100%" stopColor={stroke} stopOpacity="0" />
              </linearGradient>
            </defs>

            <path d={chart.area} fill={`url(#${gradient})`} />

            {/* vectorEffect throughout: preserveAspectRatio="none" would otherwise
                scale stroke widths and dashes with the container. */}
            <line
              x1="0"
              x2={VW}
              y1={chart.baseFy * VH}
              y2={chart.baseFy * VH}
              stroke={HAIR}
              strokeWidth="1"
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />

            {held && (
              <line
                x1={held.fx * VW}
                x2={held.fx * VW}
                y1="0"
                y2={VH}
                stroke={CROSS}
                strokeWidth="1"
                strokeOpacity="0.45"
                vectorEffect="non-scaling-stroke"
              />
            )}

            <path
              d={chart.line}
              fill="none"
              stroke={stroke}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>

          {/* Labels and dots live in HTML, not SVG: the same stretch that lets
              the curve fill the container would distort <text> and flatten a
              circle into an ellipse. */}
          <div
            className="pointer-events-none absolute right-0 -translate-y-1/2 bg-ink/90 px-1 font-mono text-[9.5px] uppercase tracking-[0.12em] text-faint"
            style={{ top: `${chart.baseFy * 100}%` }}
          >
            base <span className="tabular">{money(chart.base, 0)}</span>
          </div>

          {/* The latest reading is marked while nothing is held, so the end of
              the series is findable without scrubbing to it. */}
          {!held && (
            <div
              className="pointer-events-none absolute h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{
                left: `${chart.last.fx * 100}%`,
                top: `${chart.last.fy * 100}%`,
                background: stroke,
                boxShadow: `0 0 0 3px ${stroke}22`,
              }}
            />
          )}

          {held && (
            <>
              <div
                className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                  left: `${held.fx * 100}%`,
                  top: `${held.fy * 100}%`,
                  background: stroke,
                  boxShadow: `0 0 0 3px ${stroke}22`,
                }}
              />
              <div
                className="pointer-events-none absolute top-0 whitespace-nowrap rounded-md border border-ink-hair bg-ink-card px-2.5 py-2 shadow-lg shadow-black/40"
                style={{
                  left: `${held.fx * 100}%`,
                  // Clamp near the edges so the tooltip never leaves the frame.
                  transform: `translateX(${held.fx < 0.15 ? 0 : held.fx > 0.85 ? -100 : -50}%)`,
                }}
              >
                <div className="tabular font-mono text-[9.5px] uppercase tracking-[0.12em] text-faint">
                  {stamp(held.ms)}
                </div>
                <div className="tabular mt-1.5 font-mono text-[12.5px] font-semibold leading-none text-body">
                  {money(held.equity)}
                </div>
                <div
                  className={`tabular mt-1.5 font-mono text-[10.5px] leading-none ${
                    held.pnl >= 0 ? "text-gain" : "text-loss"
                  }`}
                >
                  {signedMoney(held.pnl)}
                </div>
              </div>
            </>
          )}

          <span className="sr-only" aria-live="polite">
            {held ? `${stamp(held.ms)}, equity ${money(held.equity)}, P&L ${signedMoney(held.pnl)}` : ""}
          </span>
        </div>

        <div className="mt-2.5 flex items-baseline justify-between gap-2 font-mono text-[10px] tracking-[0.04em] text-faint">
          <span className="tabular">{stamp(chart.pts[0].ms)}</span>
          <span className="tabular">{chart.pts.length} pts</span>
          <span className="tabular">{stamp(chart.last.ms)}</span>
        </div>
      </div>
    );
  }

  return (
    <Panel title="Equity" right={header}>
      {/* gap-px over bg-ink-line draws exact hairlines between the cells at any
          column count, so the rail never grows a stray edge as it reflows. */}
      <div className="grid gap-px overflow-hidden rounded-lg border border-ink-line bg-ink-line sm:grid-cols-3">
        {chart ? (
          <>
            <div className="bg-ink-raised px-4 py-3">
              <Stat label="Equity" value={money(chart.last.equity)} sub={`base ${money(chart.base, 0)}`} />
            </div>
            <div className="bg-ink-raised px-4 py-3">
              <Stat
                label="P&L"
                value={signedMoney(chart.last.pnl)}
                tone={chart.last.pnl >= 0 ? "gain" : "loss"}
              />
            </div>
            <div className="bg-ink-raised px-4 py-3">
              <Stat
                label="Return"
                // A zero or negative base makes the ratio meaningless, not zero.
                value={chart.base > 0 ? signedPct((chart.last.pnl / chart.base) * 100) : null}
                tone={chart.last.pnl >= 0 ? "gain" : "loss"}
              />
            </div>
          </>
        ) : (
          // No curve, no figures. Stat renders an absent value as an em dash.
          <>
            <div className="bg-ink-raised px-4 py-3">
              <Stat label="Equity" value={null} />
            </div>
            <div className="bg-ink-raised px-4 py-3">
              <Stat label="P&L" value={null} />
            </div>
            <div className="bg-ink-raised px-4 py-3">
              <Stat label="Return" value={null} />
            </div>
          </>
        )}
      </div>

      {stale && (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 font-mono text-[10.5px] text-warn">
          <span className="uppercase tracking-[0.12em]">refresh failed</span>
          <span className="min-w-0 flex-1 truncate text-warn/75" title={error}>
            {error}
          </span>
          <span className="whitespace-nowrap text-warn/75">holding the last good read</span>
        </div>
      )}

      <div className="mt-3">{well}</div>

      {(data?.note || readAt !== null) && (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-ink-line pt-2.5 font-mono text-[10px] text-faint">
          {data?.note && (
            <span className="min-w-0 flex-1 truncate" title={data.note}>
              {data.note}
            </span>
          )}
          {readAt !== null && (
            <span className="tabular ml-auto whitespace-nowrap">
              {stale ? "last good read" : "read"} {clock(readAt)}
            </span>
          )}
        </div>
      )}
    </Panel>
  );
}
