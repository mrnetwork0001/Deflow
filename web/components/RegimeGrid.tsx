"use client";

import { AnalystView, pct, signedPct } from "@/lib/api";
import { Badge, Empty, Panel } from "./ui";

const STANCE_TONE: Record<string, "gain" | "info" | "muted"> = {
  sell_premium: "gain",
  buy_convexity: "info",
  stand_down: "muted",
};

const STANCE_LABEL: Record<string, string> = {
  sell_premium: "sell premium",
  buy_convexity: "buy convexity",
  stand_down: "stand down",
};

export function RegimeGrid({ views }: { views: AnalystView[] }) {
  return (
    <Panel title="Agent 1 · Volatility regime" right={<Badge>variance risk premium</Badge>}>
      {views.length === 0 ? (
        <Empty>Waiting for the first scan…</Empty>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {views.map((v) => (
            <article
              key={v.symbol}
              className={`rounded border p-3 transition ${
                v.tradeable ? "border-ink-line bg-ink" : "border-ink-line/50 bg-ink/40 opacity-60"
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-bold text-body">{v.symbol}</div>
                  <div className="tabular text-[11px] text-muted">
                    ${v.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </div>
                </div>
                <Badge tone={STANCE_TONE[v.stance] ?? "muted"}>{STANCE_LABEL[v.stance] ?? v.stance}</Badge>
              </div>

              {/* The variance risk premium is the signal the whole desk trades. */}
              <div className="mt-3">
                <div className="flex items-baseline justify-between text-[10px] text-muted">
                  <span>variance premium</span>
                  <span
                    className={`tabular text-xs font-bold ${
                      v.variance_premium > 0.02 ? "text-gain" : v.variance_premium < -0.01 ? "text-info" : "text-muted"
                    }`}
                  >
                    {signedPct(v.variance_premium * 100)}
                  </span>
                </div>
                <VrpBar value={v.variance_premium} />
              </div>

              <dl className="mt-2 space-y-1 text-[10px]">
                <Row k="IV 30d / HV 60d" v={`${pct(v.iv_30d)} / ${pct(v.hv_60d)}`} />
                <Row k="IV rank" v={pct(v.iv_rank, 0)} />
                <Row k="trend / RSI" v={`${v.trend_score >= 0 ? "+" : ""}${v.trend_score.toFixed(2)} / ${v.rsi14.toFixed(0)}`} />
                <Row k="bias" v={v.bias} />
                <Row k="conviction" v={pct(v.conviction, 0)} />
              </dl>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

/** Signed bar centred on zero: right of centre is rich, left is cheap. */
function VrpBar({ value }: { value: number }) {
  const scaled = Math.max(-1, Math.min(1, value / 0.1));
  const width = Math.abs(scaled) * 50;
  return (
    <div className="relative mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ink-line">
      <div className="absolute left-1/2 top-0 h-full w-px bg-muted/40" />
      <div
        className={`absolute top-0 h-full ${scaled >= 0 ? "bg-gain" : "bg-info"}`}
        style={scaled >= 0 ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
      />
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted">{k}</dt>
      <dd className="tabular text-body">{v}</dd>
    </div>
  );
}
