"use client";

import { useState } from "react";
import { Position, WorkingOrder, money, pct, signedMoney } from "@/lib/api";

const CLOSED_PREVIEW = 6;

/**
 * The book, in three states of certainty: working orders that are out but not
 * filled, structures actually held, and what has already been closed.
 *
 * There is no loading or offline branch here on purpose — this component owns
 * no fetch. The dashboard holds the poll and renders the unreachable screen, so
 * an empty `open` here can only be read as "nothing shown", never as a claim
 * about the desk's current book.
 */
export function PositionsTable({
  open, closed, working = [], loaded = true, stale = false,
}: {
  open: Position[];
  closed: Position[];
  working?: WorkingOrder[];
  /** Has the book actually been fetched? An empty array before the first
   *  response is not an empty book, and printing "No open positions" for it
   *  is a claim this component has no basis to make. */
  loaded?: boolean;
  /** Was the last refresh a failure? The rows below are then last-known, not
   *  current, and must not be presented as the live book. */
  stale?: boolean;
}) {
  const [showAllClosed, setShowAllClosed] = useState(false);

  // The backend appends closes chronologically; the useful end is the recent one.
  const closedNewestFirst = [...closed].reverse();
  const closedShown = showAllClosed ? closedNewestFirst : closedNewestFirst.slice(0, CLOSED_PREVIEW);

  return (
    // min-w-0 so the wide table below scrolls inside its own container instead
    // of forcing the dashboard grid column wider than the viewport.
    // No .lift: this is a readout, not a target — lifting it would move the row
    // under the cursor while it is being read.
    <section className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-ink-line bg-ink-card">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-ink-line px-4 py-2.5">
        <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          Open structures
        </h2>
        <div className="flex items-center gap-4">
          {/* null, not 0, before the first response: "0 live · 0 working ·
              0 closed" is a claim about the book made before the book has been
              seen. Same gate the empty state below already uses. */}
          <Count n={loaded ? open.length : null} label="live" tone="text-gain" />
          <Count n={loaded ? working.length : null} label="working" tone="text-warn" />
          <Count n={loaded ? closed.length : null} label="closed" tone="text-body" />
        </div>
      </header>

      {/* ---- Working orders: routed, no fill, therefore not a position ---- */}
      {working.length > 0 && (
        <div className="border-b border-ink-line bg-warn/[0.04]">
          <div className="flex items-center gap-2 border-b border-warn/20 px-4 py-2">
            <span className="live-dot h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-warn">
              Working orders — submitted, not yet filled
            </span>
          </div>
          <ul className="divide-y divide-warn/10">
            {working.map((w) => (
              <li
                key={w.proposal_id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 font-mono text-[10.5px]"
              >
                <span className="w-12 shrink-0 font-bold text-body">{w.symbol}</span>
                <span className="text-muted">
                  {w.strategy.replace(/_/g, " ")} ×<span className="tabular">{w.contracts}</span>
                </span>
                <span className="tabular whitespace-nowrap text-faint">
                  @ {w.limit_price.toFixed(2)} net
                </span>
                {w.simulated && <SimTag />}
                <span className="tabular ml-auto whitespace-nowrap text-faint">
                  {w.status} · {Math.round(w.age_seconds)}s
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ---- Held structures ---------------------------------------------
          Height is reserved so the panel does not jump between the empty
          state and the first row landing. */}
      <div className="min-h-[176px]">
        {open.length === 0 ? (
          <div className="flex min-h-[176px] flex-col items-center justify-center gap-2 px-6 py-10 text-center">
            {/* Three different things, and only one of them is "the desk holds
                nothing". Before the first response this component has seen no
                book at all, and after a failed refresh it has seen only an old
                one -- printing "No open positions" for either states something
                it cannot know. */}
            <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-faint">
              {!loaded ? "Loading the book" : stale ? "Book unconfirmed" : "No open positions"}
            </span>
            <p className="max-w-[28ch] font-sans text-[12.5px] leading-snug text-muted">
              {!loaded
                ? "Waiting for the desk to answer."
                : stale
                  ? "The last refresh failed, so nothing here is confirmed current."
                  : "The desk trades only when it measures an edge."}
            </p>
          </div>
        ) : (
          <>
          {stale && (
            <div className="mb-3 rounded-md border border-warn/40 bg-warn/[0.07] px-3 py-2 font-mono text-[10.5px] text-warn">
              Last refresh failed — these rows are as last seen, not as they stand now.
            </div>
          )}
          <div
            tabIndex={0}
            role="region"
            aria-label="Open structures table, scrolls horizontally"
            className="overflow-x-auto focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
          >
            {/* border-separate keeps the sticky symbol column's own borders and
                background painted while the rest of the table scrolls under it. */}
            <table className="w-full min-w-[860px] border-separate border-spacing-0 font-mono text-[11px]">
              <thead>
                <tr className="text-left font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint">
                  <th className="sticky left-0 z-10 border-b border-ink-line bg-ink-card py-2 pl-4 pr-3 font-normal">Symbol</th>
                  <th className="border-b border-ink-line py-2 pr-3 font-normal">Structure</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Qty</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Strikes</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">DTE</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Max loss</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Max profit</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">P(profit)</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Δ</th>
                  <th className="border-b border-ink-line py-2 pr-3 text-right font-normal">Θ/day</th>
                  <th className="border-b border-ink-line py-2 pr-4 text-right font-normal">Unrealised</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr
                    key={p.proposal_id}
                    className="group transition-colors hover:bg-ink-raised/50 [&:last-child>td]:border-b-0"
                  >
                    <td className="sticky left-0 z-10 whitespace-nowrap border-b border-ink-line/60 bg-ink-card py-2 pl-4 pr-3 text-[11.5px] font-bold text-body transition-colors group-hover:bg-ink-raised">
                      {p.symbol}
                      {p.simulated && <SimTag />}
                      {p.mark_suspect && (
                        <span
                          title="Last mark fell outside the structure's payoff bounds"
                          className="ml-1.5 cursor-help font-normal text-loss"
                        >
                          ?
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap border-b border-ink-line/60 py-2 pr-3 text-muted">
                      {p.strategy.replace(/_/g, " ")}
                    </td>
                    <td className="tabular border-b border-ink-line/60 py-2 pr-3 text-right text-body">
                      {p.contracts}
                    </td>
                    <td className="tabular whitespace-nowrap border-b border-ink-line/60 py-2 pr-3 text-right text-muted">
                      {p.legs.map((l) => l.strike).join(" / ")}
                    </td>
                    {/* Entry is gated to a 7–60 day window, so a structure inside
                        seven days is past the window it was opened in. */}
                    <td className={`tabular border-b border-ink-line/60 py-2 pr-3 text-right ${p.dte <= 7 ? "text-warn" : "text-muted"}`}>
                      {p.dte}
                    </td>
                    <td className="tabular whitespace-nowrap border-b border-ink-line/60 py-2 pr-3 text-right text-loss/75">
                      {money(p.max_loss, 0)}
                    </td>
                    <td className="tabular whitespace-nowrap border-b border-ink-line/60 py-2 pr-3 text-right text-gain/75">
                      {money(p.max_profit, 0)}
                    </td>
                    <td className="tabular border-b border-ink-line/60 py-2 pr-3 text-right text-body">
                      {pct(p.probability_of_profit, 0)}
                    </td>
                    <td className="tabular border-b border-ink-line/60 py-2 pr-3 text-right text-muted">
                      {p.net_delta >= 0 ? "+" : ""}{p.net_delta.toFixed(3)}
                    </td>
                    <td className="tabular border-b border-ink-line/60 py-2 pr-3 text-right text-muted">
                      {p.greeks.theta >= 0 ? "+" : ""}{p.greeks.theta.toFixed(1)}
                    </td>
                    <td className={`tabular whitespace-nowrap border-b border-ink-line/60 py-2 pr-4 text-right font-semibold ${p.unrealized_pnl >= 0 ? "text-gain" : "text-loss"}`}>
                      {signedMoney(p.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      {/* ---- Closed ------------------------------------------------------ */}
      {closed.length > 0 && (
        <div className="border-t border-ink-line">
          <div className="flex items-center gap-3 px-4 py-2">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Closed</h3>
            <span className="tabular ml-auto font-mono text-[9.5px] text-faint">
              {closedShown.length} of {closed.length}
            </span>
            {closed.length > CLOSED_PREVIEW && (
              <button
                type="button"
                onClick={() => setShowAllClosed((v) => !v)}
                className="rounded border border-ink-line px-2 py-1 font-mono text-[9.5px] uppercase tracking-[0.12em] text-muted transition-colors hover:border-ink-hair hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
              >
                {showAllClosed ? "show fewer" : `show all ${closed.length}`}
              </button>
            )}
          </div>
          <ul className={`divide-y divide-ink-line/60 ${showAllClosed ? "max-h-56 overflow-y-auto" : ""}`}>
            {closedShown.map((c) => {
              // A trade closed without a realised figure is unknown, not flat —
              // rendering it as $0.00 would invent a result.
              const realized = c.realized_pnl;
              return (
                <li
                  key={c.proposal_id + c.entry_at}
                  className="flex items-baseline gap-3 px-4 py-1.5 font-mono text-[10.5px]"
                >
                  <span
                    className={`tabular w-[74px] shrink-0 text-right font-semibold ${
                      realized == null ? "text-faint" : realized >= 0 ? "text-gain" : "text-loss"
                    }`}
                  >
                    {realized == null ? "—" : signedMoney(realized)}
                  </span>
                  <span className="w-12 shrink-0 font-bold text-body">{c.symbol}</span>
                  <span className="truncate text-muted">{c.close_reason ?? "—"}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Header readout: a zero is dimmed rather than coloured, so live counts carry
 *  the accent. A null has not been counted yet and renders as an em dash. */
function Count({ n, label, tone }: { n: number | null; label: string; tone: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={`tabular font-mono text-[13px] font-bold ${n ? tone : "text-faint"}`}>{n ?? "—"}</span>
      <span className="font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint">{label}</span>
    </span>
  );
}

/** Marks anything that exists only in the simulator, so it cannot read as live. */
function SimTag() {
  return (
    <span className="ml-1.5 rounded-[3px] border border-warn/35 px-1 align-[1px] font-mono text-[8.5px] font-normal uppercase tracking-[0.1em] text-warn">
      sim
    </span>
  );
}
