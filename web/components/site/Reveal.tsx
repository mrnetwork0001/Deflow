"use client";

import React, { useEffect, useRef, useState } from "react";

/**
 * Reveals its children as they scroll into view.
 *
 * Safe by default: the markup ships VISIBLE. The hidden state is applied by
 * JavaScript on mount and removed on intersection, so a reader with scripts
 * blocked, a crawler, or a hydration failure sees a complete page rather than
 * a blank one. Opacity-0-in-CSS is the usual way this is done and the usual
 * way pages end up empty.
 *
 * Reveals once and then stops observing - re-animating on every scroll past is
 * distracting on a page this long.
 */
export function Reveal({
  children,
  delay = 0,
  y = 14,
  className = "",
  as: Tag = "div",
}: {
  children: React.ReactNode;
  /** Stagger, in ms. Keep under ~250 or the page feels sluggish. */
  delay?: number;
  /** Travel distance. Small: motion should be felt, not watched. */
  y?: number;
  className?: string;
  as?: React.ElementType;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [state, setState] = useState<"idle" | "armed" | "shown">("idle");

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (
      typeof IntersectionObserver === "undefined" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setState("shown");
      return;
    }

    // Anything already on screen at mount is shown immediately - animating the
    // hero on load would just delay the first paint of the thing people came
    // for.
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight * 0.9) {
      setState("shown");
      return;
    }

    setState("armed");
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setState("shown");
          io.disconnect();
        }
      },
      // Fire a little before the element reaches the fold, so it has finished
      // moving by the time it is properly in view.
      { threshold: 0.08, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  return (
    <Tag
      ref={ref as never}
      className={className}
      style={{
        opacity: state === "armed" ? 0 : 1,
        transform: state === "armed" ? `translateY(${y}px)` : "translateY(0)",
        transition:
          state === "idle"
            ? undefined
            : `opacity 620ms cubic-bezier(.22,.8,.3,1) ${delay}ms, transform 620ms cubic-bezier(.22,.8,.3,1) ${delay}ms`,
        willChange: state === "shown" ? "auto" : "opacity, transform",
      }}
    >
      {children}
    </Tag>
  );
}

/** Staggers a list of children by index. */
export function RevealGroup({
  children, step = 70, className = "", y = 14,
}: { children: React.ReactNode; step?: number; className?: string; y?: number }) {
  return (
    <>
      {React.Children.map(children, (child, i) => (
        <Reveal delay={Math.min(i * step, 280)} y={y} className={className}>
          {child}
        </Reveal>
      ))}
    </>
  );
}
