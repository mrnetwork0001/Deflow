"use client";

import { Card } from "./chrome";
import { Mark } from "./chrome";
import { PayoffDiagram } from "./visuals";

export function Thesis() {
  return (
    <section className="relative overflow-hidden border-t border-ink-line px-6 py-28">
      <div aria-hidden className="grid-bg pointer-events-none absolute inset-0 opacity-30" />
      <div className="relative mx-auto max-w-content">
        <div className="flex justify-center"><Mark size={40} /></div>

        <p className="mx-auto mt-10 max-w-3xl text-center font-sans text-[26px] font-medium leading-[1.4] tracking-tight text-muted sm:text-[32px]">
          Under the risk-neutral measure, <span className="text-body">every vertical spread is
          worth exactly what it costs</span>. Score a candidate at its own implied volatility and
          every trade prices at zero — the correct answer, and a useless one.
        </p>

        <p className="mx-auto mt-8 max-w-3xl text-center font-sans text-[26px] font-medium leading-[1.4] tracking-tight text-muted sm:text-[32px]">
          So Deflow scores each candidate <span className="text-gain">twice</span>, and trades the
          difference.
        </p>

        <div className="mx-auto mt-16 grid max-w-4xl gap-4 lg:grid-cols-[1.2fr_1fr]">
          <Card className="p-6">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-ink-line font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                  <th className="pb-3 font-medium">Measure</th>
                  <th className="pb-3 font-medium">Volatility</th>
                  <th className="pb-3 font-medium">What it tells you</th>
                </tr>
              </thead>
              <tbody className="font-sans text-[13px]">
                <tr className="border-b border-ink-line/60">
                  <td className="py-4 pr-4 font-mono text-[12px] text-info">risk-neutral</td>
                  <td className="py-4 pr-4 text-muted">implied</td>
                  <td className="py-4 text-muted">What the market says it is worth — ≈ 0 EV, as arbitrage requires</td>
                </tr>
                <tr>
                  <td className="py-4 pr-4 font-mono text-[12px] text-gain">physical</td>
                  <td className="py-4 pr-4 text-muted">forecast realised</td>
                  <td className="py-4 text-muted">What it is worth if the stock keeps moving as it has been</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-5 border-t border-ink-line pt-5 font-sans text-[13.5px] leading-[1.7] text-muted">
              The dollar gap between those two rows <span className="text-body">is</span> the
              variance risk premium. Anything with non-positive expectancy under the physical
              measure is refused — <span className="text-body">however high its win rate</span>.
            </p>
          </Card>

          <Card className="flex flex-col p-6">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-loss">
              A trade Deflow refuses
            </div>
            <div className="mt-5 space-y-3 font-mono text-[12px]">
              {[
                ["probability of profit", "79%", "text-gain"],
                ["you keep", "$320 · 4 times in 5", "text-gain"],
                ["you lose", "$1,680 · the fifth", "text-loss"],
              ].map(([k, v, tone]) => (
                <div key={k} className="flex items-baseline justify-between gap-3">
                  <span className="text-faint">{k}</span>
                  <span className={`tabular font-semibold ${tone}`}>{v}</span>
                </div>
              ))}
              <div className="flex items-baseline justify-between gap-3 border-t border-ink-line pt-3">
                <span className="text-faint">expected value</span>
                <span className="tabular text-[17px] font-bold text-loss">−$112</span>
              </div>
            </div>
            <PayoffDiagram credit className="mt-6 w-full" />
          </Card>
        </div>
      </div>
    </section>
  );
}
