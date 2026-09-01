"use client";

import { ButtonLink, Card, Section } from "./chrome";
import { RevealGroup } from "./Reveal";
import { ChainGraphic } from "./visuals";

export function Audit() {
  return (
    <Section
      id="audit"
      eyebrow="Auditability"
      title="Results you can check, not results you have to believe."
      lead="Every decision — each analyst view, proposal, audit, gate verdict, order and exit — is appended as one line carrying the SHA-256 of the line before it. Edit or delete any historical entry and the chain breaks, and the API reports the exact index where."
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <Card className="flex flex-col justify-between p-6">
          <ChainGraphic className="w-full" />
          <div className="mt-6 rounded-lg border border-ink-line bg-ink p-4 font-mono text-[11.5px] leading-relaxed">
            <div className="text-faint">GET /api/ledger/verify</div>
            <div className="mt-2 text-gain">{"{"}</div>
            <div className="text-gain">{'  "valid": true,'}</div>
            <div className="text-gain">{'  "entries": 1284,'}</div>
            <div className="text-gain">{'  "broken_at": null,'}</div>
            <div className="text-muted">{'  "detail": "Chain intact — every'}</div>
            <div className="text-muted">{'   entry hashes to its successor."'}</div>
            <div className="text-gain">{"}"}</div>
          </div>
        </Card>

        <div className="grid gap-4">
          <RevealGroup step={90}>
          {[
            ["Tamper-evident", "Modify entry 3 of 6 and verification reports broken_at: 3. Delete one and it reports the same. A log tells you what a system says it did; this tells you whether the story was edited afterwards."],
            ["Refusals included", "Stand-downs, abstentions and vetoes are logged with the numbers that produced them. A desk that records only its fills cannot be audited — and for this strategy, the refusals are most of the behaviour."],
            ["Survives concurrency", "Appends take an exclusive file lock and re-derive the head underneath it, so two processes sharing a data directory chain onto each other instead of forking. Verified with four concurrent writers."],
          ].map(([t, d]) => (
            <Card key={t} className="p-6">
              <h3 className="font-sans text-[16px] font-semibold text-body">{t}</h3>
              <p className="mt-2.5 font-sans text-[13.5px] leading-[1.7] text-muted">{d}</p>
            </Card>
          ))}
          </RevealGroup>
          <div className="pt-1">
            <ButtonLink href="/ledger/" variant="ghost">Read the live ledger</ButtonLink>
          </div>
        </div>
      </div>
    </Section>
  );
}
