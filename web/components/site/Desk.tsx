"use client";

import { Card, Pill, Section } from "./chrome";
import { GateGraphic, PayoffDiagram, PnlDistribution, VolSmile } from "./visuals";

const AGENTS = [
  {
    n: "01",
    name: "Macro & Volatility Analyst",
    q: "What is the market doing?",
    body:
      "Measures implied against a jump-robust forecast of realised volatility on eight liquid "
      + "names. Emits a stance, a directional bias — and about half the time, a documented refusal.",
    out: "regime + variance risk premium",
    art: <VolSmile className="w-full" />,
  },
  {
    n: "02",
    name: "Options Structurer",
    q: "What trade expresses that?",
    body:
      "Delta-targeted strikes, a width ladder scaled to spot, a hard liquidity floor, and position "
      + "size taken from the risk gate's own sizer. Wing geometry is correct by construction.",
    out: "8 priced, defined-risk candidates",
    art: <PayoffDiagram className="w-full" />,
  },
  {
    n: "03",
    name: "Adversarial Risk Auditor",
    q: "What is wrong with it?",
    body:
      "Re-derives every Greek from scratch rather than trusting the structurer, then runs 1,000 "
      + "jump-diffusion paths under two volatility measures. Has fatal-objection authority.",
    out: "pass, or a veto",
    art: <PnlDistribution className="w-full" />,
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
  },
];

export function Desk() {
  return (
    <Section
      id="desk"
      eyebrow="The desk"
      title="Four agents, and only one of them is a language model."
      lead="The reasoning layer is shown finished, priced candidates and returns exactly one integer index — bounds-checked. It cannot change a strike, a width, a premium or a size. A total model failure degrades to a deterministic ranker, not to a bad trade."
      center
    >
      <div className="grid gap-4 lg:grid-cols-2">
        {AGENTS.map((a) => (
          <Card key={a.n} className="flex flex-col overflow-hidden">
            <div className="border-b border-ink-line bg-ink-raised/60 px-6 pt-6">
              {a.art}
            </div>
            <div className="flex flex-1 flex-col p-6">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-[11px] text-faint">{a.n}</span>
                <h3 className="font-sans text-[17px] font-semibold text-body">{a.name}</h3>
              </div>
              <div className="mt-1 font-mono text-[11.5px] text-muted">{a.q}</div>
              <p className="mt-4 flex-1 font-sans text-[13.5px] leading-[1.7] text-muted">{a.body}</p>
              <div className="mt-5 flex items-center gap-2 border-t border-ink-line pt-4 font-mono text-[11px]">
                <span className="text-faint">→</span>
                <span className="text-gain">{a.out}</span>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card className="mt-4 flex flex-col items-start gap-5 border-warn/25 p-6 sm:flex-row sm:items-center">
        <Pill tone="warn">the only LLM in the system</Pill>
        <p className="font-sans text-[13.5px] leading-[1.7] text-muted">
          Between stages 2 and 3, Featherless AI picks one candidate from the list — or abstains.
          Its entire output surface is{" "}
          <span className="font-mono text-[12.5px] text-body">
            {"{ index, confidence, rationale }"}
          </span>
          . A model that hallucinates index 9999 is ignored, not indexed with.
        </p>
      </Card>
    </Section>
  );
}
