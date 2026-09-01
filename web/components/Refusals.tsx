"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Refusal,
  RefusalStage,
  Refusals as RefusalsPayload,
  getJSON,
  pct,
} from "@/lib/api";
import { Badge, Empty, Panel, Stat } from "./ui";

const STAGE_ORDER: RefusalStage[] = ["analyst", "reasoning", "auditor", "risk_gate"];

const STAGE_META: Record<RefusalStage, { label: string; bar: string; tone: "muted" | "warn" | "info" | "loss" }> = {
  analyst: { label: "analyst", bar: "bg-muted", tone: "muted" },
  reasoning: { label: "reasoning", bar: "bg-warn", tone: "warn" },
  auditor: { label: "auditor", bar: "bg-info", tone: "info" },
  risk_gate: { label: "risk gate", bar: "bg-loss", tone: "loss" },
};

/** A stage the backend adds later must still render, so unknown keys degrade. */
function meta(stage: string) {
  return STAGE_META[stage as RefusalStage] ?? { label: String(stage).replace(/_/g, " "), bar: "bg-ink-hair", tone: "muted" as const };
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

function clock(at: string): string {
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? "—" : new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
}

export function Refusals() {
  const [data, setData] = useState<RefusalsPayload | null>(null);
  const [offline, setOffline] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getJSON<RefusalsPayload>("/api/refusals?limit=40"));
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
    <Badge tone="muted">
      <span className="tabular">{raw.length}</span> of <span className="tabular">{total}</span> shown
    </Badge>
  ) : undefined;

  return (
    <Panel title="What it refused" right={right}>
      {data === null ? (
        offline ? (
          <div className="py-8 text-center text-xs">
            <div className="font-semibold text-loss">Backend unreachable</div>
            <p className="mt-1.5 text-muted">Refusals are read from the ledger. Nothing is shown until it answers.</p>
          </div>
        ) : (
          <Empty>Loading…</Empty>
        )
      ) : total === 0 && raw.length === 0 ? (
        <Empty>No refusals recorded yet.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <Stat label="Documented refusals" value={<span className="tabular">{total ?? "—"}</span>} />
            <p className="max-w-prose font-sans text-[12px] leading-[1.7] text-muted">
              A refusal is an outcome, not an absence. Every one below names the agent that said no and the
              reason it gave — the same record the ledger keeps.
            </p>
          </div>

          {staged > 0 && (
            <div className="mt-4">
              <div
                role="img"
                aria-label={segments
                  .filter((s) => s.count > 0)
                  .map((s) => `${STAGE_META[s.stage].label} ${s.count}`)
                  .join(", ")}
                className="flex h-2 w-full overflow-hidden rounded-full bg-ink"
              >
                {segments
                  .filter((s) => s.count > 0)
                  .map((s) => (
                    <div
                      key={s.stage}
                      // flex-grow divides the track exactly, so rounding never
                      // leaves a gap at the end of the bar.
                      style={{ flexGrow: s.count, flexBasis: 0, minWidth: 2 }}
                      className={STAGE_META[s.stage].bar}
                      title={`${STAGE_META[s.stage].label} · ${s.count} (${pct(s.count / staged, 0)})`}
                    />
                  ))}
              </div>

              <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1.5">
                {segments.map((s) => (
                  <li
                    key={s.stage}
                    className={`flex items-center gap-1.5 font-mono text-[10px] ${s.count === 0 ? "opacity-40" : ""}`}
                  >
                    <span className={`h-2 w-2 shrink-0 rounded-[2px] ${STAGE_META[s.stage].bar}`} />
                    <span className="text-muted">{STAGE_META[s.stage].label}</span>
                    <span className="tabular font-semibold text-body">{s.count}</span>
                    <span className="tabular text-faint">{pct(s.count / staged, 0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 max-h-[24rem] overflow-y-auto border-t border-ink-line pr-1">
            {groups.length === 0 ? (
              <Empty>No refusals recorded yet.</Empty>
            ) : (
              <ul>
                {groups.map((g) => {
                  const m = meta(g.head.stage);
                  const reason = g.head.reason?.trim() || "no reason recorded";
                  return (
                    <li key={g.head.seq} className="border-b border-ink-line/60 py-2.5 last:border-b-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-body">{g.head.symbol}</span>
                        <Badge tone={m.tone}>{m.label}</Badge>
                        {g.count > 1 && (
                          <span
                            className="tabular rounded border border-ink-hair px-1.5 py-0.5 font-mono text-[10px] text-faint"
                            title={`${g.count} consecutive cycles refused for the same reason`}
                          >
                            ×{g.count}
                          </span>
                        )}
                        <time className="tabular ml-auto font-mono text-[10px] text-muted">{clock(g.head.at)}</time>
                      </div>
                      <p className="mt-1 line-clamp-2 font-sans text-[11px] leading-[1.6] text-muted" title={reason}>
                        {reason}
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

// The dashboard imports this panel as `RefusalsPanel`, matching the naming of
// the other panels it composes; the type `Refusals` in lib/api.ts owns the
// plain name in module scope.
export { Refusals as RefusalsPanel };
