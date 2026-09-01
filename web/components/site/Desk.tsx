"use client";

import { useEffect, useState } from "react";
import { Section } from "./chrome";
import { GateGraphic, PayoffDiagram, PnlDistribution, VolSmile } from "./visuals";

const ADVANCE_MS = 6000;

const AGENTS = [
  {
    n: "01",
    name: "Macro & Volatility Analyst",
    q: "What is the market doing?",
    body:
      "Measures implied against a jump-robust forecast of realised volatility on eight liquid "
      + "names. Emits a stance, a directional bias — and about half the time, a documented "
      + "refusal to trade at all.",
    out: "regime + variance risk premium",
    art: <VolSmile className="w-full" />,
    accent: "info" as const,
  },
  {
    n: "02",
    name: "Options Structurer",
    q: "What trade expresses that?",
    body:
      "Delta-targeted strikes, a width ladder scaled to spot, a hard liquidity floor, and "
      + "position size taken from the risk gate's own sizer. Wing geometry is correct by "
      + "construction, not checked afterwards.",
    out: "8 priced, defined-risk candidates",
    art: <PayoffDiagram className="w-full" />,
    accent: "gain" as const,
  },
  {
    n: "03",
    name: "Adversarial Risk Auditor",
    q: "What is wrong with it?",
    body:
      "Re-derives every Greek from scratch rather than trusting the structurer, then runs 1,000 "
      + "jump-diffusion paths under two volatility measures. Holds fatal-objection authority and "
      + "uses it.",
    out: "pass, or a veto",
    art: <PnlDistribution className="w-full" />,
    accent: "loss" as const,
  },
  {
    n: "04",
    name: "Execution Agent",
    q: "Route it, or don't.",
    body:
      "Re-runs the entire risk gate on the exact proposal being sent, then submits a multi-leg "
      + "order through Alpaca's official CLI with an idempotent client order id.",
    out: "mleg order on Alpaca",
    art: <GateGraphic className="w-full" />,
    accent: "gain" as const,
  },
];

const ACCENT = {
  info: { text: "text-info", bg: "bg-info", border: "border-info/40" },
  gain: { text: "text-gain", bg: "bg-gain", border: "border-gain/40" },
  loss: { text: "text-loss", bg: "bg-loss", border: "border-loss/40" },
};

export function Desk() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const [still, setStill] = useState(false);

  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setStill(q.matches);
    apply();
    q.addEventListener("change", apply);
    return () => q.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    if (paused || still) return;
    const t = setInterval(() => setActive((i) => (i + 1) % AGENTS.length), ADVANCE_MS);
    return () => clearInterval(t);
  }, [paused, still]);

  const a = AGENTS[active];
  const accent = ACCENT[a.accent];

  return (
    <Section
      id="desk"
      eyebrow="The desk"
      title="Four agents, and only one of them is a language model."
      lead="The reasoning layer is shown finished, priced candidates and returns exactly one integer index — bounds-checked. It cannot change a strike, a width, a premium or a size. A total model failure degrades to a deterministic ranker, not to a bad trade."
      center
    >
      <div
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {/* ── the rail ───────────────────────────────────────────────── */}
        <ol className="relative grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ink-line bg-ink-line md:grid-cols-4">
          {AGENTS.map((agent, i) => {
            const on = i === active;
            const tone = ACCENT[agent.accent];
            return (
              <li key={agent.n} className="relative bg-ink-card">
                <button
                  onClick={() => setActive(i)}
                  aria-current={on ? "step" : undefined}
                  className={`group/step relative w-full px-4 py-4 text-left transition-colors ${
                    on ? "bg-ink-raised" : "hover:bg-ink-raised/60"
                  }`}
                >
                  <div className="flex items-baseline gap-2.5">
                    <span
                      className={`font-mono text-[11px] font-bold transition-colors ${
                        on ? tone.text : "text-faint"
                      }`}
                    >
                      {agent.n}
                    </span>
                    <span
                      className={`font-sans text-[12.5px] font-medium leading-tight transition-colors ${
                        on ? "text-body" : "text-muted"
                      }`}
                    >
                      {agent.name}
                    </span>
                  </div>

                  {/* Progress bar: fills across the active step, so the rail
                      reads as a pipeline advancing rather than a tab strip. */}
                  <span className="absolute inset-x-0 bottom-0 h-[2px] bg-ink-line">
                    <span
                      key={`${i}-${active}-${paused}`}
                      className={`block h-full ${tone.bg}`}
                      style={
                        on
                          ? still || paused
                            ? { width: "100%" }
                            : { animation: `stepFill ${ADVANCE_MS}ms linear forwards` }
                          : { width: 0 }
                      }
                    />
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {/* ── the detail ─────────────────────────────────────────────── */}
        <div className="mt-4 grid items-stretch gap-4 lg:grid-cols-[1.25fr_1fr]">
          <div
            key={`t${active}`}
            className={`flex flex-col justify-center rounded-xl border border-ink-line bg-ink-card p-7 ${
              still ? "" : "animate-rise"
            }`}
          >
            <div className="flex items-baseline gap-3">
              <span className={`font-mono text-[12px] font-bold ${accent.text}`}>{a.n}</span>
              <h3 className="font-sans text-[19px] font-semibold text-body">{a.name}</h3>
            </div>
            <p className="mt-1 font-mono text-[12px] text-muted">{a.q}</p>
            <p className="mt-5 max-w-prose font-sans text-[14px] leading-[1.75] text-muted">
              {a.body}
            </p>
            <div className="mt-6 flex items-center gap-2 border-t border-ink-line pt-4 font-mono text-[11.5px]">
              <span className="text-faint">→</span>
              <span className={accent.text}>{a.out}</span>
            </div>
          </div>

          <div
            key={`a${active}`}
            className={`flex items-center justify-center rounded-xl border border-ink-line bg-ink-raised/60 p-7 ${
              still ? "" : "animate-rise"
            }`}
          >
            <div className="w-full max-w-[340px]">{a.art}</div>
          </div>
        </div>

        {/* ── the one that may be wrong ──────────────────────────────── */}
        <div className="mt-4 flex flex-col items-start gap-4 rounded-xl border border-warn/25 bg-warn/[0.04] p-6 sm:flex-row sm:items-center">
          <span className="shrink-0 rounded-full border border-warn/40 bg-warn/10 px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.1em] text-warn">
            the only LLM in the system
          </span>
          <p className="font-sans text-[13.5px] leading-[1.7] text-muted">
            Between stages 2 and 3, Featherless AI picks one candidate from the list — or abstains.
            Its entire output surface is{" "}
            <span className="font-mono text-[12.5px] text-body">
              {"{ index, confidence, rationale }"}
            </span>
            . A model that hallucinates index 9999 is ignored, not indexed with.
          </p>
        </div>
      </div>
    </Section>
  );
}
