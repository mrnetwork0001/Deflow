"use client";

import { Card, Section } from "./chrome";
import { RevealGroup } from "./Reveal";

const FAILURES = [
  {
    tag: "Unbounded",
    title: "The model sizes the trade",
    body:
      "Most agents let a language model choose the strike, the width and the position size. "
      + "A hallucinated number becomes an order. There is no layer that can say no, because the "
      + "layer that would say no is the same one that made the decision.",
  },
  {
    tag: "Undefined",
    title: "The risk has no floor",
    body:
      "Naked options and unhedged directional bets have no worst case. The position works for "
      + "weeks and then one gap erases the account. Nothing in the system knows what the maximum "
      + "loss is, because the structure does not have one.",
  },
  {
    tag: "Unverifiable",
    title: "The results cannot be checked",
    body:
      "A log tells you what a system says it did. It does not tell you whether the story was "
      + "edited afterwards, and it usually records only the fills — so the refusals, which are "
      + "most of what a risk system does, leave no trace at all.",
  },
];

export function Problem() {
  return (
    <Section
      id="problem"
      eyebrow="The problem"
      title="Autonomous trading agents fail in three predictable ways."
      lead="Each of them is a structural property, not a tuning problem — so Deflow is built to make each one impossible rather than unlikely."
      center
    >
      <div className="grid gap-4 md:grid-cols-3">
        <RevealGroup step={90}>
        {FAILURES.map((f, i) => (
          <Card key={f.tag} className="flex flex-col p-6">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-[11px] text-faint">{String(i + 1).padStart(2, "0")}</span>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-loss">{f.tag}</span>
            </div>
            <h3 className="mt-4 font-sans text-[17px] font-semibold text-body">{f.title}</h3>
            <p className="mt-3 font-sans text-[13.5px] leading-[1.7] text-muted">{f.body}</p>
          </Card>
        ))}
        </RevealGroup>
      </div>
    </Section>
  );
}
