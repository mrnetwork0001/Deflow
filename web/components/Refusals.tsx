"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Refusal,
  RefusalStage,
  Refusals as RefusalsPayload,
  getJSON,
  pct,
} from "@/lib/api";
import { Badge, Empty, Panel } from "./ui";

const STAGE_ORDER: RefusalStage[] = ["analyst", "reasoning", "auditor", "risk_gate"];

interface StageMeta { label: string; bar: string; edge: string; text: string }

// Colour is spent on the rare refusals. The analyst declines constantly and
// stays grey; a risk-gate veto is the one that should catch the eye.
const STAGE_META: Record<RefusalStage, StageMeta> = {
  analyst: { label: "analyst", bar: "bg-muted", edge: "border-l-muted", text: "text-muted" },
  reasoning: { label: "reasoning", bar: "bg-warn", edge: "border-l-warn", text: "text-warn" },
  auditor: { label: "auditor", bar: "bg-info", edge: "border-l-info", text: "text-info" },
  risk_gate: { label: "risk gate", bar: "bg-loss", edge: "border-l-loss", text: "text-loss" },
};

/** A stage the backend adds later must still render, so unknown keys degrade. */
function meta(stage: string): StageMeta {
  return (
    STAGE_META[stage as RefusalStage] ?? {
      label: String(stage).replace(/_/g, " "),
      bar: "bg-ink-hair",
      edge: "border-l-ink-hair",
      text: "text-muted",
    }
  );
}

interface Group { head: Refusal; count: number }

/**
 * The analyst declines most often and phrases it identically cycle after cycle.
 * Folding consecutive identical (symbol, stage, reason) runs into one row keeps
 * the rare refusals — an auditor objection, a risk-gate veto — visible instead
 * of buried under fifty copies of the same sentence.
 */
function collapse(refusals: Refusal[]): Group[] {
  const groups: Group[] = [];
  for (const r of refusals) {
    const previous = groups[groups.length - 1];
    if (
      previous &&
      previous.head.symbol === r.symbol &&
      previous.head.stage === r.stage &&
      previous.head.reason === r.reason
    ) {
      previous.count += 1;
      continue;
    }
    groups.push({ head: r, count: 1 });
  }
  return groups;
}

const hhmmss = (d: Date) => d.toLocaleTimeString("en-GB", { hour12: false });

function clock(at: string): string {
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? "—" : hhmmss(new Date(ms));
}

// Two clamped lines run to roughly this many characters at the reason column's
// width. Below it the clamp never bites, so an expander would be a control that
// visibly does nothing.
const CLAMPED_CHARS = 96;

