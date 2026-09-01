"use client";

import Link from "next/link";
import React from "react";

export const GITHUB_URL = "https://github.com/mrnetwork0001/Deflow";

export function Nav() {
  return (
    <nav className="sticky top-0 z-50 border-b border-ink-line/70 bg-ink/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-content items-center justify-between px-5 py-3">
        <Link href="/" className="group flex items-center gap-2.5">
          <Mark />
          <span className="font-mono text-sm font-bold tracking-tight text-body transition group-hover:text-gain">
            DEFLOW
          </span>
        </Link>

        <div className="hidden items-center gap-7 md:flex">
          {[
            ["The edge", "#edge"],
            ["Pipeline", "#pipeline"],
            ["Risk gate", "#gate"],
            ["Alpaca", "#alpaca"],
          ].map(([label, href]) => (
            <a key={href} href={href} className="text-[12px] text-muted transition hover:text-body">
              {label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden rounded-md border border-ink-line px-3 py-1.5 font-mono text-[11px] text-muted transition hover:border-muted hover:text-body sm:block"
          >
            GitHub
          </a>
          <Link
            href="/dashboard/"
            className="rounded-md bg-gain px-3.5 py-1.5 font-mono text-[11px] font-bold text-ink transition hover:bg-gain/85"
          >
            Launch app →
          </Link>
        </div>
      </div>
    </nav>
  );
}

/** Wordmark: a capped payoff diagram — flat, ramp, flat. The thesis in 20px. */
export function Mark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="0.5" y="0.5" width="23" height="23" rx="5" stroke="#1b2230" />
      <path d="M4 16.5h4.5L15 8h5" stroke="#00e08a" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 16.5h4.5" stroke="#ff5c5c" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}

export function Section({
  id, eyebrow, title, lead, children, className = "",
}: {
  id?: string; eyebrow?: string; title?: string; lead?: string;
  children: React.ReactNode; className?: string;
}) {
  return (
    <section id={id} className={`scroll-mt-16 border-t border-ink-line/60 px-5 py-20 ${className}`}>
      <div className="mx-auto max-w-content">
        {eyebrow && (
          <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.2em] text-gain">{eyebrow}</div>
        )}
        {title && (
          <h2 className="max-w-3xl font-sans text-[28px] font-semibold leading-[1.2] tracking-tight text-body sm:text-[34px]">
            {title}
          </h2>
        )}
        {lead && <p className="mt-4 max-w-2xl font-sans text-[15px] leading-relaxed text-muted">{lead}</p>}
        <div className={title || lead ? "mt-10" : ""}>{children}</div>
      </div>
    </section>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-ink-line bg-ink-raised p-6 ${className}`}>{children}</div>;
}
