"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LedgerEntry, getJSON } from "@/lib/api";

/**
 * The hero's proof panel: the desk's real decisions, cycling.
 *
 * Deliberately not a mockup. A marketing card showing a specific trade with
 * specific numbers asserts that the trade happened, and this project's whole
 * argument is that unverified claims are the enemy - so it reads the actual
 * ledger and, when there is nothing to show, says so rather than inventing a
 * plausible one.
 *
 * It rotates through the last several verdicts rather than pinning the newest.
 * That keeps the panel in motion between trading cycles, and it shows the
 * behaviour that matters: roughly half of these are refusals, and a card that
 * only ever displayed the most recent fill would hide the thing the system is
 * actually for.
 */

const ROTATE_MS = 4600;
const POLL_MS = 20000;
const MAX_SHOWN = 8;

interface Decision {
  key: string;
  symbol: string;
  strategy: string;
  contracts: number | null;
  dte: number | null;
  maxLoss: number | null;
  pop: number | null;
  netDelta: number | null;
  breakersPassed: number | null;
  breakersTotal: number | null;
  elapsedUs: number | null;
  approved: boolean;
  reason: string;
  routed: boolean;
  at: string;
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

function extract(entries: LedgerEntry[]): Decision[] {
  const out: Decision[] = [];
  for (let i = entries.length - 1; i >= 0 && out.length < MAX_SHOWN; i--) {
    const e = entries[i];
    if (e.event !== "risk_gate") continue;
    const p: Record<string, any> = e.payload ?? {};
    const load: Record<string, any> = p.payload ?? {};
    const routed = entries
      .slice(i + 1, i + 4)
      .some((n) => n.event === "execution" && n.payload?.submitted === true);

    out.push({
      key: `${e.seq}`,
      symbol: String(p.symbol ?? load.symbol ?? ""),
      strategy: String(load.strategy ?? "").replace(/_/g, " "),
      contracts: num(load.contracts),
      dte: num(load.dte),
      maxLoss: num(load.max_loss),
      pop: num(load.probability_of_profit),
      netDelta: num(load.net_delta),
      breakersPassed: num(p.breakers_passed),
      breakersTotal: num(p.breakers_total),
      elapsedUs: num(p.elapsed_us),
      approved: p.approved === true,
      reason: String(p.reason ?? ""),
      routed,
      at: String(e.at ?? ""),
    });
  }
  return out;
}

/** Count a number up when it changes. Static if the visitor asked for that. */
function useCountUp(target: number | null, ms = 700, still = false): number | null {
  const [value, setValue] = useState(target);
  const from = useRef(target ?? 0);
  useEffect(() => {
    if (target === null || still) {
      setValue(target);
      from.current = target ?? 0;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min((now - start) / ms, 1);
      // Ease-out: fast to nearly-there, then settle. Linear reads mechanical.
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(a + (target - a) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms, still]);
  return value;
}

export function DecisionCard() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "offline">("loading");
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [phase, setPhase] = useState(0);          // bumped on change, drives the sweep
  const [still, setStill] = useState(false);

  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setStill(q.matches);
    apply();
    q.addEventListener("change", apply);
    return () => q.removeEventListener("change", apply);
  }, []);

