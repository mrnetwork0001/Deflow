"use client";

import { useMemo, useState } from "react";
import { AnalystView, money, pct, signedPct } from "@/lib/api";
import { Badge, Panel } from "./ui";

const STANCE: Record<string, { label: string; text: string }> = {
  sell_premium: { label: "sell premium", text: "text-gain" },
  buy_convexity: { label: "buy convexity", text: "text-info" },
  stand_down: { label: "stand down", text: "text-faint" },
};

const STANCE_ORDER = ["sell_premium", "buy_convexity", "stand_down"] as const;

// Same band and scale as the public scanner, so a row read here and a row read
// on the marketing page mean the same thing. Inside ±BAND the premium is noise;
// drawing that band is what makes a stand-down legible as a decision rather
// than as an absence.
const BAND = 0.02;
const SCALE = 0.12; // full bar width, either side of zero

/** Missing or non-finite readings render as an em dash - never as a zero. */
const num = (x: unknown): number | null =>
  typeof x === "number" && Number.isFinite(x) ? x : null;

const trend = (n: number) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}`;

// Column widths are shared by the header strip and the rows so the two cannot
// drift apart.
const COL = {
  symbol: "w-14",
  last: "w-[84px]",
  ivhv: "hidden w-[104px] md:block",
  ivr: "w-12",
  trend: "w-12",
  rsi: "hidden w-10 lg:block",
  conv: "w-12",
  stance: "w-24",
};

export function RegimeGrid({ views }: { views: AnalystView[] }) {
  const [open, setOpen] = useState<string | null>(null);

  // Richest premium first, so the two ends of the book are the two ends of the
  // list and the spread of the signal is visible without reading a number.
  // Symbols with no reading sort last and tie-break by name, so the order never
  // reshuffles between identical scans.
  const rows = useMemo(() => {
    const key = (v: AnalystView) => num(v.variance_premium) ?? Number.NEGATIVE_INFINITY;
    return [...views].sort((a, b) =>
      key(a) === key(b) ? a.symbol.localeCompare(b.symbol) : key(b) - key(a),
    );
  }, [views]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { sell_premium: 0, buy_convexity: 0, stand_down: 0 };
    views.forEach((v) => { c[v.stance] = (c[v.stance] ?? 0) + 1; });
    return c;
  }, [views]);

  const right = (
    <div className="flex items-center gap-4">
      {rows.length > 0 && (
        <div className="hidden items-center gap-3.5 md:flex">
          {STANCE_ORDER.map((k) => (
            <span key={k} className={`flex items-baseline gap-1.5 ${counts[k] ? "" : "opacity-40"}`}>
              <span className={`tabular font-mono text-[12px] font-bold ${STANCE[k].text}`}>
                {counts[k]}
              </span>
              <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                {STANCE[k].label}
              </span>
            </span>
          ))}
        </div>
      )}
      <Badge>variance risk premium</Badge>
    </div>
  );

  return (
    <Panel title="Agent 1 · Volatility regime" right={right}>
      {/* Full-bleed to the panel edge: this is a readout, not a card grid. */}
      <div className="-m-4 overflow-hidden rounded-b-xl">
        <div className="hidden items-center gap-x-4 border-b border-ink-line px-4 py-2 font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint lg:flex">
          <span className={COL.symbol}>symbol</span>
          <span className={`${COL.last} text-right`}>last</span>
          <span className="flex-1 px-3 text-center">cheap ← variance premium → rich</span>
          <span className={`${COL.ivhv} text-right`}>iv30 / hv60</span>
          <span className={`${COL.ivr} text-right`}>iv rank</span>
          <span className={`${COL.trend} text-right`}>trend</span>
          <span className={`${COL.rsi} text-right`}>rsi</span>
          <span className={`${COL.conv} text-right`}>conv</span>
          <span className={`${COL.stance} text-right`}>stance</span>
          <span className="w-3" />
        </div>

        {/* Height is reserved so the panel does not collapse to its title bar
            before the first scan lands and then shove the page around. */}
        <div className="min-h-[232px]">
          {rows.length === 0 ? (
            // `views` is the only channel this component has: an empty array
            // covers a first load, a scan that returned nothing, and a poll
            // that failed. It reports what it knows - no rows - instead of
            // picking one of the three and asserting it.
            <div className="grid min-h-[232px] place-items-center px-5 text-center">
              <div>
                <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-faint">
                  awaiting analyst
                </div>
                <p className="mt-2.5 font-sans text-[13px] text-muted">Waiting for the first scan…</p>
                <p className="mt-1.5 font-mono text-[11px] text-faint">no views received</p>
              </div>
            </div>
          ) : (
            <ol className="divide-y divide-ink-line">
              {rows.map((v) => {
                const st = STANCE[v.stance];
                const isOpen = open === v.symbol;
                const price = num(v.price);
                const vrp = num(v.variance_premium);
                const iv = num(v.iv_30d);
                const hv = num(v.hv_60d);
                const ivr = num(v.iv_rank);
                const tr = num(v.trend_score);
                const rsi = num(v.rsi14);
                const conv = num(v.conviction);
                const reasons = (v.reasons ?? []).filter((r) => r && r.trim());
                const brief = v.brief?.trim();

                return (
                  <li key={v.symbol}>
                    <button
                      type="button"
                      onClick={() => setOpen(isOpen ? null : v.symbol)}
                      aria-expanded={isOpen}
                      aria-controls={`regime-${v.symbol}`}
                      className={`flex w-full flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 text-left transition-colors hover:bg-ink-raised/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-gain/60 ${
                        isOpen ? "bg-ink-raised/50" : ""
                      } ${
                        // Not tradeable is carried by weight, not by a claim.
                        // Hover and focus restore it to full contrast so it
                        // stays readable when someone goes looking.
                        v.tradeable ? "" : "opacity-60 hover:opacity-100 focus-visible:opacity-100"
                      }`}
                    >
                      <span className={`${COL.symbol} font-mono text-[13px] font-bold text-body`}>
                        {v.symbol}
                      </span>
                      <span className={`tabular ${COL.last} text-right font-mono text-[12px] text-muted`}>
                        {price === null ? "-" : money(price)}
                      </span>

                      <span className="order-last w-full lg:order-none lg:w-auto lg:flex-1 lg:px-3">
                        <VrpBar value={vrp} />
                      </span>

                      <span
                        title="IV 30d / HV 60d"
                        className={`tabular ${COL.ivhv} text-right font-mono text-[11.5px] text-muted`}
                      >
                        {iv === null || hv === null ? "-" : `${pct(iv)} / ${pct(hv)}`}
                      </span>
                      <span
                        title="IV rank"
                        className={`tabular ${COL.ivr} text-right font-mono text-[11.5px] text-muted`}
                      >
                        {ivr === null ? "-" : pct(ivr, 0)}
                      </span>
                      <span
                        title="trend score"
                        className={`tabular ${COL.trend} text-right font-mono text-[11.5px] text-muted`}
                      >
                        {tr === null ? "-" : trend(tr)}
                      </span>
                      <span
                        title="RSI 14"
                        className={`tabular ${COL.rsi} text-right font-mono text-[11.5px] text-muted`}
                      >
                        {rsi === null ? "-" : rsi.toFixed(0)}
                      </span>
                      <span
                        title="conviction"
                        className={`tabular ${COL.conv} text-right font-mono text-[11.5px] text-muted`}
                      >
                        {conv === null ? "-" : pct(conv, 0)}
                      </span>
                      <span
                        className={`${COL.stance} text-right font-mono text-[10.5px] uppercase tracking-[0.1em] ${
                          st ? st.text : "text-muted"
                        }`}
                      >
                        {st ? st.label : v.stance}
                      </span>
                      <span
                        aria-hidden
                        className={`w-3 shrink-0 text-right font-mono text-[10px] text-faint transition-transform duration-200 ${
                          isOpen ? "rotate-90" : ""
                        }`}
                      >
                        ▸
                      </span>
                    </button>

                    {isOpen && (
                      <div
                        id={`regime-${v.symbol}`}
                        className="animate-rise border-t border-ink-line bg-ink px-4 py-3.5"
                      >
                        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-5">
                          <Metric k="IV 30d" v={iv === null ? "-" : pct(iv)} />
                          <Metric k="HV 60d" v={hv === null ? "-" : pct(hv)} />
                          <Metric k="IV rank" v={ivr === null ? "-" : pct(ivr, 0)} />
                          <Metric
                            k="variance premium"
                            v={vrp === null ? "-" : signedPct(vrp * 100)}
                            tone={vrp === null || Math.abs(vrp) <= BAND ? "text-muted" : vrp > 0 ? "text-gain" : "text-info"}
                          />
                          <Metric k="trend" v={tr === null ? "-" : trend(tr)} />
                          <Metric k="RSI 14" v={rsi === null ? "-" : rsi.toFixed(0)} />
                          <Metric k="conviction" v={conv === null ? "-" : pct(conv, 0)} />
                          <Metric k="regime" v={v.regime || "-"} />
                          <Metric k="bias" v={v.bias || "-"} />
                          <Metric
                            k="tradeable"
                            v={v.tradeable ? "true" : "false"}
                            tone={v.tradeable ? "text-body" : "text-warn"}
                          />
                        </dl>

                        {(reasons.length > 0 || brief) && (
                          <div className="mt-3.5 border-t border-ink-line pt-3">
                            {reasons.length > 0 && (
                              <ul className="space-y-1">
                                {reasons.map((r, i) => (
                                  <li key={i} className="flex gap-2 font-mono text-[11.5px] leading-snug text-muted">
                                    <span className="text-faint">·</span>
                                    <span className="break-words">{r}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                            {brief && (
                              <p className={`font-sans text-[12.5px] leading-[1.7] text-muted ${reasons.length > 0 ? "mt-2.5" : ""}`}>
                                {brief}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </Panel>
  );
}

/** Signed bar centred on zero, with the noise band drawn behind it. */
function VrpBar({ value }: { value: number | null }) {
  const v = value ?? 0;
  const width = Math.min(Math.abs(v) / SCALE, 1) * 50;
  const rich = v > 0;
  const inBand = Math.abs(v) <= BAND;
  const band = (BAND / SCALE) * 50;

  return (
    <span className="flex items-center gap-3">
      <span className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-ink" aria-hidden>
        {/* the band the analyst treats as no signal */}
        <span
          className="absolute top-0 block h-full bg-ink-hair/60"
          style={{ left: `${50 - band}%`, width: `${band * 2}%` }}
        />
        <span className="absolute left-1/2 top-0 block h-full w-px bg-muted/50" />
        {value !== null && (
          <span
            className={`absolute top-0 block h-full transition-all duration-700 ${
              inBand ? "bg-faint" : rich ? "bg-gain" : "bg-info"
            }`}
            style={rich ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
          />
        )}
      </span>
      <span
        className={`tabular w-16 shrink-0 text-right font-mono text-[11.5px] ${
          value === null ? "text-faint" : inBand ? "text-muted" : rich ? "text-gain" : "text-info"
        }`}
      >
        {value === null ? "-" : signedPct(value * 100)}
      </span>
    </span>
  );
}

function Metric({ k, v, tone = "text-body" }: { k: string; v: string; tone?: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">{k}</dt>
      <dd className={`tabular mt-0.5 break-words font-mono text-[12px] ${tone}`}>{v}</dd>
    </div>
  );
}
