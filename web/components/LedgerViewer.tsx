"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Empty, Panel } from "./ui";
import { ChainStatus, LedgerEntry, getJSON, money, pct, signedPct } from "@/lib/api";

const GENESIS = "0".repeat(64);

const EVENTS = [
  "all", "analyst_view", "candidates_built", "reasoning_choice", "audit",
  "risk_gate", "execution", "exit", "market_closed", "cycle_start", "cycle_end",
] as const;

const LIMITS = [50, 200, 500] as const;

/** Rows per page. Small enough that an entry stays readable without
 *  scrolling past it, which matters when each row can be expanded. */
const PAGE_SIZE = 12;

// Same colour vocabulary as the live decision stream, so an event means the
// same thing whichever panel you meet it in.
const TONE: Record<string, string> = {
  cycle_start: "text-info",
  cycle_end: "text-info",
  analyst_view: "text-muted",
  candidates_built: "text-body",
  reasoning_choice: "text-warn",
  audit: "text-body",
  risk_gate: "text-body",
  execution: "text-gain",
  exit: "text-warn",
  market_closed: "text-faint",
};

// --- payload → one honest line ---------------------------------------------

/** A finite number, or null. A missing field must never be printed as zero. */
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

const words = (v: unknown) => String(v ?? "").replace(/_/g, " ");

/** Compact signed dollars — "+$91". Whole dollars keep a summary line scannable. */
const signed0 = (n: number) => `${n >= 0 ? "+" : "−"}${money(Math.abs(n), 0)}`;

const join = (...parts: (string | null | false)[]) => parts.filter(Boolean).join(" · ");

