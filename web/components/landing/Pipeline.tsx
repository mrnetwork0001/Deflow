"use client";

const STAGES = [
  {
    n: "01", agent: "Macro & Volatility Analyst", role: "what is the market doing?",
    detail: "Measures implied against realised volatility on eight liquid names. Emits a stance, a bias, and — about half the time — a documented refusal to trade.",
    out: "regime + variance risk premium", tone: "info" as const,
  },
  {
    n: "02", agent: "Options Structurer", role: "what trade expresses that?",
    detail: "Delta-targeted strikes, a width ladder scaled to spot, a hard liquidity floor, and position size taken from the risk gate's own sizer.",
    out: "8 priced, defined-risk candidates", tone: "info" as const,
  },
  {
    n: "03", agent: "Reasoning layer", role: "which one?",
    detail: "Featherless AI is shown finished candidates and returns one integer index, bounds-checked. It cannot change a strike, a size, or a price. Any failure falls back to a deterministic ranker.",
    out: "one index, or abstain", tone: "warn" as const, model: true,
  },
  {
    n: "04", agent: "Adversarial Risk Auditor", role: "what is wrong with it?",
    detail: "Re-derives the Greeks from scratch and runs 1,000 jump-diffusion paths under two volatility measures. Refuses negative expectancy however high the win rate.",
    out: "pass, or a fatal objection", tone: "info" as const,
  },
  {
    n: "05", agent: "Deterministic risk gate", role: "is it allowed?",
    detail: "Twelve hard-coded circuit breakers. No network, no prompt, no model. Fails closed on anything malformed, and sizes the trade itself.",
    out: "approved + contract count", tone: "gain" as const, gate: true,
  },
  {
    n: "06", agent: "Execution Agent", role: "route it",
    detail: "Re-runs the entire gate on the exact proposal being sent, then submits a multi-leg order through Alpaca's official CLI with an idempotent client order id.",
    out: "mleg order on Alpaca", tone: "gain" as const,
  },
];

export function Pipeline() {
  return (
    <ol className="relative space-y-3">
      {STAGES.map((s, i) => (
        <li key={s.n} className="relative">
          <div
            className={`rounded-xl border bg-ink-raised p-5 transition hover:border-muted/50 ${
              s.gate ? "border-gain/35" : s.model ? "border-warn/30" : "border-ink-line"
            }`}
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-mono text-[11px] font-bold text-muted">{s.n}</span>
              <h3 className="font-sans text-[15px] font-semibold text-body">{s.agent}</h3>
              <span className="font-mono text-[11px] text-muted">{s.role}</span>
              {s.gate && (
                <span className="ml-auto rounded border border-gain/40 bg-gain/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-gain">
                  zero LLM
                </span>
              )}
              {s.model && (
                <span className="ml-auto rounded border border-warn/40 bg-warn/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-warn">
                  only LLM in the system
                </span>
              )}
            </div>
            <p className="mt-2 max-w-3xl font-sans text-[13.5px] leading-relaxed text-muted">{s.detail}</p>
            <div className="mt-3 flex items-center gap-2 font-mono text-[11px]">
              <span className="text-muted">→</span>
              <span className={s.tone === "gain" ? "text-gain" : s.tone === "warn" ? "text-warn" : "text-info"}>
                {s.out}
              </span>
            </div>
          </div>
          {i < STAGES.length - 1 && (
            <div className="ml-8 h-3 w-px bg-ink-line" aria-hidden />
          )}
        </li>
      ))}
    </ol>
  );
}
