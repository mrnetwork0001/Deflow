"use client";

import { Section } from "./chrome";
import { PayoffDiagram } from "./visuals";

export function Thesis() {
  return (
    <Section
      id="edge"
      eyebrow="The edge"
      title={
        <>
          Probability of profit is not an edge.
          <br />
          <span className="text-gain">Expectancy is.</span>
        </>
      }
      lead="Under the risk-neutral measure every vertical spread is worth exactly what it costs. Score a candidate at its own implied volatility and every trade prices at zero — the correct answer, and a useless one. So Deflow scores each candidate twice, and trades the difference."
    >
      {/* ── the two measures, side by side ─────────────────────────────── */}
      <div className="grid gap-px overflow-hidden rounded-xl border border-ink-line bg-ink-line md:grid-cols-2">
        <Measure
          label="Risk-neutral"
          vol="implied volatility"
          value="≈ $0"
          tone="info"
          note="What the market says it is worth. Zero expected value, as arbitrage requires — which is why scoring this way ranks every candidate identically."
        />
        <Measure
          label="Physical"
          vol="forecast realised volatility"
          value="the edge"
          tone="gain"
          note="What it is worth if the underlying keeps moving the way it actually has been. Jump-robust, so one earnings gap cannot masquerade as a regime."
        />
      </div>

      <p className="mt-5 text-center font-sans text-[14.5px] leading-relaxed text-muted">
        The dollar gap between those two numbers <span className="text-body">is</span> the variance
        risk premium — and it is the only reason to put the trade on.
      </p>

      {/* ── what that rules out ────────────────────────────────────────── */}
      <div className="mt-12 grid gap-4 lg:grid-cols-[1fr_0.85fr]">
        <div className="rounded-xl border border-loss/25 bg-ink-card p-7">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-loss">
            A trade Deflow refuses
          </div>
          <h3 className="mt-4 font-sans text-[19px] font-semibold leading-snug text-body">
            79% of the time you keep $320. The other 21% you lose $1,680.
          </h3>

          <dl className="mt-6 space-y-px overflow-hidden rounded-lg border border-ink-line bg-ink-line font-mono text-[12px]">
            <Row k="probability of profit" v="79%" tone="text-gain" />
            <Row k="you keep" v="$320" tone="text-gain" sub="four times in five" />
            <Row k="you lose" v="$1,680" tone="text-loss" sub="the fifth" />
            <Row k="expected value" v="−$112" tone="text-loss" strong />
          </dl>

          <p className="mt-6 font-sans text-[13.5px] leading-[1.75] text-muted">
            A high win rate is not an edge. It is a way to lose money slowly and feel good about
            it. Anything with non-positive expectancy under the physical measure is refused —{" "}
            <span className="text-body">however high its probability of profit</span>.
          </p>
        </div>

        <div className="flex flex-col justify-between rounded-xl border border-ink-line bg-ink-raised/60 p-7">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
              What it will trade
            </div>
            <p className="mt-4 font-sans text-[13.5px] leading-[1.75] text-muted">
              Defined-risk structures only. Every short leg sits inside a long of the same right, so
              the worst case is a property of the geometry rather than a promise — and the wing is
              what makes the maximum loss knowable before the order is sent.
            </p>
          </div>
          <div className="mt-6">
            <PayoffDiagram credit className="w-full" />
          </div>
        </div>
      </div>
    </Section>
  );
}

function Measure({
  label, vol, value, note, tone,
}: { label: string; vol: string; value: string; note: string; tone: "info" | "gain" }) {
  const text = tone === "gain" ? "text-gain" : "text-info";
  return (
    <div className="bg-ink-card p-7">
      <div className={`font-mono text-[10px] uppercase tracking-[0.14em] ${text}`}>{label}</div>
      <div className="mt-1.5 font-mono text-[11.5px] text-faint">{vol}</div>
      <div className={`mt-6 font-mono text-[30px] font-bold leading-none ${text}`}>{value}</div>
      <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
        expected value
      </div>
      <p className="mt-5 font-sans text-[13px] leading-[1.7] text-muted">{note}</p>
    </div>
  );
}

function Row({
  k, v, tone, sub, strong = false,
}: { k: string; v: string; tone: string; sub?: string; strong?: boolean }) {
  return (
    <div
      className={`flex items-baseline justify-between gap-4 bg-ink-card px-4 ${
        strong ? "py-3.5" : "py-2.5"
      }`}
    >
      <dt className="text-faint">{k}</dt>
      <dd className={`tabular text-right ${tone} ${strong ? "text-[17px] font-bold" : "font-semibold"}`}>
        {v}
        {sub && <span className="ml-2 font-normal text-faint">· {sub}</span>}
      </dd>
    </div>
  );
}
