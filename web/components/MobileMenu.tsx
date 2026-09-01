"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { SECTIONS } from "./SectionRail";
import { Wordmark } from "./site/chrome";
import { Status } from "@/lib/api";

/* The phone header was trying to show everything the desktop header shows -
   a four-item status strip, the ledger button and the primary action - and
   stacked itself three rows deep doing it. On mobile the status readouts and
   secondary navigation live in a slide-in drawer behind a hamburger, with the
   equity pinned at the bottom the way a wallet card is; only the wordmark and
   the one primary action stay in the bar. */

function Row({ dot, label, value }: { dot: string; label: string; value?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className="font-mono text-[12px] text-body">{label}</span>
      {value && <span className="ml-auto font-mono text-[11px] text-faint">{value}</span>}
    </div>
  );
}

export function MobileMenu({
  status,
  live,
  equity,
  pnl,
  pnlTone,
}: {
  status: Status | null;
  live: boolean;
  /** Already-formatted strings; null renders a dash, never a number. */
  equity: string | null;
  pnl: string | null;
  pnlTone: "gain" | "loss" | null;
}) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    // The page must not scroll behind the drawer.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="md:hidden">
      <button
        onClick={() => setOpen(true)}
        aria-label="Open menu"
        aria-expanded={open}
        className="flex h-9 w-9 flex-col items-center justify-center gap-[5px] rounded-md border border-ink-hair focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
      >
        <span className="h-[1.5px] w-4 bg-body" />
        <span className="h-[1.5px] w-4 bg-body" />
        <span className="h-[1.5px] w-4 bg-body" />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-ink/70 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Desk menu"
            tabIndex={-1}
            className="flex h-full w-[290px] max-w-[85vw] flex-col border-r border-ink-line bg-ink p-5 focus:outline-none motion-safe:animate-[drawerIn_200ms_ease-out]"
          >
            <div className="mb-6 flex items-center justify-between">
              <Wordmark height={24} />
              <button
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="rounded-md border border-ink-hair px-2 py-1 font-mono text-[12px] text-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
              >
                ✕
              </button>
            </div>

            {/* Section links: same rows the rail shows, tap to jump. */}
            <nav aria-label="Dashboard sections" className="mb-5">
              <ul>
                {SECTIONS.map((s) => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      onClick={() => setOpen(false)}
                      className="flex items-baseline gap-2 rounded-md px-2 py-2 font-mono text-[13px] text-body transition-colors hover:bg-ink-raised"
                    >
                      {s.label}
                      {s.sub && <span className="text-[10px] text-faint">{s.sub}</span>}
                    </a>
                  </li>
                ))}
                <li>
                  <Link
                    href="/ledger/"
                    className="flex items-baseline gap-2 rounded-md px-2 py-2 font-mono text-[13px] text-body transition-colors hover:bg-ink-raised"
                  >
                    Ledger ↗
                    <span className="tabular text-[10px] text-faint">
                      {status ? status.ledger.entries.toLocaleString() : "-"}
                      {status?.ledger.valid === false ? " · chain broken" : ""}
                    </span>
                  </Link>
                </li>
              </ul>
            </nav>

            {/* Status readouts: what the desktop strip shows, as rows. */}
            <div className="border-t border-ink-line pt-4">
              <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.2em] text-faint">
                Status
              </div>
              <Row
                dot={status === null ? "bg-faint" : live ? "bg-gain" : "bg-warn"}
                label={status === null ? "-" : live ? "Alpaca paper" : "simulation"}
              />
              <Row
                dot={status?.reasoning.featherless_enabled ? "bg-info" : "bg-faint"}
                label={
                  status === null
                    ? "-"
                    : status.reasoning.featherless_enabled
                      ? "Featherless"
                      : "deterministic"
                }
              />
              <Row dot="bg-faint" label={`route: ${status?.execution.route ?? "-"}`} />
              {status?.market_open !== undefined && (
                <Row
                  dot={status.market_open ? "bg-gain" : "bg-warn"}
                  label={status.market_open ? "market open" : "market closed"}
                />
              )}
            </div>

            {/* Equity card, pinned at the foot like a wallet. Nulls stay
                dashes: the drawer obeys the same rule as every panel. */}
            <div className="mt-auto rounded-lg border border-ink-line bg-ink-card p-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                Equity
              </div>
              <div className={`tabular mt-1.5 font-mono text-[20px] font-bold ${equity ? "text-body" : "text-faint"}`}>
                {equity ?? "-"}
              </div>
              <div
                className={`tabular mt-0.5 font-mono text-[12px] ${
                  pnl ? (pnlTone === "loss" ? "text-loss" : "text-gain") : "text-faint"
                }`}
              >
                {pnl ?? "-"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
