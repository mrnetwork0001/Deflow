"use client";

import { Card, Section } from "./chrome";
import { RevealGroup } from "./Reveal";

const SURFACES = [
  {
    t: "Trading API",
    s: "Orders & market data",
    d: "Written directly against the HTTP surface so the multi-leg payload is visible in one place: account, positions, daily bars, option-chain snapshots with NBBO and server-side Greeks.",
    note: "Refuses to initialise against a non-paper endpoint.",
  },
  {
    t: "Alpaca CLI",
    s: "Default order route",
    d: "The official Go binary is the interface an unattended agent actually gets deployed behind — its own 429/5xx backoff, its own credential resolution, and --dry-run to render the exact request without sending it.",
    note: "Every order carries an idempotent client order id.",
  },
  {
    t: "MCP server",
    s: "Structured discovery",
    d: "Alpaca's FastMCP server spoken as JSON-RPC over stdio with no SDK dependency, resolving tool names at runtime so an upstream rename cannot break the integration.",
    note: "72 tools discovered; chains, contracts and account state.",
  },
  {
    t: "Featherless AI",
    s: "Bounded reasoning",
    d: "Serverless open-model inference for the one stage that is allowed to be wrong. Qwen2.5-72B picks among finished candidates and explains the choice in English.",
    note: "Any failure falls back to the deterministic ranker.",
  },
];

export function Stack() {
  return (
    <Section
      eyebrow="Built on"
      title="All three Alpaca surfaces, each for what it is best at."
      center
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <RevealGroup step={80}>
        {SURFACES.map((c) => (
          <Card key={c.t} className="flex flex-col p-6">
            <h3 className="font-sans text-[16px] font-semibold text-body">{c.t}</h3>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-gain">{c.s}</div>
            <p className="mt-4 flex-1 font-sans text-[13px] leading-[1.7] text-muted">{c.d}</p>
            <p className="mt-5 border-t border-ink-line pt-4 font-mono text-[11px] leading-relaxed text-faint">
              {c.note}
            </p>
          </Card>
        ))}
        </RevealGroup>
      </div>

      <Card className="mt-4 overflow-hidden p-6" hover={false}>
        <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
          A real multi-leg order, as routed
        </div>
        <pre className="overflow-x-auto font-mono text-[11.5px] leading-[1.8] text-muted">
{`alpaca order submit --order-class mleg --qty 4 --type limit \\
  --limit-price -1.35 \\
  --legs '[{"symbol":"SPY261016P00540000","ratio_qty":"1",
            "side":"sell","position_intent":"sell_to_open"},
           {"symbol":"SPY261016P00535000","ratio_qty":"1",
            "side":"buy","position_intent":"buy_to_open"}]'`}
        </pre>
        <p className="mt-4 font-sans text-[12.5px] text-muted">
          Negative limit price because Alpaca quotes multi-leg packages net —{" "}
          <span className="text-body">positive is a debit paid, negative is a credit received</span>.
        </p>
      </Card>
    </Section>
  );
}