function describe(entry: LedgerEntry): string {
  const p: Record<string, any> =
    entry.payload && typeof entry.payload === "object" ? entry.payload : {};
  const sym = typeof p.symbol === "string" ? p.symbol : "";

  switch (entry.event) {
    case "cycle_start": {
      const universe = Array.isArray(p.universe) ? p.universe.join(" ") : "";
      return join(p.mode ? String(p.mode) : null, universe ? `scanning ${universe}` : "cycle opened");
    }

    case "cycle_end": {
      const equity = num(p.performance?.equity);
      return (
        join(
          num(p.orders_submitted) !== null ? `${p.orders_submitted} routed` : null,
          num(p.vetoed) !== null ? `${p.vetoed} vetoed` : null,
          equity !== null ? `equity ${money(equity, 0)}` : null,
        ) || "cycle closed"
      );
    }

    case "market_closed":
      return typeof p.detail === "string" && p.detail ? p.detail : "market closed — cycle skipped";

    case "analyst_view": {
      const vrp = num(p.variance_premium);
      const ivr = num(p.iv_rank);
      return join(
        [sym, p.stance ? String(p.stance) : ""].filter(Boolean).join(" ") || "view",
        vrp !== null ? `VRP ${signedPct(vrp * 100, 1)}` : null,
        ivr !== null ? `IV rank ${pct(ivr, 0)}` : null,
        p.tradeable === false ? "not tradeable" : null,
      );
    }

    case "candidates_built": {
      const count = num(p.count);
      const strategy = p.strategy ? words(p.strategy) : "";
      return count !== null
        ? `${sym} ${count} × ${strategy || "candidates"}`.trim()
        : `${sym} candidates built`.trim();
    }

    case "reasoning_choice": {
      const engine = p.used_llm ? String(p.model ?? "model") : "deterministic ranker";
      const index = num(p.index);
      const pick = index === -1 ? "abstained" : index !== null ? `chose #${index}` : "chose";
      const conf = num(p.confidence);
      return `${sym} ${engine} → ${pick}${conf !== null ? ` @ ${pct(conf, 0)} confidence` : ""}`.trim();
    }

    case "audit": {
      const ev = num(p.monte_carlo_physical?.mean_pnl);
      const objections = Array.isArray(p.objections) ? p.objections.length : null;
      const verdict = typeof p.passed === "boolean" ? (p.passed ? "pass" : "FAIL") : "audited";
      return join(
        `${sym} ${verdict}`.trim(),
        ev !== null ? `EV ${signed0(ev)}` : null,
        objections !== null ? `${objections} objection${objections === 1 ? "" : "s"}` : null,
      );
    }

    case "risk_gate": {
      const passed = num(p.breakers_passed);
      const total = num(p.breakers_total);
      const micros = num(p.elapsed_us);
      const head = [sym, passed !== null && total !== null ? `${passed}/${total}` : ""]
        .filter(Boolean)
        .join(" ");
      const timing = micros !== null ? ` in ${micros.toFixed(1)}µs` : "";
      // A veto is only meaningful with its reason attached — that string is the
      // whole point of the gate, so it is never abbreviated away.
      const verdict =
        p.approved === true
          ? "approved"
          : typeof p.reason === "string" && p.reason
            ? p.reason
            : "vetoed";
      return `${head}${timing} — ${verdict}`;
    }

    case "execution": {
      if (p.submitted === false) {
        return `${sym} order rejected${p.error ? ` — ${String(p.error)}` : ""}`.trim();
      }
      const contracts = num(p.contracts);
      return join(
        [
          sym,
          "routed",
          contracts !== null ? `${contracts}×` : null,
          p.strategy ? String(p.strategy) : null,
          p.route ? `via ${p.route}` : null,
        ]
          .filter(Boolean)
          .join(" "),
        p.simulated === true ? "simulated fill" : null,
      );
    }

    case "exit": {
      const realized = num(p.realized_pnl);
      const unrealized = num(p.unrealized_pnl);
      return join(
        `${sym} ${words(p.reason) || "closed"}`.trim(),
        realized !== null
          ? `realised ${signed0(realized)}`
          : unrealized !== null
            ? `unrealised ${signed0(unrealized)}`
            : null,
        p.submitted === false ? "close failed" : null,
      );
    }

    default: {
      // Unknown event: still a line a human can read, never a wall of JSON.
      const scalars = Object.entries(p)
        .filter(([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean")
        .slice(0, 4)
        .map(([k, v]) => `${k} ${v}`);
      return scalars.join(" · ") || "no scalar fields — expand to read the payload";
    }
  }
}

const shortHash = (h: string) => (h.length > 30 ? `${h.slice(0, 20)}…${h.slice(-8)}` : h);

const clockTime = (iso: string) => {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? "--:--:--" : new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
};

// --- component --------------------------------------------------------------

export function LedgerViewer() {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [checkedAt, setCheckedAt] = useState<string>("");
  // Whether what is on screen was confirmed by the most recent fetch.
  const [stale, setStale] = useState(false);
  const [seenAt, setSeenAt] = useState<string>("");
  const [checking, setChecking] = useState(false);
  const [limit, setLimit] = useState<number>(50);
  const [filter, setFilter] = useState<string>("all");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  // Flipping filters fast can land an older response after a newer one; only
  // the most recent request is allowed to write state.
  const request = useRef(0);

  const load = useCallback(async () => {
    const token = ++request.current;
    const query = `/api/ledger?limit=${limit}${filter === "all" ? "" : `&event=${filter}`}`;
    try {
      const [page, status] = await Promise.all([
        getJSON<{ entries: LedgerEntry[]; total: number }>(query),
        getJSON<ChainStatus>("/api/ledger/verify"),
      ]);
      if (token !== request.current) return;
      // The backend returns the tail oldest-first; the newest decision is the
      // one a reader is here for.
      setEntries([...page.entries].reverse());
      setTotal(page.total);
      setChain(status);
      setStale(false);
      setSeenAt(new Date().toLocaleTimeString("en-GB", { hour12: false }));
      setError("");
    } catch (e) {
      if (token !== request.current) return;
      // A failed verify must never leave a stale green banner standing -- and
      // it must not leave the entry count standing either. This panel exists
      // to assert that the record is verified; continuing to print
      // "N entries · chain intact" from a previous fetch, under a banner that
      // now says otherwise, is the precise dishonesty it is meant to rule out.
      // The rows stay visible because they were real, but they are explicitly
      // marked as last-seen rather than current.
      setChain(null);
      setStale(true);
      setError(e instanceof Error ? e.message : "backend unreachable");
    } finally {
      if (token === request.current) setLoaded(true);
    }
  }, [limit, filter]);

  const verify = useCallback(async () => {
    setChecking(true);
    const startedAt = Date.now();
    try {
      const status = await getJSON<ChainStatus>("/api/ledger/verify");
      setChain(status);
      setStale(false);
      setCheckedAt(new Date().toLocaleTimeString("en-GB", { hour12: false }));
      setError("");
    } catch (e) {
      setChain(null);
      setStale(true);
      setError(e instanceof Error ? e.message : "backend unreachable");
    } finally {
      // Re-hashing the file usually returns in single-digit milliseconds. With
      // no floor the button flickers and the check reads as if nothing ran.
      const elapsed = Date.now() - startedAt;
      if (elapsed < 420) await new Promise((r) => setTimeout(r, 420 - elapsed));
      setChecking(false);
    }
  }, []);

  // Changing the filter or window re-lists everything; staying on page 4 of a
  // list that now has two pages shows an empty table.
  useEffect(() => {
    setPage(0);
    setExpanded(null);
  }, [filter, limit]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    // Refetching under someone who is reading an expanded entry would swap the
    // evidence out from under them, so the poll stops while a row is open.
    // New entries land at the top, so a refresh shifts every later page by one.
    // Pausing while the reader is off page 1 -- or has a row open -- keeps the
    // thing they are looking at where they left it.
    if (expanded !== null || page > 0) return;
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [expanded, page, load]);

  // Clamp rather than trust: a refresh can shorten the list under a reader who
  // is on the last page.
  const pageCount = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const start = current * PAGE_SIZE;
  const visible = entries.slice(start, start + PAGE_SIZE);

  const offline = chain === null;
  const broken = chain !== null && !chain.valid;

  return (
    <Panel
      title="Hash-chained decision ledger"
      right={
        <Badge tone={offline ? "muted" : broken ? "loss" : "gain"}>
          {stale
            ? `${total !== null ? total.toLocaleString() + " entries" : "entries"} — unconfirmed`
            : total !== null
              ? `${total.toLocaleString()} entries`
              : "unavailable"}
        </Badge>
      }
    >
      {/* ---- Verification banner ------------------------------------------
          The single most important thing on this panel: a claim about the
          record, and a button a sceptic can press to re-check it themselves. */}
      <div
        className={`rounded border p-3 ${
          offline
            ? "border-warn/40 bg-warn/5"
            : broken
              ? "border-loss/50 bg-loss/10"
              : "border-gain/40 bg-gain/5"
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div
              className={`flex items-center gap-2 text-sm font-bold ${
                offline ? "text-warn" : broken ? "text-loss" : "text-gain"
              }`}
            >
              <ChainGlyph />
              {offline ? "Chain not verified" : broken ? "CHAIN BROKEN" : "Chain intact"}
            </div>

            <p className="mt-1.5 max-w-prose text-[11px] leading-relaxed text-muted">
              {offline
                ? `The verifier is unreachable — ${error || "no response"}. Nothing is asserted about the record until it answers.`
                : broken
                  ? chain!.detail
                  : `Every one of ${chain!.entries.toLocaleString()} entries re-hashes to its successor.`}
            </p>

            {broken && chain!.broken_at !== null && (
              <p className="mt-1 text-[11px] font-semibold text-loss">
                First break at entry {chain!.broken_at}. Everything before it still verifies.
              </p>
            )}

            {chain && chain.head && (
              <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[10px]">
                <span className="uppercase tracking-[0.12em] text-faint">
                  {broken ? "last good hash" : "head"}
                </span>
                <code className="tabular break-all font-mono text-body" title={chain.head}>
                  {shortHash(chain.head)}
                </code>
              </div>
            )}
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1">
            <button
              onClick={verify}
              disabled={checking}
              className={`rounded border px-3 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-wider transition disabled:opacity-60 ${
                offline
                  ? "border-warn/40 bg-warn/10 text-warn hover:bg-warn/20"
                  : broken
                    ? "border-loss/40 bg-loss/10 text-loss hover:bg-loss/20"
                    : "border-gain/40 bg-gain/10 text-gain hover:bg-gain/20"
              }`}
            >
              {checking ? "re-hashing…" : "Verify chain"}
            </button>
            <span className="tabular text-[10px] text-faint">
              {checkedAt ? `checked ${checkedAt}` : "recomputes every hash"}
            </span>
          </div>
        </div>
      </div>

      {/* ---- Filters and window ------------------------------------------ */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex flex-wrap gap-1">
          {EVENTS.map((name) => {
            const active = filter === name;
            return (
              <button
                key={name}
                onClick={() => { setExpanded(null); setFilter(name); }}
                className={`rounded-full border px-2.5 py-0.5 font-mono text-[10px] transition ${
                  active
                    ? "border-info/50 bg-info/10 text-info"
                    : "border-ink-line text-muted hover:border-ink-hair hover:text-body"
                }`}
              >
                {name}
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-1">
          <span className="text-[10px] uppercase tracking-[0.12em] text-faint">window</span>
          {LIMITS.map((n) => (
            <button
              key={n}
              onClick={() => { setExpanded(null); setLimit(n); }}
              className={`tabular rounded border px-2 py-0.5 font-mono text-[10px] transition ${
                limit === n
                  ? "border-ink-hair bg-ink-card text-body"
                  : "border-ink-line text-muted hover:text-body"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* ---- Entries ------------------------------------------------------ */}
      <div className="mt-2 border-t border-ink-line">
        {!loaded ? (
          <Empty>Reading the chain…</Empty>
        ) : entries.length === 0 ? (
          <Empty>
            {error
              ? <>Ledger unreachable — <span className="text-loss">{error}</span>. Showing nothing rather than something stale.</>
              : filter !== "all"
                ? <>No <span className="text-body">{filter}</span> entries in the last {limit}.</>
                : <>The ledger is empty. No cycle has been recorded yet.</>}
          </Empty>
        ) : (
          <>
            {/* Rows below were real when fetched, but nothing has confirmed
                them since. Say so above them rather than letting them read as
                current -- the whole point of this panel is that what it shows
                has been verified. */}
            {stale && (
              <div className="mb-2 rounded-md border border-warn/40 bg-warn/[0.07] px-3 py-2 font-mono text-[10.5px] text-warn">
                Not confirmed by the latest fetch{seenAt ? ` — last confirmed ${seenAt}` : ""}.
                These entries are as last seen, not as they stand now.
              </div>
            )}
          <ul>
            {visible.map((entry) => (
              <Row
                key={`${entry.seq}-${entry.hash}`}
                entry={entry}
                open={expanded === entry.seq}
                onToggle={() => setExpanded(expanded === entry.seq ? null : entry.seq)}
              />
            ))}
          </ul>

          {pageCount > 1 && (
            <nav
              className="mt-3 flex items-center justify-between gap-3 border-t border-ink-line pt-3"
              aria-label="Ledger pages"
            >
              <button
                onClick={() => { setPage(current - 1); setExpanded(null); }}
                disabled={current === 0}
                className="rounded-md border border-ink-hair px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted transition-colors hover:border-muted hover:text-body disabled:cursor-not-allowed disabled:opacity-30"
              >
                ← Newer
              </button>

              <div className="flex items-center gap-3 font-mono text-[10.5px] text-faint">
                <span className="tabular">
                  {start + 1}–{Math.min(start + PAGE_SIZE, entries.length)} of {entries.length}
                </span>
                <span className="hidden items-center gap-1 sm:flex">
                  {Array.from({ length: pageCount }, (_, i) => (
                    <button
                      key={i}
                      onClick={() => { setPage(i); setExpanded(null); }}
                      aria-label={`Page ${i + 1}`}
                      aria-current={i === current ? "page" : undefined}
                      className={`h-1.5 w-1.5 rounded-full transition-colors ${
                        i === current ? "bg-gain" : "bg-ink-hair hover:bg-muted"
                      }`}
                    />
                  ))}
                </span>
              </div>

              <button
                onClick={() => { setPage(current + 1); setExpanded(null); }}
                disabled={current >= pageCount - 1}
                className="rounded-md border border-ink-hair px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted transition-colors hover:border-muted hover:text-body disabled:cursor-not-allowed disabled:opacity-30"
              >
                Older →
              </button>
            </nav>
          )}
          </>
        )}
      </div>

      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-ink-line pt-2 text-[10px] text-faint">
        <span className="tabular">
          page {current + 1} of {pageCount} · {entries.length} fetched
          {total !== null && !stale ? ` · ${total.toLocaleString()} in the chain` : ""}
          {stale && seenAt ? ` · last confirmed ${seenAt}` : ""}
          {expanded !== null
            ? " · paused while an entry is open"
            : current > 0
              ? " · paused while paging"
              : " · refreshes every 20s"}
        </span>
        <span>Append-only JSONL · SHA-256 per record · /api/ledger/verify</span>
      </footer>
    </Panel>
  );
}

function Row({
  entry, open, onToggle,
}: { entry: LedgerEntry; open: boolean; onToggle: () => void }) {
  const tone = TONE[entry.event] ?? "text-muted";
  return (
    <li className="border-b border-ink-line/60 last:border-0">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 px-1 py-1.5 text-left transition-colors hover:bg-ink-card/70 ${
          open ? "bg-ink-card/70" : ""
        }`}
      >
        <span className="tabular w-9 shrink-0 text-right font-mono text-[10px] text-faint">{entry.seq}</span>
        <span className="tabular w-16 shrink-0 font-mono text-[10px] text-muted" title={entry.at}>
          {clockTime(entry.at)}
        </span>
        <span className={`w-32 shrink-0 font-mono text-[10px] font-semibold ${tone}`}>{entry.event}</span>
        {/* Full width on its own line when the row is too narrow for four
            columns, so a long veto reason never widens the page. */}
        <span className="w-full min-w-0 truncate pl-[3.6rem] text-[11px] text-body sm:w-auto sm:flex-1 sm:pl-0">
          {describe(entry)}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-faint">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="grid gap-3 border-t border-ink-line/60 bg-ink px-2 py-3 lg:grid-cols-[1fr_20rem]">
          <div className="min-w-0">
            <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-faint">payload</div>
            <pre className="max-h-72 overflow-auto rounded border border-ink-line bg-ink-raised p-2.5 font-mono text-[10px] leading-relaxed text-body">
              {JSON.stringify(entry.payload, null, 2)}
            </pre>
          </div>

          <div className="min-w-0">
            <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-faint">chain</div>
            <HashLine label="prev_hash" value={entry.prev_hash} genesis={entry.prev_hash === GENESIS} />
            <HashLine label="hash" value={entry.hash} />
            <p className="mt-2 text-[10px] leading-relaxed text-muted">
              Entry {entry.seq} hashes its own body together with the SHA-256 of{" "}
              {entry.prev_hash === GENESIS ? "the genesis value" : `entry ${entry.seq - 1}`}. Change a
              byte of the payload and this hash — and every hash after it — stops matching, which is
              exactly what <span className="text-body">Verify chain</span> recomputes.
            </p>
          </div>
        </div>
      )}
    </li>
  );
}

function HashLine({ label, value, genesis = false }: { label: string; value: string; genesis?: boolean }) {
  return (
    <div className="mt-1 border-b border-ink-line/50 pb-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] text-muted">{label}</span>
        {genesis && <span className="font-mono text-[9px] uppercase tracking-wider text-faint">genesis</span>}
      </div>
      <code className="tabular block break-all font-mono text-[10px] leading-relaxed text-body">{value}</code>
    </div>
  );
}

/** Two interlocking links: the panel's whole argument in 14 pixels. */
function ChainGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M6.4 9.6 9.6 6.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M9.2 4.6 10.6 3.2a2.7 2.7 0 0 1 3.8 3.8L13 8.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M6.8 11.4 5.4 12.8a2.7 2.7 0 0 1-3.8-3.8L3 7.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
