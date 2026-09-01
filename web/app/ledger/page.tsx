"use client";

import Link from "next/link";
import { LedgerViewer } from "@/components/LedgerViewer";
import { Mark } from "@/components/site/chrome";

export default function LedgerPage() {
  return (
    <main className="mx-auto max-w-[1400px] p-4 sm:p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href="/" className="group flex items-center gap-2.5" aria-label="Deflow home">
          <Mark size={26} />
          <span className="flex items-baseline gap-3">
            <span className="font-mono text-lg font-bold tracking-tight text-gain transition-opacity group-hover:opacity-80">
              DEFLOW
            </span>
            <span className="hidden font-mono text-[11px] text-muted sm:inline">decision ledger</span>
          </span>
        </Link>
        <nav className="flex items-center gap-2">
          <Link
            href="/dashboard/"
            className="rounded-md border border-ink-hair px-3 py-1.5 font-mono text-[11px] text-muted transition-colors hover:border-muted hover:text-body"
          >
            Live desk
          </Link>
          <Link
            href="/"
            className="rounded-md border border-ink-hair px-3 py-1.5 font-mono text-[11px] text-muted transition-colors hover:border-muted hover:text-body"
          >
            Overview
          </Link>
        </nav>
      </header>

      <p className="mb-6 max-w-prose font-sans text-[13.5px] leading-[1.7] text-muted">
        Every analyst view, proposal, audit, gate verdict, order and exit the desk has produced —
        including the ones that ended in a refusal to trade. Each entry carries the SHA-256 of the
        entry before it, so altering or deleting any historical record breaks the chain from that
        point forward. <span className="text-body">Verify it yourself below.</span>
      </p>

      <LedgerViewer />
    </main>
  );
}