export function Refusals() {
  const [data, setData] = useState<RefusalsPayload | null>(null);
  const [offline, setOffline] = useState(false);
  const [readAt, setReadAt] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    try {
      setData(await getJSON<RefusalsPayload>("/api/refusals?limit=40"));
      setReadAt(hhmmss(new Date()));
      setOffline(false);
    } catch {
      // Keep the last good payload and label it, rather than blanking the
      // panel or letting a stale read pass as current.
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  const toggle = (seq: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(seq)) next.add(seq);
      return next;
    });

  const raw = useMemo(
    () => [...(data?.refusals ?? [])].sort((a, b) => b.seq - a.seq),
    [data],
  );
  const groups = useMemo(() => collapse(raw), [raw]);

  const segments = useMemo(() => {
    const by = data?.by_stage ?? {};
    return STAGE_ORDER.map((stage) => ({ stage, count: Math.max(0, by[stage] ?? 0) }));
  }, [data]);

  const staged = segments.reduce((sum, s) => sum + s.count, 0);
  const total = Number.isFinite(data?.total) ? (data as RefusalsPayload).total : null;

  const right = offline ? (
    <Badge tone="warn">offline{data ? " · last known" : ""}</Badge>
  ) : total !== null && raw.length > 0 ? (
    <div className="flex items-center gap-3">
      {readAt && (
        <span className="tabular hidden font-mono text-[10px] text-faint sm:inline">read {readAt}</span>
      )}
      <Badge tone="muted">
        <span className="tabular">{raw.length}</span> of <span className="tabular">{total}</span> shown
      </Badge>
    </div>
  ) : undefined;

  return (
    <Panel title="What it refused" right={right}>
      {data === null ? (
        // Reserved so the panel does not grow by ~400px when the first read lands.
        <div className="grid min-h-[22rem] place-items-center px-4 text-center">
          {offline ? (
            <div>
              <div className="font-mono text-[11px] font-bold uppercase tracking-[0.14em] text-loss">
                Backend unreachable
              </div>
              <p className="mx-auto mt-2.5 max-w-sm font-sans text-[12.5px] leading-[1.7] text-muted">
                Refusals are read from the ledger. Nothing is shown until it answers.
              </p>
            </div>
          ) : (
            <div className="flex items-center gap-2 font-mono text-[11px] text-faint">
              <span className="live-dot text-info">●</span>
              reading the refusal ledger…
            </div>
          )}
        </div>
      ) : total === 0 && raw.length === 0 ? (
        <div className="grid min-h-[22rem] place-items-center">
          <Empty>No refusals recorded yet.</Empty>
        </div>
      ) : (
        <div className="space-y-3.5">
          <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
            <div className="shrink-0">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                Documented refusals
              </div>
              <div className="tabular mt-1.5 font-mono text-[28px] font-bold leading-none text-body">
                {total ?? "—"}
              </div>
            </div>
            <p className="max-w-prose flex-1 basis-72 font-sans text-[12.5px] leading-[1.7] text-muted">
              A refusal is an outcome, not an absence. Every one below names the agent that said no and the
              reason it gave — the same record the ledger keeps.
            </p>
          </div>

          <div className="overflow-hidden rounded-lg border border-ink-line bg-ink">
            <div className="px-3.5 pb-3.5 pt-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                  refusals by stage
                </span>
                <span className="tabular font-mono text-[10px] text-faint">n = {staged}</span>
              </div>

              {staged > 0 ? (
                <div
                  role="img"
                  aria-label={segments
                    .filter((s) => s.count > 0)
                    .map((s) => `${STAGE_META[s.stage].label} ${s.count}`)
                    .join(", ")}
                  className="mt-2.5 flex h-2.5 w-full gap-px overflow-hidden rounded-[3px] bg-ink-raised"
                >
                  {segments
                    .filter((s) => s.count > 0)
                    .map((s) => (
                      <div
                        key={s.stage}
                        // flex-grow divides the track exactly, so rounding never
                        // leaves a gap at the end of the bar.
                        style={{ flexGrow: s.count, flexBasis: 0, minWidth: 2 }}
                        className={`transition-all duration-700 ${STAGE_META[s.stage].bar}`}
                        title={`${STAGE_META[s.stage].label} · ${s.count} (${pct(s.count / staged, 0)})`}
                      />
                    ))}
                </div>
              ) : (
                <div className="mt-2.5 flex h-2.5 items-center font-mono text-[10px] text-faint">
                  stage breakdown not reported
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-px border-t border-ink-line bg-ink-line sm:grid-cols-4">
              {segments.map((s) => {
                const m = STAGE_META[s.stage];
                const none = s.count === 0;
                return (
                  <div key={s.stage} className="bg-ink px-3.5 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-[1px] ${m.bar} ${none ? "opacity-40" : ""}`} />
                      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                        {m.label}
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-baseline gap-2">
                      <span
                        className={`tabular font-mono text-[17px] font-semibold leading-none ${
                          none ? "text-faint" : "text-body"
                        }`}
                      >
                        {s.count}
                      </span>
                      {/* A share of nothing is not 0% — it is undefined. */}
                      <span className="tabular font-mono text-[10.5px] text-faint">
                        {staged > 0 ? pct(s.count / staged, 0) : "—"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {offline && (
            <div className="rounded-md border border-warn/25 bg-warn/[0.06] px-3 py-2 font-mono text-[10.5px] leading-relaxed text-warn">
              backend unreachable — nothing below has changed since the last successful read
              {readAt && <span className="tabular"> at {readAt}</span>}
            </div>
          )}

          <div className="overflow-hidden rounded-lg border border-ink-line bg-ink">
            <div className="hidden items-center gap-x-3 border-b border-ink-line px-3 py-2 font-mono text-[9.5px] uppercase tracking-[0.14em] text-faint sm:flex">
              <span className="w-14">symbol</span>
              <span className="w-[4.5rem]">stage</span>
              <span className="flex-1">reason given</span>
              <span className="w-10 text-right">repeat</span>
              <span className="w-14 text-right">time</span>
              <span className="w-5" aria-hidden />
            </div>

            {groups.length === 0 ? (
              <div className="grid min-h-[15rem] place-items-center">
                <Empty>No refusals recorded yet.</Empty>
              </div>
            ) : (
              <div
                role="region"
                aria-label="Refusal log"
                tabIndex={0}
                className="max-h-[24rem] min-h-[15rem] overflow-y-auto focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-gain/60"
              >
                <ul className="divide-y divide-ink-line">
                  {groups.map((g) => {
                    const m = meta(g.head.stage);
                    const reason = g.head.reason?.trim() || "no reason recorded";
                    const long = reason.length > CLAMPED_CHARS;
                    const open = expanded.has(g.head.seq);
                    return (
                      <li
                        key={g.head.seq}
                        className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 border-l-2 px-3 py-2.5 transition-colors hover:bg-ink-raised/70 ${m.edge}`}
                      >
                        <span className="w-14 shrink-0 font-mono text-[12.5px] font-bold text-body">
                          {g.head.symbol}
                        </span>
                        <span
                          className={`w-[4.5rem] shrink-0 font-mono text-[10px] uppercase tracking-[0.1em] ${m.text}`}
                        >
                          {m.label}
                        </span>

                        <p
                          className={`order-last w-full min-w-0 break-words font-sans text-[11.5px] leading-[1.6] text-muted sm:order-none sm:w-auto sm:flex-1 ${
                            long && !open ? "line-clamp-2" : ""
                          }`}
                          title={long ? reason : undefined}
                        >
                          {reason}
                        </p>

                        <span className="w-10 shrink-0 text-right">
                          {g.count > 1 && (
                            <span
                              className="tabular font-mono text-[10px] text-faint"
                              title={`${g.count} consecutive cycles refused for the same reason`}
                            >
                              ×{g.count}
                            </span>
                          )}
                        </span>
                        <time
                          dateTime={g.head.at}
                          className="tabular w-14 shrink-0 text-right font-mono text-[10px] text-faint"
                        >
                          {clock(g.head.at)}
                        </time>

                        {long ? (
                          <button
                            type="button"
                            onClick={() => toggle(g.head.seq)}
                            aria-expanded={open}
                            aria-label={`${open ? "Collapse" : "Show"} the full reason for ${g.head.symbol}`}
                            className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-ink-line text-[9px] text-faint transition-colors hover:border-ink-hair hover:bg-ink-raised hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
                          >
                            <span className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}>
                              ▾
                            </span>
                          </button>
                        ) : (
                          <span className="h-5 w-5 shrink-0" aria-hidden />
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

// The dashboard imports this panel as `RefusalsPanel`, matching the naming of
// the other panels it composes; the type `Refusals` in lib/api.ts owns the
// plain name in module scope.
export { Refusals as RefusalsPanel };
