"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, money, pct } from "@/lib/api";
import { Badge, Panel } from "./ui";

interface StreamEvent { event: string; payload: any; seq: number; at: string }

/** The tail is a window, not an archive. The full history is the ledger. */
const CAP = 200;

/**
 * Four link states, because "not live" is three different facts: never opened,
 * opened then lost, or refused. Only `live` may present rows as current.
 */
type Link = "connecting" | "live" | "dropped" | "offline";

const LINK: Record<Link, { label: string; tone: "muted" | "gain" | "warn" | "loss"; dot: string }> = {
  connecting: { label: "connecting", tone: "muted", dot: "bg-faint" },
  live: { label: "live", tone: "gain", dot: "bg-gain" },
  dropped: { label: "reconnecting", tone: "warn", dot: "bg-warn" },
  offline: { label: "offline", tone: "loss", dot: "bg-loss" },
};

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
};

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A missing measurement prints as an em dash. A zero here would be a claim. */
const show = (v: unknown, format: (n: number) => string) => (isNum(v) ? format(v) : "—");
const int = (v: unknown) => show(v, (n) => String(n));
const sym = (v: unknown) => (typeof v === "string" && v ? v : "—");

function clock(at: string): string {
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? "—" : new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
}

/** One-line human summary per event type. */
function describe(e: StreamEvent): string {
  const p = e.payload ?? {};
  switch (e.event) {
    case "cycle_start": {
      const universe: string[] = Array.isArray(p.universe) ? p.universe : [];
      return universe.length ? `scanning ${universe.join(" ")}` : "cycle opened";
    }
    case "cycle_end":
      return `${int(p.orders_submitted)} routed · ${int(p.vetoed)} vetoed · equity ${show(p.performance?.equity, (n) => money(n, 0))}`;
    case "analyst_view":
      return `${sym(p.symbol)} ${p.stance ?? "—"} · VRP ${show(p.variance_premium, (n) => pct(n, 1))} · IVR ${show(p.iv_rank, (n) => pct(n, 0))}`;
    case "candidates_built":
      return `${sym(p.symbol)} ${int(p.count)} × ${String(p.strategy ?? "").replace(/_/g, " ")}`;
    case "reasoning_choice":
      return `${sym(p.symbol)} ${p.used_llm ? p.model : "deterministic"} → ${p.index === -1 ? "abstain" : `#${p.index}`} @ ${show(p.confidence, (n) => pct(n, 0))}`;
    case "audit":
      return `${sym(p.symbol)} ${p.passed ? "pass" : "FAIL"} · EV ${show(p.monte_carlo_physical?.mean_pnl, (n) => money(n, 0))} · ${Array.isArray(p.objections) ? p.objections.length : "—"} objection(s)`;
    case "risk_gate":
      return `${sym(p.symbol)} ${int(p.breakers_passed)}/${int(p.breakers_total)} in ${show(p.elapsed_us, (n) => n.toFixed(1))}µs — ${p.approved ? "approved" : p.reason ?? "refused"}`;
    case "execution":
      return `${sym(p.symbol)} ${p.submitted ? "routed" : "failed"} ${int(p.contracts)}× via ${p.route ?? "—"}${p.simulated ? " (sim)" : ""}`;
    case "exit":
      return `${sym(p.symbol)} ${p.reason ?? "closed"}`;
    default:
      return JSON.stringify(p).slice(0, 120);
  }
}

