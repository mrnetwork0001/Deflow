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
import { Badge, Empty, Panel, Stat } from "./ui";

// The viewBox is stretched to the container by preserveAspectRatio="none", so
// these units are arbitrary — only their ratios matter.
const VW = 1000;
const VH = 100;

// Token hexes, repeated here because SVG paint attributes cannot take Tailwind
// classes. Keep in sync with tailwind.config.ts.
const GAIN = "#00e08a";
const LOSS = "#ff5a5a";

const stamp = (ms: number) =>
  new Date(ms).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

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

export function EquityCurve() {
  const [data, setData] = useState<EquityCurveData | null>(null);
  const [error, setError] = useState("");
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

  const stroke = chart?.up ? GAIN : LOSS;

  const header = (
    <div className="flex items-center gap-2">
      {error && data && <Badge tone="warn">stale</Badge>}
      {data && (
        <Badge tone={data.source === "alpaca" ? "info" : "muted"}>{data.source}</Badge>
      )}
      {data?.note && (
        <span className="hidden max-w-[22ch] truncate text-[10px] text-muted sm:inline" title={data.note}>
          {data.note}
        </span>
      )}
    </div>
  );

  let body: React.ReactNode;

  if (!data && error) {
    body = (
      <div className="py-8 text-center">
        <div className="text-xs font-semibold text-loss">Curve unavailable</div>
        <p className="mt-1.5 text-[11px] text-muted">{error}</p>
        <p className="mt-1 text-[11px] text-faint">Showing nothing beats showing a number we cannot verify.</p>
      </div>
    );
  } else if (!data) {
    body = <Empty>Reading the curve…</Empty>;
  } else if (!chart) {
    body = <Empty>Not enough history yet. The curve fills in as the desk trades.</Empty>;
  } else {
    const ret = chart.base > 0 ? signedPct((chart.last.pnl / chart.base) * 100) : "—";
    body = (
      <>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Stat label="Equity" value={money(chart.last.equity)} sub={`base ${money(chart.base, 0)}`} />
          <Stat
            label="P&L"
            value={signedMoney(chart.last.pnl)}
            tone={chart.last.pnl >= 0 ? "gain" : "loss"}
          />
          <Stat label="Return" value={ret} tone={chart.last.pnl >= 0 ? "gain" : "loss"} />
        </div>

        <div
          className="relative mt-4 h-44 w-full touch-pan-y select-none sm:h-52"
          onPointerMove={track}
          onPointerDown={track}
          onPointerLeave={() => setHover(null)}
          onPointerCancel={() => setHover(null)}
        >
          <svg
            className="absolute inset-0 h-full w-full overflow-visible"
            viewBox={`0 0 ${VW} ${VH}`}
            preserveAspectRatio="none"
            aria-hidden
          >
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity="0.26" />
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
              stroke="#262b33"
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
                stroke="#39414d"
                strokeWidth="1"
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

          {/* Labels live in HTML, not SVG: the same stretch that lets the curve
              fill the container would distort <text>. */}
          <div
            className="pointer-events-none absolute right-0 -translate-y-1/2 bg-ink-raised/85 px-1 font-mono text-[9px] uppercase tracking-[0.1em] text-faint"
            style={{ top: `${chart.baseFy * 100}%` }}
          >
            base {money(chart.base, 0)}
          </div>

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
                className="pointer-events-none absolute top-0 whitespace-nowrap rounded border border-ink-hair bg-ink-card px-2 py-1.5 shadow-lg"
                style={{
                  left: `${held.fx * 100}%`,
                  // Clamp near the edges so the tooltip never leaves the frame.
                  transform: `translateX(${held.fx < 0.15 ? 0 : held.fx > 0.85 ? -100 : -50}%)`,
                }}
              >
                <div className="tabular text-[9px] uppercase tracking-[0.1em] text-faint">{stamp(held.ms)}</div>
                <div className="tabular mt-1 text-xs font-semibold text-body">{money(held.equity)}</div>
                <div className={`tabular text-[10px] ${held.pnl >= 0 ? "text-gain" : "text-loss"}`}>
                  {signedMoney(held.pnl)}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-faint">
          <span className="tabular">{stamp(chart.pts[0].ms)}</span>
          <span className="tabular">{stamp(chart.last.ms)}</span>
        </div>
      </>
    );
  }

  return (
    <Panel title="Equity" right={header}>
      {body}
    </Panel>
  );
}
