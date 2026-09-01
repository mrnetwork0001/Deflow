"use client";

import Link from "next/link";
import { ButtonLink, GITHUB_URL, Mark, Wordmark } from "./chrome";

export function CTA() {
  return (
    <section className="relative overflow-hidden border-t border-ink-line px-6 py-28">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="grid-bg absolute inset-0 opacity-30" />
        <div className="absolute left-1/2 top-0 h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-gain/[0.07] blur-[110px]" />
      </div>
      <div className="relative mx-auto max-w-content text-center">
        <div className="flex justify-center"><Mark size={44} /></div>
        <h2 className="mt-8 font-sans text-[34px] font-bold leading-[1.1] tracking-tightest text-body sm:text-[46px]">
          Watch it refuse a trade.
        </h2>
        <p className="mx-auto mt-5 max-w-xl font-sans text-[16px] leading-[1.7] text-muted">
          The desk streams every decision live — the regime read on eight names, the open book with
          Greeks, and a button that fires a naked call at the running risk gate.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <ButtonLink href="/dashboard/">Launch the desk</ButtonLink>
          <ButtonLink href={GITHUB_URL} variant="ghost" external>Read the source</ButtonLink>
        </div>
        <p className="mt-8 font-mono text-[11.5px] text-faint">
          One command from a bare clone —{" "}
          <span className="text-muted">python main.py</span>
        </p>
      </div>
    </section>
  );
}

const COLUMNS: [string, [string, string, boolean?][]][] = [
  ["Product", [
    ["Live desk", "/dashboard/"],
    ["Decision ledger", "/ledger/"],
    ["API reference", "/docs", true],
    ["Risk envelope", "/api/risk/envelope", true],
  ]],
  ["Project", [
    ["GitHub", GITHUB_URL, true],
    ["MIT licence", `${GITHUB_URL}/blob/main/LICENSE`, true],
    ["Technical write-up", `${GITHUB_URL}/blob/main/ONE_PAGE_WRITEUP.md`, true],
    ["Specification", `${GITHUB_URL}/blob/main/DEFLOW_PROJECT_SPEC.md`, true],
  ]],
  ["Built with", [
    ["Alpaca", "https://alpaca.markets", true],
    ["Featherless AI", "https://featherless.ai", true],
    ["lablab.ai", "https://lablab.ai", true],
  ]],
];

export function Footer() {
  return (
    <footer className="border-t border-ink-line px-6 py-14">
      <div className="mx-auto max-w-content">
        <div className="grid gap-10 lg:grid-cols-[1.6fr_repeat(3,1fr)]">
          <div className="max-w-sm">
            <Wordmark height={34} />
            <p className="mt-4 font-sans text-[12.5px] leading-[1.7] text-muted">
              An autonomous multi-agent options desk on Alpaca paper trading, built for the
              lablab.ai × Alpaca AI Trading Agents Hackathon.
            </p>
          </div>

          {COLUMNS.map(([heading, links]) => (
            <div key={heading}>
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{heading}</div>
              <ul className="mt-4 space-y-2.5">
                {links.map(([label, href, external]) => (
                  <li key={label}>
                    {external ? (
                      <a href={href} target="_blank" rel="noreferrer"
                         className="underline-grow font-sans text-[13px] text-muted transition-colors hover:text-gain">
                        {label}
                      </a>
                    ) : (
                      <Link href={href} className="underline-grow font-sans text-[13px] text-muted transition-colors hover:text-gain">
                        {label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 border-t border-ink-line pt-6">
          <p className="max-w-4xl font-sans text-[11.5px] leading-[1.7] text-faint">
            Paper trading only. Paper-trading results are hypothetical, do not involve actual
            securities transactions, and do not guarantee future results. Options trading carries
            substantial risk of loss and is not suitable for every investor; read the
            Characteristics and Risks of Standardized Options before trading options with real
            capital. Nothing here is investment advice.
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 font-mono text-[11px] text-faint">
            <span>MIT licensed · Built by Ifeanyichukwu Onwo</span>
            <span>Deflow · 2026</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
