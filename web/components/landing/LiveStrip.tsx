"use client";

import { useEffect, useState } from "react";
import { Status, getJSON } from "@/lib/api";

/** Live numbers straight from the running desk.
 *
 *  The reason these belong on a landing page is that none of them are
 *  copywriting: if the backend is up, that is the real ledger height, the real
 *  mode and the real book. If it is down the strip says so and falls back to
 *  the static facts, rather than showing zeros dressed up as results.
 */
export function LiveStrip() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    const load = () => getJSON<Status>("/api/status").then(setStatus).catch(() => setStatus(null));
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  const live = status !== null;
  const perf = status?.performance;

  const items: [string, string][] = [
    ["breakers", "12"],
    ["gate latency", "1.4 µs"],
    ["defined-risk", "100%"],
    ["max risk / trade", "2%"],
    ["ledger entries", live ? String(status!.ledger.entries) : "hash-chained"],
    ["open structures", live ? String(perf!.open_positions) : "—"],
  ];

  return (
    <div className="mt-12 overflow-hidden rounded-xl border border-ink-line bg-ink-raised/60">
      <div className="flex items-center gap-2 border-b border-ink-line px-5 py-2.5">
        <span className={`text-[8px] ${live ? "live-dot text-gain" : "text-muted"}`}>●</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted">
          {live
            ? `desk online · ${status!.mode === "paper" ? "Alpaca paper trading" : "simulation mode"} · ${status!.cycles_run} cycles run`
            : "desk offline · run python main.py to bring it up"}
        </span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {items.map(([label, value], i) => (
          <div
            key={label}
            className={`px-5 py-4 ${i % 2 ? "border-l border-ink-line" : ""} ${
              i >= 2 ? "border-t border-ink-line sm:border-t-0" : ""
            } sm:border-l sm:border-ink-line sm:first:border-l-0 ${i >= 3 ? "sm:border-t sm:border-ink-line lg:border-t-0" : ""}`}
          >
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{label}</dt>
            <dd className="tabular mt-1 font-mono text-lg font-bold text-body">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