export function EventStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [link, setLink] = useState<Link>("connecting");
  // Auto-tail only while the reader is at the bottom; scrolling up to read an
  // older decision must not be yanked back by the next frame off the wire.
  const [pinned, setPinned] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);
  const opened = useRef(false);

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/api/stream`);
    source.onopen = () => {
      opened.current = true;
      setLink("live");
    };
    source.onerror = () => {
      // EventSource retries on its own, so a transport error after a good
      // connection is a gap, not an end. Only CLOSED (or never having opened)
      // is honestly "offline".
      const closed = source.readyState === EventSource.CLOSED;
      setLink(closed || !opened.current ? "offline" : "dropped");
    };
    source.onmessage = (message) => {
      try {
        const parsed = JSON.parse(message.data) as StreamEvent;
        setEvents((prev) => {
          // The server replays its last 30 events at the start of EVERY
          // connection, not once. EventSource reconnects on any blip -- laptop
          // sleep, a proxy timeout, a backend restart, StrictMode's double
          // mount in dev -- so appending blindly re-adds history and the
          // bottom row, which this panel presents as the present, ends up
          // carrying an older timestamp than the rows above it. seq is the
          // monotonic ledger id, so anything not newer than what is already
          // buffered is a replay.
          const newest = prev.length ? prev[prev.length - 1].seq : -1;
          if (typeof parsed.seq === "number" && parsed.seq <= newest) return prev;
          return [...prev, parsed].slice(-CAP);
        });
      } catch {
        /* keep-alive frames are not JSON */
      }
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    if (!pinned) return;
    const el = scroller.current;
    // Jump, don't animate: a smooth scroll emits intermediate scroll events
    // that the handler below would read as the reader deliberately scrolling away.
    if (el) el.scrollTop = el.scrollHeight;
  }, [events, pinned]);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setPinned((was) => (was === atBottom ? was : atBottom));
  }, []);

  const state = LINK[link];
  const last = events[events.length - 1];

  return (
    <Panel
      title="Decision stream"
      right={
        <div className="flex items-center gap-2.5">
          <span
            className="tabular hidden font-mono text-[10px] text-faint sm:inline"
            title={`Tail of the last ${CAP} events. The full history is the hash-chained ledger.`}
          >
            {events.length} buffered
          </span>
          <Badge tone={state.tone}>
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${state.dot} ${link === "live" ? "live-dot" : ""}`}
            />
            {state.label}
          </Badge>
        </div>
      }
    >
      <div className="relative overflow-hidden rounded-lg border border-ink-line bg-ink font-mono">
        <div className="flex gap-3 border-b border-ink-line px-3 py-1.5 text-[9.5px] uppercase tracking-[0.14em] text-faint">
          <span className="hidden w-10 shrink-0 text-right sm:block">seq</span>
          <span className="w-[54px] shrink-0">time</span>
          <span className="w-[7.5rem] shrink-0">event</span>
          <span className="min-w-0 flex-1">detail</span>
        </div>

        {/* Fixed height: the tail owns this space whether or not anything has
            arrived, so the dashboard grid never reflows as events land. */}
        <div
          ref={scroller}
          onScroll={onScroll}
          tabIndex={0}
          role="log"
          aria-label="Decision stream"
          className="h-[20rem] overflow-y-auto overscroll-contain focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
        >
          {events.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center text-[11.5px] leading-relaxed">
              {link === "live" ? (
                <span className="text-faint">connected — waiting for the next cycle</span>
              ) : link === "connecting" ? (
                <span className="text-faint">opening stream…</span>
              ) : (
                <span className="text-warn">
                  stream unreachable — start the desk with{" "}
                  <span className="text-body">python main.py</span>
                </span>
              )}
            </div>
          ) : (
            <ul className="divide-y divide-ink-line/45 text-[10.5px]">
              {events.map((e, i) => (
                <li
                  key={`${e.seq}-${i}`}
                  className="flex gap-3 px-3 py-[3px] leading-[1.45] transition-colors hover:bg-ink-raised/60"
                >
                  <span className="tabular hidden w-10 shrink-0 text-right text-faint sm:block">
                    {e.seq}
                  </span>
                  <span className="tabular w-[54px] shrink-0 text-muted">{clock(e.at)}</span>
                  <span className={`w-[7.5rem] shrink-0 truncate ${TONE[e.event] ?? "text-muted"}`}>
                    {e.event}
                  </span>
                  <span className="tabular min-w-0 flex-1 break-words text-body">{describe(e)}</span>
                </li>
              ))}

              {/* Without this the last row would keep reading as the present. */}
              {link !== "live" && last && (
                <li className="flex gap-2 border-t border-warn/25 bg-warn/[0.05] px-3 py-2 text-[10.5px] text-warn">
                  <span aria-hidden>⚠</span>
                  <span>
                    {link === "offline" ? "stream closed" : "stream interrupted"} — nothing above is
                    newer than {clock(last.at)}
                  </span>
                </li>
              )}
            </ul>
          )}
        </div>

        {!pinned && events.length > 0 && (
          <button
            type="button"
            onClick={() => setPinned(true)}
            className="absolute bottom-2 right-3 rounded-full border border-ink-hair bg-ink-raised/95 px-2.5 py-1 text-[10px] tracking-[0.08em] text-muted transition-colors hover:border-muted hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
          >
            ↓ latest
          </button>
        )}
      </div>
    </Panel>
  );
}
