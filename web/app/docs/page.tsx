"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Wordmark, GITHUB_URL } from "@/components/site/chrome";

/* Documentation in the grouped-sidebar format: uppercase group labels, an
   accent-barred active item that follows the reader, a wide content column
   with key-value tables and code chips, on a faint grid texture. One route,
   anchored sections - the sidebar is a scrollspy, not a router. */

// ---------------------------------------------------------------------------
// Contents
// ---------------------------------------------------------------------------

const GROUPS: Array<{ label: string; items: Array<[string, string]> }> = [
  {
    label: "Getting started",
    items: [
      ["welcome", "Welcome to Deflow"],
      ["how", "How it works"],
    ],
  },
  {
    label: "The desk",
    items: [
      ["agents", "The four agents"],
      ["edge", "The edge: variance premium"],
    ],
  },
  {
    label: "Risk",
    items: [
      ["gate", "The deterministic gate"],
      ["exits", "Order & exit lifecycle"],
    ],
  },
  {
    label: "Auditability",
    items: [
      ["ledger", "Decision ledger"],
      ["refusals", "Refusals"],
    ],
  },
  {
    label: "Operate",
    items: [
      ["run", "Self-hosting & running"],
      ["api", "HTTP API"],
    ],
  },
  {
    label: "Trust",
    items: [["trust", "Trust model & FAQ"]],
  },
];

const ALL_IDS = GROUPS.flatMap((g) => g.items.map(([id]) => id));

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
  ["POST /api/risk/evaluate", "submit a hypothetical trade; the twelve breakers rule on it"],
];

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

function H1({ children }: { children: React.ReactNode }) {
  return (
    <h1 className="mb-5 font-sans text-[34px] font-bold leading-tight tracking-tight text-white sm:text-[40px]">
      {children}
    </h1>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-4 mt-10 font-sans text-[24px] font-bold tracking-tight text-white">
      {children}
    </h2>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 max-w-[78ch] font-sans text-[15px] leading-[1.8] text-muted">{children}</p>
  );
}

function B({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-body">{children}</strong>;
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <code className="whitespace-nowrap rounded border border-ink-hair bg-ink-raised px-2 py-0.5 font-mono text-[12px] text-body">
      {children}
    </code>
  );
}

function G({ href, children, external = false }: { href: string; children: React.ReactNode; external?: boolean }) {
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
      className="font-mono text-[13px] text-gain hover:underline"
    >
      {children}
    </a>
  );
}

/** Key-value rows with hairline separators, the format's signature table. */
function KV({ rows }: { rows: Array<[React.ReactNode, React.ReactNode]> }) {
  return (
    <div className="mb-4 border-t border-ink-line">
      {rows.map(([k, v], i) => (
        <div
          key={i}
          className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-ink-line py-3"
        >
          <span className="font-sans text-[13.5px] text-muted">{k}</span>
          <span className="min-w-0">{v}</span>
        </div>
      ))}
    </div>
  );
}

function Rule() {
  return <hr className="my-10 border-ink-line" />;
}

