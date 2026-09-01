"use client";

import { useEffect, useMemo, useState } from "react";
import { AnalystView, getJSON } from "@/lib/api";
import { Section } from "./chrome";
import { RevealGroup } from "./Reveal";

const FALLBACK = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMD", "TSLA"];

const STANCE: Record<string, { label: string; text: string; bg: string }> = {
  sell_premium: { label: "sell premium", text: "text-gain", bg: "bg-gain" },
  buy_convexity: { label: "buy convexity", text: "text-info", bg: "bg-info" },
  stand_down: { label: "stand down", text: "text-faint", bg: "bg-ink-hair" },
};

// The band inside which the variance premium is treated as noise. Drawing it
// is what makes a stand-down legible as a decision rather than an absence.
const BAND = 0.02;
const SCALE = 0.12;   // full bar width, either side of zero

export function Universe() {
  const [views, setViews] = useState<AnalystView[] | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const load = () =>
      getJSON<{ views: AnalystView[] }>("/api/analysis")
        .then((d) => { setViews(d.views); setOffline(false); })
        .catch(() => setOffline(true));
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  // Richest premium first, so the two ends of the book are the two ends of the
  // list and the reader can see the spread of the signal without reading it.
  const rows = useMemo(() => {
    if (!views) return null;
    return [...views].sort((a, b) => b.variance_premium - a.variance_premium);
  }, [views]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { sell_premium: 0, buy_convexity: 0, stand_down: 0 };
    (views ?? []).forEach((v) => { c[v.stance] = (c[v.stance] ?? 0) + 1; });
    return c;
  }, [views]);

  return (
    <Section
      eyebrow="Coverage"
      title="Eight names, chosen for penny-wide markets."
      lead="A defined-risk desk lives or dies on being able to exit, so the universe is selected for depth of option chain rather than for interesting stories."
    >
      {/* what the desk has decided, at a glance */}
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-ink-line bg-ink-card px-5 py-4">
        {(["sell_premium", "buy_convexity", "stand_down"] as const).map((k) => (
          <div key={k} className="flex items-baseline gap-2.5">
            <span className={`tabular font-mono text-[19px] font-bold ${STANCE[k].text}`}>
              {views ? counts[k] : "-"}
            </span>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-faint">
              {STANCE[k].label}
            </span>
          </div>
        ))}
        <p className="ml-auto max-w-md font-sans text-[12.5px] leading-snug text-muted">
          Roughly half of every scan ends in a documented refusal to trade. That is the desk
          working, not the desk idle.
        </p>
      </div>

      {/* the scanner */}
      <div className="overflow-hidden rounded-xl border border-ink-line bg-ink-card">
        <div className="hidden items-center gap-4 border-b border-ink-line px-5 py-2.5 font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint sm:flex">
          <span className="w-14">symbol</span>
          <span className="w-24 text-right">last</span>
          <span className="flex-1 px-4 text-center">
            cheap ← variance premium → rich
          </span>
          <span className="w-16 text-right">IV rank</span>
          <span className="w-14 text-right">trend</span>
          <span className="w-28 text-right">stance</span>
        </div>

        <ol className="divide-y divide-ink-line">
          <RevealGroup step={45} y={8}>
          {(rows ?? FALLBACK.map((s) => ({ symbol: s }) as AnalystView)).map((v) => {
            const st = v.stance ? STANCE[v.stance] : null;
            const vrp = v.variance_premium ?? 0;
            return (
              <li
                key={v.symbol}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 transition-colors hover:bg-ink-raised/50"
              >
                <span className="w-14 font-mono text-[13px] font-bold text-body">{v.symbol}</span>
                <span className="tabular w-24 text-right font-mono text-[12px] text-muted">
                  {v.price != null
                    ? `$${v.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                    : "-"}
                </span>

                <div className="order-last w-full sm:order-none sm:w-auto sm:flex-1 sm:px-4">
                  <VrpBar value={st ? vrp : null} />
                </div>

                <span className="tabular w-16 text-right font-mono text-[11.5px] text-muted">
                  {v.iv_rank != null ? `${(v.iv_rank * 100).toFixed(0)}%` : "-"}
                </span>
                <span className="tabular w-14 text-right font-mono text-[11.5px] text-muted">
                  {v.trend_score != null
                    ? `${v.trend_score >= 0 ? "+" : ""}${v.trend_score.toFixed(2)}`
                    : "-"}
                </span>
                <span
                  className={`w-28 text-right font-mono text-[10.5px] uppercase tracking-[0.1em] ${
                    st ? st.text : "text-faint"
                  }`}
                >
                  {st ? st.label : offline ? "offline" : "scanning…"}
                </span>
              </li>
            );
          })}
          </RevealGroup>
        </ol>
      </div>
    </Section>
  );
}

/** Signed bar centred on zero, with the noise band drawn behind it. */
function VrpBar({ value }: { value: number | null }) {
  const v = value ?? 0;
  const width = Math.min(Math.abs(v) / SCALE, 1) * 50;
  const rich = v > 0;
  const inBand = Math.abs(v) <= BAND;
  const bandWidth = (BAND / SCALE) * 50;

  return (
    <div className="flex items-center gap-3">
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-ink">
        {/* the band the analyst treats as no signal */}
        <div
          className="absolute top-0 h-full bg-ink-hair/60"
          style={{ left: `${50 - bandWidth}%`, width: `${bandWidth * 2}%` }}
        />
        <div className="absolute left-1/2 top-0 h-full w-px bg-muted/50" />
        {value !== null && (
          <div
            className={`absolute top-0 h-full transition-all duration-700 ${
              inBand ? "bg-faint" : rich ? "bg-gain" : "bg-info"
            }`}
            style={rich ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
          />
        )}
      </div>
      <span
        className={`tabular w-14 shrink-0 text-right font-mono text-[11.5px] ${
          value === null ? "text-faint" : inBand ? "text-faint" : rich ? "text-gain" : "text-info"
        }`}
      >
        {value === null ? "-" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%`}
      </span>
    </div>
  );
}
