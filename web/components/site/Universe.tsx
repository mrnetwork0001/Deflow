"use client";

import { useEffect, useState } from "react";
import { AnalystView, getJSON } from "@/lib/api";
import { Card, Section } from "./chrome";

const FALLBACK = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMD", "TSLA"];

const STANCE: Record<string, { label: string; cls: string }> = {
  sell_premium: { label: "sell premium", cls: "text-gain" },
  buy_convexity: { label: "buy convexity", cls: "text-info" },
  stand_down: { label: "stand down", cls: "text-faint" },
};

export function Universe() {
  const [views, setViews] = useState<AnalystView[] | null>(null);

  useEffect(() => {
    getJSON<{ views: AnalystView[] }>("/api/analysis")
      .then((d) => setViews(d.views))
      .catch(() => setViews(null));
  }, []);

  return (
    <Section
      eyebrow="Coverage"
      title="Eight names, chosen for penny-wide markets."
      lead="A defined-risk desk lives or dies on being able to exit. The universe is selected for depth of option chain, not for interesting stories — and roughly half of every scan ends in a documented refusal to trade."
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {(views ?? FALLBACK.map((s) => ({ symbol: s }) as AnalystView)).map((v) => {
          const st = v.stance ? STANCE[v.stance] : null;
          return (
            <Card key={v.symbol} className="p-5">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-[15px] font-bold text-body">{v.symbol}</span>
                {v.price != null && (
                  <span className="tabular font-mono text-[12px] text-muted">
                    ${v.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                )}
              </div>
              {st ? (
                <>
                  <div className={`mt-3 font-mono text-[11px] uppercase tracking-[0.1em] ${st.cls}`}>
                    {st.label}
                  </div>
                  <div className="mt-3 space-y-1.5 font-mono text-[10.5px]">
                    <Row k="variance premium" v={`${v.variance_premium >= 0 ? "+" : ""}${(v.variance_premium * 100).toFixed(1)}%`}
                         tone={v.variance_premium > 0.02 ? "text-gain" : v.variance_premium < -0.01 ? "text-info" : "text-muted"} />
                    <Row k="IV rank" v={`${(v.iv_rank * 100).toFixed(0)}%`} />
                    <Row k="trend" v={`${v.trend_score >= 0 ? "+" : ""}${v.trend_score.toFixed(2)}`} />
                  </div>
                </>
              ) : (
                <div className="mt-3 font-mono text-[11px] text-faint">awaiting first scan</div>
              )}
            </Card>
          );
        })}
      </div>
    </Section>
  );
}

function Row({ k, v, tone = "text-body" }: { k: string; v: string; tone?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-faint">{k}</span>
      <span className={`tabular ${tone}`}>{v}</span>
    </div>
  );
}
