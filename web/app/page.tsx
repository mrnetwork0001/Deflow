import Link from "next/link";
import { Breakers } from "@/components/landing/Breakers";
import { LiveStrip } from "@/components/landing/LiveStrip";
import { Pipeline } from "@/components/landing/Pipeline";
import { Card, GITHUB_URL, Mark, Nav, Section } from "@/components/landing/Shell";

export default function Landing() {
  return (
    <>
      <Nav />

      {/* ───────────────────────── Hero ───────────────────────── */}
      <header className="relative overflow-hidden px-5 pb-16 pt-20 sm:pt-28">
        {/* Faint payoff-diagram grid, purely atmospheric. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "linear-gradient(#11161f 1px, transparent 1px), linear-gradient(90deg, #11161f 1px, transparent 1px)",
            backgroundSize: "56px 56px",
            maskImage: "radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%)",
            WebkitMaskImage: "radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%)",
          }}
        />

        <div className="relative mx-auto max-w-content">
          <div className="inline-flex items-center gap-2 rounded-full border border-ink-line bg-ink-raised px-3 py-1">
            <span className="live-dot text-[8px] text-gain">●</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted">
              lablab.ai × Alpaca · AI Trading Agents Hackathon
            </span>
          </div>

          <h1 className="mt-7 max-w-4xl font-sans text-[40px] font-bold leading-[1.08] tracking-[-0.02em] text-body sm:text-[58px]">
            An options desk where the AI is the{" "}
            <span className="text-gain">least-trusted component</span>.
          </h1>

          <p className="mt-6 max-w-2xl font-sans text-[17px] leading-relaxed text-muted">
            Deflow trades defined-risk option spreads on Alpaca paper trading, harvesting the gap
            between the volatility options are priced at and the volatility stocks actually deliver.
            Four agents propose. Twelve deterministic circuit breakers decide.{" "}
            <span className="text-body">No model ever produces a number that reaches the broker.</span>
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              href="/dashboard/"
              className="group rounded-lg bg-gain px-6 py-3 font-mono text-[13px] font-bold text-ink transition hover:bg-gain/85"
            >
              Launch app
              <span className="ml-2 inline-block transition group-hover:translate-x-0.5">→</span>
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-ink-line bg-ink-raised px-6 py-3 font-mono text-[13px] text-body transition hover:border-muted"
            >
              View source
            </a>
            <code className="rounded-lg border border-ink-line/60 px-4 py-3 font-mono text-[12px] text-muted">
              $ python main.py
            </code>
          </div>

          <LiveStrip />
        </div>
      </header>

      {/* ───────────────────────── The edge ───────────────────────── */}
      <Section
        id="edge"
        eyebrow="The edge"
        title="Probability of profit is not an edge. Expectancy is."
        lead="Under the risk-neutral measure every vertical spread is worth exactly what it costs. Score a candidate at its own implied volatility and every trade prices at zero — the correct answer, and a useless one. So Deflow scores each candidate twice, and trades the difference."
      >
        <div className="grid gap-4 lg:grid-cols-[1.15fr_1fr]">
          <Card>
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-ink-line font-mono text-[10px] uppercase tracking-wider text-muted">
                  <th className="pb-2 font-medium">Measure</th>
                  <th className="pb-2 font-medium">Volatility</th>
                  <th className="pb-2 font-medium">What it tells you</th>
                </tr>
              </thead>
              <tbody className="font-sans text-[13px]">
                <tr className="border-b border-ink-line/40">
                  <td className="py-3 pr-4 font-mono text-[12px] text-info">risk-neutral</td>
                  <td className="py-3 pr-4 text-muted">implied</td>
                  <td className="py-3 text-muted">What the market says it is worth — ≈ 0 EV, as arbitrage requires</td>
                </tr>
                <tr>
                  <td className="py-3 pr-4 font-mono text-[12px] text-gain">physical</td>
                  <td className="py-3 pr-4 text-muted">realised (HV60)</td>
                  <td className="py-3 text-muted">What it is worth if the stock keeps moving as it has been</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-5 border-t border-ink-line pt-4 font-sans text-[13.5px] leading-relaxed text-muted">
              The dollar gap between those two rows <span className="text-body">is</span> the variance
              risk premium, and it is the only reason to put the trade on. Anything with non-positive
              expectancy under the physical measure is refused —{" "}
              <span className="text-body">however high its win rate</span>.
            </p>
          </Card>

          <Card className="flex flex-col justify-between border-loss/25">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-loss">
                A trade Deflow refuses
              </div>
              <div className="mt-4 space-y-2.5 font-mono text-[12px]">
                {[
                  ["structure", "SPY bull put spread", "text-body"],
                  ["probability of profit", "79%", "text-gain"],
                  ["you keep", "$320 · four times in five", "text-gain"],
                  ["you lose", "$1,680 · the fifth time", "text-loss"],
                ].map(([k, v, tone]) => (
                  <div key={k} className="flex items-baseline justify-between gap-3">
                    <span className="text-muted">{k}</span>
                    <span className={`tabular font-semibold ${tone}`}>{v}</span>
                  </div>
                ))}
                <div className="mt-3 flex items-baseline justify-between gap-3 border-t border-ink-line pt-3">
                  <span className="text-muted">expected value</span>
                  <span className="tabular text-base font-bold text-loss">−$112</span>
                </div>
              </div>
            </div>
            <p className="mt-5 font-sans text-[13px] leading-relaxed text-muted">
              A high win rate is not an edge. It is a way to lose money slowly and feel good about it.
              The auditor kills this trade before the risk gate ever sees it.
            </p>
          </Card>
        </div>
      </Section>

      {/* ───────────────────────── Pipeline ───────────────────────── */}
      <Section
        id="pipeline"
        eyebrow="Pipeline"
        title="Six stages. One of them is allowed to be wrong."
        lead="Every stage writes to a hash-chained ledger — including the stages that decide not to trade. Roughly half of all symbol-cycles end in a documented refusal, and a desk that only logs its fills cannot be audited."
      >
        <Pipeline />
      </Section>

      {/* ───────────────────────── Risk gate ───────────────────────── */}
      <Section
        id="gate"
        eyebrow="The risk gate"
        title="Twelve breakers, no network, no prompt, 1.4 microseconds."
        lead="risk_gate.py imports nothing but the standard library. Given the same proposal and the same book it returns the same verdict, forever. It fails closed on anything malformed, runs all twelve breakers even after one fails so the audit trail stays complete, and has no code path that can widen a limit or increase a size."
      >
        <Breakers />
      </Section>

      {/* ───────────────────────── Alpaca ───────────────────────── */}
      <Section
        id="alpaca"
        eyebrow="Built on Alpaca"
        title="All three surfaces, each for what it is best at."
      >
        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              t: "Trading API",
              s: "Order routing & market data",
              d: "Written directly against the HTTP surface so the multi-leg payload is visible in one place. Account, positions, daily bars, option-chain snapshots with NBBO and server-side Greeks.",
              note: "Refuses to initialise against a non-paper endpoint.",
            },
            {
              t: "Alpaca CLI",
              s: "Default order route",
              d: "The official Go binary is what an unattended agent gets deployed behind: its own 429/5xx backoff, its own credential resolution, and --dry-run to render the exact request without sending it.",
              note: "Every order carries an idempotent client order id.",
            },
            {
              t: "MCP server",
              s: "Structured discovery",
              d: "Alpaca's FastMCP server spoken as JSON-RPC over stdio with no SDK dependency, resolving tool names at runtime so a server update cannot break the integration.",
              note: "Chains, contracts and account state as typed tools.",
            },
          ].map((c) => (
            <Card key={c.t} className="flex flex-col">
              <h3 className="font-sans text-[15px] font-semibold text-body">{c.t}</h3>
              <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-gain">{c.s}</div>
              <p className="mt-3 flex-1 font-sans text-[13px] leading-relaxed text-muted">{c.d}</p>
              <p className="mt-4 border-t border-ink-line pt-3 font-mono text-[11px] text-muted">{c.note}</p>
            </Card>
          ))}
        </div>

        <div className="mt-4 rounded-xl border border-ink-line bg-ink-raised p-5">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
            A real multi-leg order, as routed
          </div>
          <pre className="overflow-x-auto font-mono text-[11.5px] leading-relaxed text-muted">
{`alpaca order submit --order-class mleg --qty 4 --type limit \\
  --limit-price -1.35 \\
  --legs '[{"symbol":"SPY261016P00540000","ratio_qty":"1",
            "side":"sell","position_intent":"sell_to_open"},
           {"symbol":"SPY261016P00535000","ratio_qty":"1",
            "side":"buy","position_intent":"buy_to_open"}]'`}
          </pre>
          <p className="mt-3 font-sans text-[12.5px] text-muted">
            Negative limit price because Alpaca quotes multi-leg packages net —{" "}
            <span className="text-body">positive is a debit paid, negative is a credit received</span>.
          </p>
        </div>
      </Section>

      {/* ───────────────────────── Auditability ───────────────────────── */}
      <Section
        eyebrow="Auditability"
        title="Results you can check, not results you have to believe."
        lead="Every decision — each analyst view, proposal, audit, gate verdict, order and exit — is appended as one line carrying the SHA-256 of the line before it. Edit or delete any historical entry and the chain breaks, and the API tells you the exact index where."
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            ["Tamper-evident", "Modify entry 3 of 6 and verify() reports broken_at: 3. Delete one and it reports the same."],
            ["Survives restarts", "The chain head is recovered from the existing file on startup, so a restart continues the chain instead of forking it."],
            ["Refusals included", "Stand-downs, abstentions and vetoes are logged with the numbers that produced them — not just the fills."],
          ].map(([t, d]) => (
            <Card key={t}>
              <h3 className="font-mono text-[12px] font-bold text-gain">{t}</h3>
              <p className="mt-2 font-sans text-[13px] leading-relaxed text-muted">{d}</p>
            </Card>
          ))}
        </div>
      </Section>

      {/* ───────────────────────── CTA ───────────────────────── */}
      <section className="border-t border-ink-line/60 px-5 py-24">
        <div className="mx-auto max-w-content text-center">
          <Mark size={34} />
          <h2 className="mt-6 font-sans text-[30px] font-semibold tracking-tight text-body sm:text-[38px]">
            Watch it refuse a trade.
          </h2>
          <p className="mx-auto mt-4 max-w-xl font-sans text-[15px] leading-relaxed text-muted">
            The dashboard streams every decision live — the regime read on eight names, the open book
            with Greeks, and a button that fires a naked call at the running risk gate.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/dashboard/"
              className="group rounded-lg bg-gain px-7 py-3.5 font-mono text-[13px] font-bold text-ink transition hover:bg-gain/85"
            >
              Launch app
              <span className="ml-2 inline-block transition group-hover:translate-x-0.5">→</span>
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-ink-line bg-ink-raised px-7 py-3.5 font-mono text-[13px] text-body transition hover:border-muted"
            >
              Read the code
            </a>
          </div>
        </div>
      </section>

      {/* ───────────────────────── Footer ───────────────────────── */}
      <footer className="border-t border-ink-line/60 px-5 py-10">
        <div className="mx-auto flex max-w-content flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xl">
            <div className="flex items-center gap-2">
              <Mark size={16} />
              <span className="font-mono text-[12px] font-bold text-body">DEFLOW</span>
            </div>
            <p className="mt-3 font-sans text-[12px] leading-relaxed text-muted">
              Paper trading only. Paper-trading results are hypothetical, do not involve actual
              securities transactions, and do not guarantee future results. Options carry substantial
              risk of loss and are not suitable for every investor. Not investment advice.
            </p>
          </div>
          <div className="flex gap-8 font-mono text-[11px]">
            <div className="space-y-2">
              <div className="text-muted">Project</div>
              <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="block text-body hover:text-gain">GitHub</a>
              <Link href="/dashboard/" className="block text-body hover:text-gain">Dashboard</Link>
              <a href="/docs" className="block text-body hover:text-gain">API docs</a>
            </div>
            <div className="space-y-2">
              <div className="text-muted">Built with</div>
              <a href="https://alpaca.markets" target="_blank" rel="noreferrer" className="block text-body hover:text-gain">Alpaca</a>
              <a href="https://featherless.ai" target="_blank" rel="noreferrer" className="block text-body hover:text-gain">Featherless AI</a>
              <a href="https://lablab.ai" target="_blank" rel="noreferrer" className="block text-body hover:text-gain">lablab.ai</a>
            </div>
          </div>
        </div>
        <div className="mx-auto mt-8 max-w-content border-t border-ink-line/60 pt-5 font-mono text-[11px] text-muted">
          MIT licensed · Built by Ifeanyichukwu Onwo for the lablab.ai × Alpaca AI Trading Agents Hackathon
        </div>
      </footer>
    </>
  );
}
