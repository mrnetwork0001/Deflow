import Link from "next/link";
import { Wordmark } from "@/components/site/chrome";

/* Interim documentation page: real content, deliberately compact. The
   structure below (anchored sections, one table of endpoints, one of
   breakers) is expected to be reshaped when the full docs format lands —
   keep sections self-contained so replacing one does not disturb the rest. */

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2
      id={id}
      className="mb-3 mt-12 scroll-mt-24 border-b border-ink-line pb-2 font-mono text-[13px] font-semibold uppercase tracking-[0.14em] text-body"
    >
      {children}
    </h2>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 max-w-[72ch] font-sans text-[13.5px] leading-[1.75] text-muted">
      {children}
    </p>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-ink-raised px-1.5 py-0.5 font-mono text-[12px] text-body">
      {children}
    </code>
  );
}

const AGENTS: Array<[string, string]> = [
  [
    "Agent 1 · Macro & Volatility Analyst",
    "Scans the universe each cycle. Measures the variance risk premium — 30-day implied volatility against a jump-robust bipower forecast of realised volatility — and classifies each name's regime. Most refusals happen here: a premium inside the noise band is no edge, and the desk stands down.",
  ],
  [
    "Agent 2 · Options Structurer",
    "Turns a tradeable view into defined-risk spreads: verticals and condors with bounded max loss, strikes chosen from the live chain, priced from real quotes.",
  ],
  [
    "Agent 3 · Adversarial Risk Auditor",
    "Independently stress-tests every proposal and argues against it — Merton jump-diffusion Monte Carlo under the physical measure, round-trip cost from real bid/ask, probability of profit. A fatal objection ends the trade before the gate ever sees it.",
  ],
  [
    "Agent 4 · Execution Agent",
    "Routes approved structures to Alpaca as native multi-leg orders, re-checking the gate immediately before submission. Submission is not a fill: orders are tracked as working until the broker confirms, on entries and exits alike.",
  ],
];

const BREAKERS: Array<[string, string]> = [
  ["01 defined_risk_structure", "every structure must have a bounded max loss"],
  ["02 max_loss_2pct", "max loss of the trade ≤ 2% of account equity"],
  ["03 trade_delta_bound", "net delta of the structure within ±0.35"],
  ["04 probability_of_profit", "credit: ≥ 65% win rate · debit: ≥ 30% plus positive expectancy"],
  ["05 aggregate_risk_6pct", "capital at risk across the whole book ≤ 6% after the fill"],
  ["06 symbol_concentration_3pct", "risk in any one underlying ≤ 3%"],
  ["07 portfolio_delta_bound", "book net delta within ±1.2 after the fill"],
  ["08 max_open_positions", "at most 6 open structures"],
  ["09 dte_window", "7 to 60 days to expiry"],
  ["10 payoff_quality", "credit ≥ 15% of spread width · debit reward/risk ≥ 0.8"],
  ["11 daily_drawdown_killswitch", "trading halts at −3% on the day"],
  ["12 vega_ceiling", "book |vega| ≤ 2.5 per $1,000 of equity"],
];

const ENDPOINTS: Array<[string, string]> = [
  ["GET /api/status", "everything the dashboard shows: performance, market state, working orders"],
  ["GET /api/performance", "equity and P&L on the broker's marks, with the desk's mid-marks labelled"],
  ["GET /api/positions", "open and closed structures"],
  ["GET /api/refusals", "every trade the desk declined, attributed to the stage that said no"],
  ["GET /api/ledger", "the hash-chained decision ledger, filterable by event"],
  ["GET /api/ledger/verify", "re-derives the chain and reports the first break, if any"],
  ["GET /api/pnl-card?date=", "one trading day summarised for a shareable card"],
  ["GET /api/stream", "server-sent events: the decision stream, live"],
  ["POST /api/cycle", "run one full trading cycle now"],
  ["POST /api/risk/evaluate", "submit a hypothetical trade and watch the twelve breakers rule on it"],
];

