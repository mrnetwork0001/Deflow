"use client";

import Link from "next/link";
import { LedgerViewer } from "@/components/LedgerViewer";
import { Wordmark } from "@/components/site/chrome";

export default function LedgerPage() {
  return (
    <main className="mx-auto max-w-[1400px] p-4 sm:p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href="/" className="group flex items-center gap-4" aria-label="Deflow home">
          <Wordmark height={30} className="transition-opacity group-hover:opacity-80" />
          <span className="hidden border-l border-ink-line pl-4 font-mono text-[11px] text-muted sm:inline">
            decision ledger
          </span>
        </Link>
        <nav className="flex items-center gap-2.5">
          <Link
            href="/"
            className="rounded-md px-3 py-2 font-mono text-[11px] text-muted transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
          >
            Overview
          </Link>
          <Link
            href="/dashboard/"
            className="inline-flex items-center gap-2 rounded-md bg-gain px-4 py-2 font-mono text-[11px] font-bold uppercase tracking-[0.08em] text-ink transition-colors hover:bg-gain-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gain/50"
          >
            Live desk →
          </Link>
        </nav>
      </header>

      <p className="mb-6 max-w-prose font-sans text-[13.5px] leading-[1.7] text-muted">
        Every analyst view, proposal, audit, gate verdict, order and exit the desk has produced -
        including the ones that ended in a refusal to trade. Each entry carries the SHA-256 of the
        entry before it, so altering or deleting any historical record breaks the chain from that
        point forward. <span className="text-body">Verify it yourself below.</span>
      </p>

      <LedgerViewer />
    </main>
  );
}
