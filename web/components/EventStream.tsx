"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { Badge, Empty, Panel } from "./ui";

interface StreamEvent { event: string; payload: any; seq: number; at: string }

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

/** One-line human summary per event type. */
function describe(e: StreamEvent): string {
  const p = e.payload ?? {};
  switch (e.event) {
    case "cycle_start":
      return `scanning ${(p.universe ?? []).join(" ")}`;
    case "cycle_end":
      return `${p.orders_submitted} routed · ${p.vetoed} vetoed · equity $${Number(p.performance?.equity ?? 0).toLocaleString()}`;
    case "analyst_view":
      return `${p.symbol} ${p.stance} · VRP ${(p.variance_premium * 100).toFixed(1)}% · IVR ${(p.iv_rank * 100).toFixed(0)}%`;
    case "candidates_built":
      return `${p.symbol} ${p.count} × ${String(p.strategy ?? "").replace(/_/g, " ")}`;
    case "reasoning_choice":
      return `${p.symbol} ${p.used_llm ? p.model : "deterministic"} → ${p.index === -1 ? "abstain" : `#${p.index}`} @ ${(p.confidence * 100).toFixed(0)}%`;
    case "audit":
      return `${p.symbol} ${p.passed ? "pass" : "FAIL"} · EV $${Number(p.monte_carlo_physical?.mean_pnl ?? 0).toFixed(0)} · ${p.objections?.length ?? 0} objection(s)`;
    case "risk_gate":
      return `${p.symbol} ${p.breakers_passed}/${p.breakers_total} in ${p.elapsed_us}µs — ${p.approved ? "approved" : p.reason}`;
    case "execution":
      return `${p.symbol} ${p.submitted ? "routed" : "failed"} ${p.contracts}× via ${p.route}${p.simulated ? " (sim)" : ""}`;
    case "exit":
      return `${p.symbol} ${p.reason}`;
    default:
      return JSON.stringify(p).slice(0, 120);
  }
}

export function EventStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/api/stream`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => {
      try {
        const parsed = JSON.parse(message.data) as StreamEvent;
        // Cap the buffer; this panel is a tail, not an archive. The full
        // history lives in the hash-chained ledger.
        setEvents((prev) => [...prev, parsed].slice(-200));
      } catch {
        /* keep-alive frames are not JSON */
      }
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  return (
    <Panel
      title="Decision stream"
      right={
        <Badge tone={connected ? "gain" : "muted"}>
          <span className={connected ? "live-dot" : ""}>●</span> {connected ? "live" : "offline"}
        </Badge>
      }
    >
      <div ref={scroller} className="h-[22rem] overflow-y-auto pr-1">
        {events.length === 0 ? (
          <Empty>Waiting for the next cycle…</Empty>
        ) : (
          <ul className="space-y-0.5">
            {events.map((e, i) => (
              <li key={`${e.seq}-${i}`} className="flex gap-2 text-[10px] leading-relaxed">
                <span className="tabular w-14 shrink-0 text-muted">
                  {new Date(e.at).toLocaleTimeString("en-GB", { hour12: false })}
                </span>
                <span className={`w-32 shrink-0 font-semibold ${TONE[e.event] ?? "text-muted"}`}>{e.event}</span>
                <span className="text-body">{describe(e)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