export default function DocsPage() {
  return (
    <main className="mx-auto max-w-[900px] p-4 sm:p-6">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <Link href="/" className="group flex items-center gap-4" aria-label="Deflow home">
          <Wordmark height={30} className="transition-opacity group-hover:opacity-80" />
          <span className="hidden border-l border-ink-line pl-4 font-mono text-[11px] text-muted sm:inline">
            documentation
          </span>
        </Link>
        <nav className="flex items-center gap-2.5">
          <Link
            href="/"
            className="rounded-md px-3 py-2 font-mono text-[11px] text-muted transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
          >
            Overview
          </Link>
          <Link
            href="/ledger/"
            className="rounded-md px-3 py-2 font-mono text-[11px] text-muted transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
          >
            Ledger
          </Link>
          <Link
            href="/dashboard/"
            className="inline-flex items-center gap-2 rounded-md bg-gain px-4 py-2 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-ink transition-colors hover:bg-gain-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gain/50"
          >
            Live desk →
          </Link>
        </nav>
      </header>

      <h1 className="font-mono text-[22px] font-bold text-body">Deflow documentation</h1>
      <P>
        Deflow is an autonomous options trading desk: four specialised agents that observe,
        structure, audit and route defined-risk option spreads on a live Alpaca paper account —
        under a deterministic risk gate that no language model can talk its way past, with every
        decision written to a tamper-evident ledger.
      </P>

      <H2 id="pipeline">The pipeline</H2>
      <P>
        Every five minutes during market hours the desk runs one cycle:{" "}
        <Code>analyse → structure → reason → audit → gate → route</Code>. Roughly half of all
        symbol-cycles end in a refusal, and refusals are first-class output — each one is recorded
        with the stage that made it and the reason why.
      </P>

      <H2 id="agents">The four agents</H2>
      <div className="space-y-4">
        {AGENTS.map(([name, blurb]) => (
          <div key={name}>
            <h3 className="mb-1 font-mono text-[12.5px] font-semibold text-gain">{name}</h3>
            <P>{blurb}</P>
          </div>
        ))}
      </div>

      <H2 id="gate">The deterministic risk gate</H2>
      <P>
        Twelve circuit breakers, pure standard-library Python, zero LLM involvement, microseconds
        per evaluation. All twelve always run — no short-circuiting — and the gate runs twice:
        once at approval, again immediately before the order leaves. It fails closed.
      </P>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[11.5px]">
          <tbody>
            {BREAKERS.map(([name, rule]) => (
              <tr key={name} className="border-b border-ink-line">
                <td className="whitespace-nowrap py-2 pr-6 text-body">{name}</td>
                <td className="py-2 text-muted">{rule}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <H2 id="ledger">The decision ledger</H2>
      <P>
        Every event — analyst views, proposals, audits, verdicts, orders, fills, exits, refusals —
        is appended to a hash chain: each entry carries the SHA-256 of the one before it, so
        altering or deleting any historical record breaks the chain from that point forward.{" "}
        <Link href="/ledger/" className="text-gain hover:underline">
          Verify it yourself
        </Link>
        .
      </P>

      <H2 id="run">Run it yourself</H2>
      <pre className="mb-3 overflow-x-auto rounded-lg border border-ink-line bg-ink-raised p-4 font-mono text-[12px] leading-relaxed text-body">
        {`git clone https://github.com/mrnetwork0001/Deflow.git && cd Deflow
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your Alpaca + Featherless keys
.venv/bin/python main.py`}
      </pre>
      <P>
        One command brings up the desk, the API and this dashboard. With no credentials it runs
        against a seeded simulated market; with Alpaca keys it trades the paper account. Set{" "}
        <Code>DEFLOW_DRY_RUN=true</Code> to run the full pipeline without submitting orders.
      </P>

      <H2 id="api">API</H2>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[11.5px]">
          <tbody>
            {ENDPOINTS.map(([ep, what]) => (
              <tr key={ep} className="border-b border-ink-line">
                <td className="whitespace-nowrap py-2 pr-6 text-body">{ep}</td>
                <td className="py-2 text-muted">{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="mt-12 border-t border-ink-line pt-4 font-mono text-[10.5px] text-faint">
        Paper trading only. Simulated results are hypothetical and do not represent actual trading.
      </footer>
    </main>
  );
}
