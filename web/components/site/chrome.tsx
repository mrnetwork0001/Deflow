"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

export const GITHUB_URL = "https://github.com/mrnetwork0001/Deflow";

/** The icon mark alone — a capped payoff diagram in a rounded square. */
export function Mark({ size = 24 }: { size?: number }) {
  return (
    // Plain <img>, not next/image: this is a static export with
    // images.unoptimized, so the loader would add machinery for no benefit.
    <img
      src="/icon-192.png"
      alt=""
      width={size}
      height={size}
      aria-hidden
      className="select-none"
      style={{ width: size, height: size }}
    />
  );
}

/**
 * Full lockup: mark, rule, DEFLOW, and the tagline beneath it.
 *
 * Served as a transparent PNG at 2× so it stays crisp on retina. The source
 * artwork ships on a solid black matte, which would read as a dark rectangle
 * against the page, so the matte is keyed out by luminance at build time --
 * that preserves the antialiased stroke edges rather than cutting a hard,
 * jagged silhouette.
 */
export function Wordmark({ height = 30, className = "" }: { height?: number; className?: string }) {
  return (
    <img
      src="/deflow-header.png"
      srcSet="/deflow-header.png 1x, /deflow-header@2x.png 2x"
      alt="Deflow — autonomy, with limits."
      className={`select-none ${className}`}
      style={{ height, width: "auto" }}
    />
  );
}

const NAV = [
  ["The problem", "#problem"],
  ["The edge", "#edge"],
  ["The desk", "#desk"],
  ["Risk gate", "#gate"],
  ["Auditability", "#audit"],
];

export function Nav() {
  const [solid, setSolid] = useState(false);
  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className={`fixed inset-x-0 top-0 z-50 transition-colors duration-300 ${
        solid ? "border-b border-ink-line bg-ink/85 backdrop-blur-xl" : "border-b border-transparent"
      }`}
    >
      <div className="mx-auto flex max-w-content items-center justify-between px-6 py-3.5">
        <Link href="/" className="group flex items-center" aria-label="Deflow home">
          <Wordmark height={30} className="transition-opacity group-hover:opacity-80" />
        </Link>

        <div className="hidden items-center gap-8 lg:flex">
          {NAV.map(([label, href]) => (
            <a key={href} href={href} className="text-[13px] text-muted transition-colors hover:text-body">
              {label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/ledger/"
            className="hidden rounded-md border border-ink-hair px-3.5 py-2 font-mono text-[11px] text-muted transition-colors hover:border-muted hover:text-body sm:block"
          >
            Ledger
          </Link>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden rounded-md border border-ink-hair px-3.5 py-2 font-mono text-[11px] text-muted transition-colors hover:border-muted hover:text-body md:block"
          >
            GitHub
          </a>
          <Link
            href="/dashboard/"
            className="rounded-md bg-gain px-4 py-2 font-mono text-[11px] font-bold text-ink transition-colors hover:bg-gain-dim"
          >
            Launch app
          </Link>
        </div>
      </div>
    </nav>
  );
}

/** Section wrapper: consistent vertical rhythm and heading treatment. */
export function Section({
  id, eyebrow, title, lead, center = false, children, className = "", divider = true,
}: {
  id?: string; eyebrow?: string; title?: React.ReactNode; lead?: string;
  center?: boolean; children?: React.ReactNode; className?: string; divider?: boolean;
}) {
  return (
    <section
      id={id}
      className={`scroll-mt-20 px-5 py-24 sm:py-28 ${divider ? "border-t border-ink-line" : ""} ${className}`}
    >
      <div className="mx-auto max-w-content">
        {(eyebrow || title || lead) && (
          <header className={center ? "mx-auto max-w-2xl text-center" : "max-w-3xl"}>
            {eyebrow && <div className="eyebrow mb-4">{eyebrow}</div>}
            {title && (
              <h2 className="font-sans text-[30px] font-semibold leading-[1.15] tracking-tightest text-body sm:text-[40px]">
                {title}
              </h2>
            )}
            {lead && (
              <p className={`mt-5 font-sans text-[15px] leading-[1.7] text-muted ${center ? "" : "max-w-prose"}`}>
                {lead}
              </p>
            )}
          </header>
        )}
        {children && <div className={eyebrow || title || lead ? "mt-14" : ""}>{children}</div>}
      </div>
    </section>
  );
}

export function Card({
  children, className = "", hover = true,
}: { children: React.ReactNode; className?: string; hover?: boolean }) {
  return (
    <div
      className={`rounded-xl border border-ink-line bg-ink-card ${
        hover ? "transition-colors duration-300 hover:border-ink-hair" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function Pill({
  children, tone = "muted",
}: { children: React.ReactNode; tone?: "muted" | "gain" | "loss" | "warn" | "info" }) {
  const tones = {
    muted: "border-ink-hair text-muted",
    gain: "border-gain/40 bg-gain/10 text-gain",
    loss: "border-loss/40 bg-loss/10 text-loss",
    warn: "border-warn/40 bg-warn/10 text-warn",
    info: "border-info/40 bg-info/10 text-info",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function ButtonLink({
  href, children, variant = "primary", external = false,
}: { href: string; children: React.ReactNode; variant?: "primary" | "ghost"; external?: boolean }) {
  const cls =
    variant === "primary"
      ? "bg-gain text-ink hover:bg-gain-dim"
      : "border border-ink-hair bg-ink-raised text-body hover:border-muted";
  const inner = (
    <span className="group inline-flex items-center gap-2">
      {children}
      <span className="transition-transform duration-200 group-hover:translate-x-0.5">→</span>
    </span>
  );
  const shared = `inline-flex rounded-lg px-6 py-3 font-mono text-[13px] font-semibold transition-colors ${cls}`;
  return external ? (
    <a href={href} target="_blank" rel="noreferrer" className={shared}>{inner}</a>
  ) : (
    <Link href={href} className={shared}>{inner}</Link>
  );
}