/** A doc section: the anchor target the sidebar tracks. */
function DocSection({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24">
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DocsPage() {
  const [active, setActive] = useState<string>(ALL_IDS[0]);
  const lock = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let frame = 0;
    const READING_LINE = 120;
    const measure = () => {
      frame = 0;
      let found = ALL_IDS[0];
      for (const id of ALL_IDS) {
        const top = document.getElementById(id)?.getBoundingClientRect().top;
        if (top === undefined || top > READING_LINE) continue;
        found = id;
      }
      // The last section can be too short to ever cross the reading line.
      const doc = document.documentElement;
      if (
        doc.scrollHeight > window.innerHeight + 2 &&
        window.scrollY + window.innerHeight >= doc.scrollHeight - 2
      ) {
        found = ALL_IDS[ALL_IDS.length - 1];
      }
      setActive(found);
    };
    const schedule = () => {
      if (lock.current) return; // a click chose the target; let the scroll land
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  const onNavClick = (id: string) => {
    // Highlight the destination immediately and ignore the highlights the
    // smooth scroll would otherwise strobe through on the way down.
    setActive(id);
    clearTimeout(lock.current);
    lock.current = setTimeout(() => {
      lock.current = undefined;
    }, 700);
  };

  return (
    <div
      className="min-h-screen bg-ink"
      style={{
        backgroundImage:
          "linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px), " +
          "linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px)",
        backgroundSize: "56px 56px",
      }}
    >
      {/* ---- top bar ---------------------------------------------------- */}
      <header className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-5">
        <Link href="/" className="group flex items-center" aria-label="Deflow home">
          <Wordmark height={30} className="transition-opacity group-hover:opacity-80" />
        </Link>
        <nav className="flex items-center gap-6 sm:gap-8">
          {(
            [
              ["APP", "/dashboard/", false],
              ["LEDGER", "/ledger/", false],
              ["GITHUB", GITHUB_URL, true],
            ] as Array<[string, string, boolean]>
          ).map(([label, href, external]) => (
            <a
              key={label}
              href={href}
              {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
              className="font-mono text-[11px] tracking-[0.22em] text-muted transition-colors hover:text-body"
            >
              {label}
            </a>
          ))}
        </nav>
      </header>

      <div className="mx-auto grid max-w-[1400px] gap-12 px-6 pb-24 pt-6 lg:grid-cols-[250px_minmax(0,1fr)]">
        {/* ---- sidebar -------------------------------------------------- */}
        <aside className="hidden lg:block">
          <nav aria-label="Documentation sections" className="sticky top-8">
            {GROUPS.map((group) => (
              <div key={group.label} className="mb-7">
                <div className="mb-2.5 font-mono text-[10px] uppercase tracking-[0.24em] text-faint">
                  {group.label}
                </div>
                <ul>
                  {group.items.map(([id, label]) => {
                    const on = active === id;
                    return (
                      <li key={id}>
                        <a
                          href={`#${id}`}
                          onClick={() => onNavClick(id)}
                          aria-current={on ? "true" : undefined}
                          className={`block border-l-2 py-1.5 pl-4 font-sans text-[13.5px] transition-colors ${
                            on
                              ? "border-gain bg-gain/[0.06] text-gain"
                              : "border-ink-line text-muted hover:border-ink-hair hover:text-body"
                          }`}
                        >
                          {label}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        {/* ---- content -------------------------------------------------- */}
        <main className="min-w-0 max-w-[860px]">
          <DocSection id="welcome">
            <H1>Welcome to Deflow</H1>
            <P>
              <B>Deflow is an autonomous options trading desk.</B> Four specialised agents observe
              the market, structure defined-risk option spreads, audit them adversarially and route
              them to a live Alpaca paper account - under a deterministic risk gate that no language
              model can talk its way past.
            </P>
            <P>
              The AI is not a chat feature bolted onto a trading bot. The agents run the desk end to
              end on a five-minute cycle, and <B>refusing to trade is a first-class output</B>:
              roughly half of all symbol-cycles end with the desk declining, on the record, with the
              stage and reason attached. Every decision is written to a hash-chained ledger anyone
              can verify.
            </P>
            <ul className="mb-6 max-w-[78ch] space-y-2 font-sans text-[15px] leading-[1.8] text-muted">
              <li>
                • <B>Measured, not vibes</B> - implied volatility against a jump-robust forecast of
                realised volatility
              </li>
              <li>
                • <B>Bounded, always</B> - every structure has a defined maximum loss before it is
                ever proposed
              </li>
              <li>
                • <B>Checkable, forever</B> - a tamper-evident ledger and the broker&apos;s own
                marks on the dashboard
              </li>
            </ul>

            <Rule />

            <H2>Where everything lives</H2>
            <KV
              rows={[
                ["Live desk", <G key="a" href="/dashboard/">deflow dashboard</G>],
                ["Decision ledger", <G key="b" href="/ledger/">deflow ledger - verify the chain</G>],
                ["GitHub", <G key="c" href={GITHUB_URL} external>mrnetwork0001/Deflow</G>],
                ["Broker", <span key="d" className="font-sans text-[13.5px] text-body">Alpaca paper account · options level 3 · $100,000 start</span>],
                ["Reasoning model", <Chip key="e">Qwen/Qwen2.5-72B-Instruct via Featherless</Chip>],
                ["Risk gate", <span key="f" className="font-sans text-[13.5px] text-body">v2.0.0 · 12 deterministic breakers · stdlib only</span>],
                ["First live session", <Chip key="g">2026-09-01</Chip>],
              ]}
            />
          </DocSection>

          <DocSection id="how">
            <H2>How it works</H2>
            <P>
              Every five minutes during US market hours the desk runs one cycle over its universe
              (SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMD, TSLA):
            </P>
            <div className="mb-4 overflow-x-auto rounded-lg border border-ink-line bg-ink-raised p-4">
              <code className="whitespace-nowrap font-mono text-[13px] text-body">
                analyse → structure → reason → audit → gate → route → reconcile
              </code>
            </div>
            <P>
              The Analyst measures each name and refuses anything without a measured edge. The
              Structurer builds candidate spreads from the live chain. The reasoning model picks
              among them - <B>among them only</B>; it cannot invent a trade. The Auditor attacks the
              choice with Monte Carlo and real transaction costs. The gate rules. The Executor
              routes. And on the next cycle the desk reconciles: an accepted order is not a fill,
              and the book only changes when the broker confirms one.
            </P>
          </DocSection>

          <Rule />

          <DocSection id="agents">
            <H2>The four agents</H2>
            <KV
              rows={[
                [
                  <span key="1" className="font-mono text-[12.5px] text-gain">Agent 1 · Macro &amp; Volatility Analyst</span>,
                  <span key="1b" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    measures the variance risk premium and the trend regime for every name, and
                    stands down anything inside the noise band
                  </span>,
                ],
                [
                  <span key="2" className="font-mono text-[12.5px] text-gain">Agent 2 · Options Structurer</span>,
                  <span key="2b" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    turns a tradeable view into defined-risk verticals and condors, strikes from the
                    live chain, priced from real quotes
                  </span>,
                ],
                [
                  <span key="3" className="font-mono text-[12.5px] text-gain">Agent 3 · Adversarial Risk Auditor</span>,
                  <span key="3b" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    argues against every proposal: jump-diffusion Monte Carlo under the physical
                    measure, round-trip cost from the real bid/ask - a fatal objection kills the
                    trade before the gate sees it
                  </span>,
                ],
                [
                  <span key="4" className="font-mono text-[12.5px] text-gain">Agent 4 · Execution Agent</span>,
                  <span key="4b" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    routes approved structures to Alpaca as native multi-leg orders, re-checking the
                    gate immediately before submission
                  </span>,
                ],
              ]}
            />
          </DocSection>

          <DocSection id="edge">
            <H2>The edge: variance premium</H2>
            <P>
              Option prices embed a forecast of volatility. Deflow builds its own -{" "}
              <B>bipower variation</B>, a jump-robust estimator that a single earnings gap
              can&apos;t distort - and trades only the gap between the two, in either direction:
            </P>
            <KV
              rows={[
                ["Implied rich vs forecast (> +2%)", <span key="a" className="font-sans text-[13.5px] text-body">sell premium - credit spreads</span>],
                ["Implied cheap vs forecast (< −1%)", <span key="b" className="font-sans text-[13.5px] text-body">buy convexity - debit spreads</span>],
                ["Inside the band", <span key="c" className="font-sans text-[13.5px] text-body">stand down - no measured edge, no trade</span>],
              ]}
            />
            <P>
              The desk also reads the IV term structure for priced-in catalysts: an inverted curve
              means the market is paying up for an event, and short-dated premium selling stands
              down around it.
            </P>
          </DocSection>

          <Rule />

          <DocSection id="gate">
            <H2>The deterministic gate</H2>
            <P>
              Twelve circuit breakers, pure standard-library Python, <B>zero LLM involvement</B>,
              microseconds per evaluation. All twelve always run - no short-circuiting - and the
              gate runs twice: once at approval, again immediately before the order leaves. It
              fails closed, and it sizes trades down before it vetoes them.
            </P>
            <KV
              rows={BREAKERS.map(([name, rule]) => [
                <Chip key={name}>{name}</Chip>,
                <span key={`${name}-r`} className="font-sans text-[13.5px] text-muted">{rule}</span>,
              ])}
            />
            <P>
              Try it yourself: the dashboard&apos;s risk-gate panel submits a deliberately bad trade
              - a naked call - and shows which breakers trip, live, with the gate&apos;s own
              wording.
            </P>
          </DocSection>

          <DocSection id="exits">
            <H2>Order &amp; exit lifecycle</H2>
            <P>
              <B>Submitted is not filled.</B> Entries and exits both live as working orders until
              the broker confirms a fill; only then does the book change, at the price actually
              given. A stale order is cancelled - and dropped only when the broker confirms the
              cancel, because a cancel acknowledgement is a request, not an outcome, and an order
              can still fill while it is pending.
            </P>
            <P>
              Exits are priced from the position&apos;s <B>current mark</B>, never its entry price,
              with the concession always against the desk. Positions carry a profit target that
              tightens as expiry approaches, a stop at 50% of max loss, and a hard exit at 3 days
              to expiry. A mark that falls outside the structure&apos;s own payoff bounds is flagged
              suspect and cannot fire an exit - bad quote data defers one cycle rather than
              realising a phantom loss.
            </P>
          </DocSection>

          <Rule />

          <DocSection id="ledger">
            <H2>Decision ledger</H2>
            <P>
              Every event the desk produces - analyst views, proposals, audits, gate verdicts,
              orders, fills, exits, refusals - is appended to a ledger where{" "}
              <B>each entry carries the SHA-256 of the one before it</B>. Altering or deleting any
              historical record breaks the chain from that point forward, visibly and permanently.
            </P>
            <KV
              rows={[
                ["Verify in the browser", <G key="a" href="/ledger/">the ledger page re-derives the chain</G>],
                ["Verify over HTTP", <Chip key="b">GET /api/ledger/verify</Chip>],
                ["Cross-process safety", <span key="c" className="font-sans text-[13.5px] text-body">file-locked appends; the head is re-derived under the lock</span>],
              ]}
            />
          </DocSection>

          <DocSection id="refusals">
            <H2>Refusals</H2>
            <P>
              Most systems only show what they did. Deflow&apos;s most informative output is what it{" "}
              <B>declined to do</B>: every refusal is recorded with the stage that made it - the
              analyst saw no edge, the model abstained, the auditor objected fatally, or the gate
              vetoed - and its exact reason. The dashboard&apos;s refusals panel is the desk&apos;s
              actual behaviour, not an absence of it.
            </P>
          </DocSection>

          <Rule />

          <DocSection id="run">
            <H2>Self-hosting &amp; running</H2>
            <pre className="mb-4 overflow-x-auto rounded-lg border border-ink-line bg-ink-raised p-4 font-mono text-[12.5px] leading-relaxed text-body">
              {`git clone ${GITHUB_URL}.git && cd Deflow
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your Alpaca + Featherless keys
.venv/bin/python main.py`}
            </pre>
            <KV
              rows={[
                ["No credentials", <span key="a" className="font-sans text-[13.5px] text-body">runs against a seeded simulated market - everything works, nothing is live</span>],
                [<Chip key="b1">DEFLOW_DRY_RUN=true</Chip>, <span key="b" className="font-sans text-[13.5px] text-body">full pipeline, no orders submitted</span>],
                [<Chip key="c1">DEFLOW_PORT</Chip>, <span key="c" className="font-sans text-[13.5px] text-body">API + dashboard port (default 8000)</span>],
                [<Chip key="d1">DEFLOW_CYCLE_SECONDS</Chip>, <span key="d" className="font-sans text-[13.5px] text-body">cycle cadence (default 300)</span>],
                ["Deploy scripts", <span key="e" className="font-sans text-[13.5px] text-body">deploy/ - additive installs for a shared VPS, systemd unit, Caddy site</span>],
              ]}
            />
            <P>
              One command brings up the desk, the API and the dashboard: the frontend is a static
              export served by the same FastAPI process, so there is no Node runtime in production.
            </P>
          </DocSection>

          <DocSection id="api">
            <H2>HTTP API</H2>
            <P>
              Read-only observability plus two deliberate write endpoints. There is no endpoint that
              places an order directly - orders exist only as the output of a full pipeline that has
              cleared the gate.
            </P>
            <KV
              rows={ENDPOINTS.map(([ep, what]) => [
                <Chip key={ep}>{ep}</Chip>,
                <span key={`${ep}-w`} className="max-w-[46ch] font-sans text-[13.5px] leading-relaxed text-muted">{what}</span>,
              ])}
            />
          </DocSection>

          <Rule />

          <DocSection id="trust">
            <H2>Trust model &amp; FAQ</H2>
            <KV
              rows={[
                [
                  <B key="q1">Is this real money?</B>,
                  <span key="a1" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    No - a live Alpaca <em>paper</em> account with real market data and real order
                    routing. Simulated results are hypothetical and do not represent actual trading.
                  </span>,
                ],
                [
                  <B key="q2">Can the LLM bypass the risk gate?</B>,
                  <span key="a2" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    Structurally impossible: the gate is pure standard-library Python with no LLM in
                    the call path, it runs twice, and the model&apos;s only power is choosing among
                    structures the Structurer already built.
                  </span>,
                ],
                [
                  <B key="q3">Whose numbers are on the dashboard?</B>,
                  <span key="a3" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    The broker&apos;s. Equity and P&amp;L come from Alpaca&apos;s own marks and the
                    panel says so; the desk&apos;s internal quote-mid marks are shown alongside,
                    labelled, because the two genuinely differ and hiding either would be lying by
                    omission.
                  </span>,
                ],
                [
                  <B key="q4">What happens on a crash or redeploy?</B>,
                  <span key="a4" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    The book, working orders and working exits are persisted and restored; closing
                    orders carry deterministic client ids so a restart cannot double-submit; and the
                    hash chain makes any gap in the record visible.
                  </span>,
                ],
                [
                  <B key="q5">Why so few trades?</B>,
                  <span key="a5" className="max-w-[52ch] font-sans text-[13.5px] leading-relaxed text-muted">
                    By design. The desk trades only when it measures an edge and the gate agrees the
                    risk fits - a desk that must trade every cycle is a random number generator with
                    commissions.
                  </span>,
                ],
              ]}
            />
          </DocSection>

          <footer className="mt-14 border-t border-ink-line pt-5 font-mono text-[10.5px] text-faint">
            Paper trading only. Simulated results are hypothetical and do not represent actual
            trading. Built for the lablab.ai × Alpaca AI Trading Agents hackathon.
          </footer>
        </main>
      </div>
    </div>
  );
}
