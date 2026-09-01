"use client";

/**
 * Generated visuals.
 *
 * The reference design leans on photography. A quant product has something
 * better available: the artefacts it actually produces. Every graphic below is
 * drawn from the same mathematics the desk trades on -- payoff geometry,
 * simulated price paths, a volatility smile, a P&L distribution -- so the page
 * illustrates the system rather than decorating it, and there is no stock
 * imagery to license or misrepresent.
 *
 * All are deterministic: a seeded PRNG, so the server render and the client
 * hydration draw identical paths.
 */

import React from "react";

/** Mulberry32 - small, fast, and identical across server and client. */
function rng(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(next: () => number) {
  // Box-Muller, so the paths have genuinely normal increments.
  const u = Math.max(next(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * next());
}

/** Geometric-Brownian price paths - the hero backdrop. */
export function PricePaths({
  width = 1200, height = 420, paths = 26, steps = 90, seed = 7, className = "",
}: { width?: number; height?: number; paths?: number; steps?: number; seed?: number; className?: string }) {
  const next = rng(seed);
  const lines: { d: string; up: boolean; o: number }[] = [];

  for (let p = 0; p < paths; p++) {
    let value = 0;
    const pts: string[] = [];
    for (let s = 0; s <= steps; s++) {
      value += gauss(next) * 0.9 + 0.055;
      const x = (s / steps) * width;
      const y = height / 2 - value * (height / 26);
      pts.push(`${s === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`);
    }
    lines.push({ d: pts.join(" "), up: value > 0, o: 0.1 + (p / paths) * 0.3 });
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={className} preserveAspectRatio="none" aria-hidden>
      {lines.map((l, i) => (
        <path
          key={i}
          d={l.d}
          fill="none"
          strokeWidth={i % 7 === 0 ? 1.4 : 0.7}
          stroke={l.up ? "#00e08a" : "#ff5a5a"}
          opacity={l.o}
        />
      ))}
    </svg>
  );
}

/** Payoff diagram for a defined-risk vertical: the capped-both-ways shape. */
export function PayoffDiagram({
  credit = false, className = "",
}: { credit?: boolean; className?: string }) {
  const w = 320, h = 150, mid = h / 2;
  // Flat, ramp, flat - profit capped on one side, loss capped on the other.
  const d = credit
    ? `M8,${mid - 34} L120,${mid - 34} L212,${mid + 40} L312,${mid + 40}`
    : `M8,${mid + 40} L120,${mid + 40} L212,${mid - 40} L312,${mid - 40}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      <line x1="8" y1={mid} x2={w - 8} y2={mid} stroke="#262b33" strokeWidth="1" strokeDasharray="3 4" />
      <path d={d} fill="none" stroke="#00e08a" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      {/* The two wings that make the risk defined. */}
      <circle cx="120" cy={credit ? mid - 34 : mid + 40} r="3.5" fill="#08090b" stroke="#00e08a" strokeWidth="1.6" />
      <circle cx="212" cy={credit ? mid + 40 : mid - 40} r="3.5" fill="#08090b" stroke="#00e08a" strokeWidth="1.6" />
      <text x="12" y={mid - 8} fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">
        max {credit ? "profit" : "loss"}
      </text>
      <text x={w - 12} y={mid + (credit ? 56 : -48)} textAnchor="end" fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">
        max {credit ? "loss" : "profit"}
      </text>
    </svg>
  );
}

/** Volatility smile with an equity put skew - what the analyst reads. */
export function VolSmile({ className = "" }: { className?: string }) {
  const w = 320, h = 150;
  const pts: string[] = [];
  for (let i = 0; i <= 60; i++) {
    const m = -0.28 + (i / 60) * 0.56;                 // log-moneyness
    const iv = 0.22 * (1 - 0.55 * m + 1.15 * m * m);   // skew + smile
    const x = 12 + (i / 60) * (w - 24);
    const y = h - 22 - (iv - 0.16) * 640;
    pts.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <line key={i} x1="12" y1={26 + i * 30} x2={w - 12} y2={26 + i * 30} stroke="#181c22" strokeWidth="1" />
      ))}
      <path d={pts.join(" ")} fill="none" stroke="#4da6ff" strokeWidth="2.2" strokeLinecap="round" />
      <line x1={w / 2} y1="16" x2={w / 2} y2={h - 16} stroke="#262b33" strokeWidth="1" strokeDasharray="3 4" />
      <text x={w / 2} y={h - 5} textAnchor="middle" fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">
        at the money
      </text>
    </svg>
  );
}

/** Terminal P&L distribution with the 5% tail shaded - the auditor's output. */
export function PnlDistribution({ className = "" }: { className?: string }) {
  const w = 320, h = 150, bars = 34;
  const next = rng(11);
  const heights = Array.from({ length: bars }, (_, i) => {
    const x = (i - bars * 0.62) / (bars * 0.2);
    return Math.exp(-0.5 * x * x) * (0.86 + next() * 0.28);
  });
  const max = Math.max(...heights);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      {heights.map((v, i) => {
        const bw = (w - 24) / bars;
        const bh = (v / max) * (h - 44);
        return (
          <rect
            key={i}
            x={12 + i * bw + 0.8}
            y={h - 24 - bh}
            width={bw - 1.6}
            height={bh}
            fill={i < bars * 0.05 ? "#ff5a5a" : "#00e08a"}
            opacity={i < bars * 0.05 ? 0.85 : 0.5}
            rx="1"
          />
        );
      })}
      <line x1="12" y1={h - 24} x2={w - 12} y2={h - 24} stroke="#262b33" strokeWidth="1" />
      <text x="14" y={h - 9} fill="#ff5a5a" fontSize="9" fontFamily="ui-monospace, monospace">CVaR 5%</text>
      <text x={w - 12} y={h - 9} textAnchor="end" fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">
        1,000 paths
      </text>
    </svg>
  );
}

/** Twelve breakers as a gate the order has to pass through. */
export function GateGraphic({ className = "" }: { className?: string }) {
  const w = 320, h = 150;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      <line x1="6" y1={h / 2} x2={w - 6} y2={h / 2} stroke="#1e2229" strokeWidth="1" strokeDasharray="2 5" />
      {Array.from({ length: 12 }, (_, i) => {
        const x = 24 + i * 24;
        return (
          <g key={i}>
            <line x1={x} y1={h / 2 - 26} x2={x} y2={h / 2 + 26} stroke="#00e08a" strokeWidth="1.6" opacity={0.28 + i * 0.055} />
            <circle cx={x} cy={h / 2 - 26} r="1.8" fill="#00e08a" opacity={0.5} />
          </g>
        );
      })}
      <circle cx="12" cy={h / 2} r="4" fill="#ffc857" />
      <circle cx={w - 12} cy={h / 2} r="4" fill="#00e08a" />
      <text x="12" y={h / 2 + 40} fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">proposal</text>
      <text x={w - 12} y={h / 2 + 40} textAnchor="end" fill="#00e08a" fontSize="9" fontFamily="ui-monospace, monospace">order</text>
    </svg>
  );
}

/** Hash chain: each block carrying the digest of the one before it. */
export function ChainGraphic({ className = "" }: { className?: string }) {
  const w = 320, h = 150;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={className} aria-hidden>
      {Array.from({ length: 5 }, (_, i) => {
        const x = 14 + i * 60;
        return (
          <g key={i} opacity={0.35 + i * 0.14}>
            <rect x={x} y={h / 2 - 20} width="44" height="40" rx="5" fill="#121519" stroke="#00e08a" strokeWidth="1.2" />
            <line x1={x + 8} y1={h / 2 - 7} x2={x + 30} y2={h / 2 - 7} stroke="#00e08a" strokeWidth="1.4" opacity="0.7" />
            <line x1={x + 8} y1={h / 2 + 1} x2={x + 36} y2={h / 2 + 1} stroke="#7c8595" strokeWidth="1.2" opacity="0.6" />
            <line x1={x + 8} y1={h / 2 + 9} x2={x + 24} y2={h / 2 + 9} stroke="#7c8595" strokeWidth="1.2" opacity="0.4" />
            {i < 4 && <path d={`M${x + 44},${h / 2} L${x + 60},${h / 2}`} stroke="#00e08a" strokeWidth="1.2" opacity="0.55" />}
          </g>
        );
      })}
      <text x="14" y={h / 2 + 42} fill="#525b6b" fontSize="9" fontFamily="ui-monospace, monospace">
        each block carries the SHA-256 of the last
      </text>
    </svg>
  );
}