  const load = useCallback(async () => {
    try {
      const page = await getJSON<{ entries: LedgerEntry[] }>("/api/ledger?limit=160");
      const found = extract(page.entries ?? []);
      setDecisions(found);
      setState(found.length ? "ready" : "empty");
      setIndex((i) => (found.length ? i % found.length : 0));
    } catch {
      setState((s) => (s === "ready" ? "ready" : "offline"));
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  // Rotate. Paused on hover so a reader can finish the row they are on.
  useEffect(() => {
    if (paused || still || decisions.length < 2) return;
    const t = setInterval(() => {
      setIndex((i) => (i + 1) % decisions.length);
      setPhase((p) => p + 1);
    }, ROTATE_MS);
    return () => clearInterval(t);
  }, [paused, still, decisions.length]);

  const d = decisions[index] ?? null;
  const ready = state === "ready" && d !== null;
  const pass = d?.approved ?? false;

  const maxLoss = useCountUp(ready ? d!.maxLoss : null, 700, still);
  const pop = useCountUp(ready ? d!.pop : null, 700, still);
  const delta = useCountUp(ready ? d!.netDelta : null, 700, still);
  const micros = useCountUp(ready ? d!.elapsedUs : null, 600, still);

  const bars = useMemo(
    () => ({
      loss: ready && d!.maxLoss != null ? Math.min(d!.maxLoss / 2000, 1) : 0,
      pop: ready && d!.pop != null ? d!.pop : 0,
      delta: ready && d!.netDelta != null ? Math.min(Math.abs(d!.netDelta) / 0.35, 1) : 0,
    }),
    [ready, d],
  );

  return (
    <div
      className="group relative overflow-hidden rounded-2xl border border-ink-line bg-ink-raised/80 backdrop-blur-sm"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {/* A slow sweep across the card, so it reads as live even between
          trading cycles. Purely decorative and non-interactive. */}
      {!still && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-0 opacity-[0.55]"
          style={{
            background:
              "linear-gradient(105deg, transparent 40%, rgba(0,224,138,0.06) 50%, transparent 60%)",
            backgroundSize: "260% 100%",
            animation: "cardSweep 7s linear infinite",
          }}
        />
      )}

      {/* header */}
      <div className="relative z-10 flex items-center justify-between gap-3 border-b border-ink-line px-5 py-3.5">
        <div className="flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.16em] text-muted">
          <span className={ready ? "live-dot text-gain" : "text-faint"}>●</span>
          <span key={`h${d?.key}`} className={still ? "" : "animate-rise"}>
            {ready ? `gate · ${d!.symbol}` : "gate · standing by"}
          </span>
        </div>
        <span
          key={`b${d?.key}`}
          className={`rounded-full border px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.12em] ${
            still ? "" : "animate-rise"
          } ${
            !ready
              ? "border-ink-hair text-faint"
              : pass
                ? "border-gain/45 bg-gain/10 text-gain"
                : "border-loss/45 bg-loss/10 text-loss"
          }`}
        >
          {!ready ? "idle" : pass ? (d!.routed ? "routed" : "approved") : "vetoed"}
        </span>
      </div>

      <div className="relative z-10 space-y-4 p-5">
        {/* the structure */}
        <div className="min-h-[104px] rounded-xl border border-ink-line bg-ink/70 p-4 font-mono text-[12.5px]">
          {ready ? (
            <div key={`s${d!.key}`} className={still ? "" : "animate-rise"}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-gain">
                  {d!.strategy}
                  {d!.contracts !== null && (
                    <span className="text-body"> · {d!.contracts} contracts</span>
                  )}
                </span>
                {d!.dte !== null && <span className="text-faint">{d!.dte} DTE</span>}
              </div>
              <div className="mt-2.5 leading-relaxed text-muted">
                <span className="text-faint">verdict</span>{" "}
                <span className={pass ? "text-gain" : "text-loss"}>
                  {d!.breakersPassed ?? "-"}/{d!.breakersTotal ?? 12} breakers
                </span>
                {micros !== null && (
                  <span className="tabular text-faint"> in {micros.toFixed(2)} µs</span>
                )}
              </div>
              {!pass && d!.reason && (
                <div className="mt-1.5 line-clamp-2 text-[11.5px] leading-snug text-loss/90">
                  {d!.reason}
                </div>
              )}
            </div>
          ) : (
            <div className="text-[12px] leading-relaxed text-faint">
              {state === "offline"
                ? "desk unreachable - nothing to show"
                : state === "empty"
                  ? "no decision recorded yet · the desk trades on US market hours"
                  : "loading recent decisions…"}
            </div>
          )}
        </div>

        {/* metrics */}
        <dl className="space-y-2.5">
          <Metric
            label="max loss"
            value={maxLoss != null ? `$${Math.round(maxLoss).toLocaleString()}` : "-"}
            fill={bars.loss} tone="loss" cap="2% cap" phase={phase} still={still}
          />
          <Metric
            label="probability of profit"
            value={pop != null ? `${(pop * 100).toFixed(0)}%` : "-"}
            fill={bars.pop} tone="gain" cap="65% floor" phase={phase} still={still}
          />
          <Metric
            label="net delta"
            value={delta != null ? delta.toFixed(3) : "-"}
            fill={bars.delta} tone="info" cap="±0.35" phase={phase} still={still}
          />
        </dl>

        {/* the point */}
        <div className="flex items-center justify-between gap-3 rounded-xl border border-gain/25 bg-gain/[0.06] px-4 py-3">
          <span className="font-mono text-[11.5px] text-gain">
            no model output reached the broker
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-faint">
            zero LLM
          </span>
        </div>
      </div>

      {/* footer */}
      <div className="relative z-10 flex items-center justify-between gap-3 border-t border-ink-line px-5 py-3 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
        <span>deterministic · hash-chained</span>
        <div className="flex items-center gap-2.5">
          {decisions.length > 1 && (
            <span className="flex items-center gap-1">
              {decisions.map((x, i) => (
                <button
                  key={x.key}
                  onClick={() => { setIndex(i); setPhase((p) => p + 1); }}
                  aria-label={`Decision ${i + 1}`}
                  className={`h-1 rounded-full transition-all duration-500 ${
                    i === index ? "w-4 bg-gain" : "w-1 bg-ink-hair hover:bg-muted"
                  }`}
                />
              ))}
            </span>
          )}
          <span className="tabular">{d?.at ? d.at.slice(11, 19) : "paper"}</span>
        </div>
      </div>
    </div>
  );
}

function Metric({
  label, value, fill, tone, cap, phase, still,
}: {
  label: string; value: string; fill: number;
  tone: "gain" | "loss" | "info"; cap: string; phase: number; still: boolean;
}) {
  const bar = { gain: "bg-gain", loss: "bg-loss", info: "bg-info" }[tone];

  // Reset to zero on each change so the bar sweeps out rather than jumping
  // between two arbitrary widths, which reads as a glitch.
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (still) { setWidth(fill); return; }
    setWidth(0);
    const t = setTimeout(() => setWidth(fill), 60);
    return () => clearTimeout(t);
  }, [fill, phase, still]);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 font-mono text-[10.5px]">
        <dt className="uppercase tracking-[0.1em] text-faint">{label}</dt>
        <dd className="tabular font-semibold text-body">{value}</dd>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink">
          <div
            className={`h-full rounded-full ${bar}`}
            style={{
              width: `${Math.max(0, Math.min(width, 1)) * 100}%`,
              transition: still ? "none" : "width 900ms cubic-bezier(.22,.8,.3,1)",
            }}
          />
        </div>
        <span className="w-16 shrink-0 text-right font-mono text-[9.5px] text-faint">{cap}</span>
      </div>
    </div>
  );
}
