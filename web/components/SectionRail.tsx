"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";

/**
 * The sub-line is static attribution text rather than a fetched figure: which
 * agent owns a section is a fact about the desk, not a measurement, and there is
 * no poll that could confirm or refute it.
 *
 * The three badges below DO repeat a number the panel beside them already
 * prints. That is safe only because each pair reads the same object out of the
 * same poll in the same render, so they cannot drift apart — see the note above
 * railCounts in page.tsx. A badge fed from a *different* response could disagree
 * with its visible neighbour, and only one of the two could be right.
 */
const SECTIONS = [
  { id: "account", label: "Account", sub: null, count: null, unit: null },
  { id: "equity", label: "Equity", sub: null, count: null, unit: null },
  { id: "regime", label: "Regime", sub: "agent 1", count: "regime", unit: " tradeable of scanned" },
  { id: "structures", label: "Structures", sub: "agents 2 · 4", count: "structures", unit: " open structures" },
  { id: "stream", label: "Stream", sub: "all agents", count: null, unit: null },
  { id: "refusals", label: "Refusals", sub: "agent 3", count: null, unit: null },
  { id: "gate", label: "Risk gate", sub: "zero llm", count: "gate", unit: " vetoes this session" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

interface SectionRailProps {
  /** Already-formatted strings. A null entry renders no badge at all — see below. */
  counts: { regime: string | null; structures: string | null; gate: string | null };
  working: boolean;
  equity: string | null;
  pnl: string | null;
  pnlTone: "gain" | "loss" | null;
  /** Last refresh failed but earlier data is still on screen. The pinned card is
   *  the only equity readout that survives the scroll, so it is the one figure
   *  that can be read long after it stopped being true. */
  stale: boolean;
  ledgerBroken: boolean;
}

/** Distance below the viewport top at which a section counts as the one being read. */
const READING_LINE = 140;

/** How long the click-driven scroll may go quiet before the highlight is handed
 *  back to the page. Long enough to bridge a frame drop mid-animation, short
 *  enough that the first real user scroll after it lands releases immediately. */
const CLICK_SETTLE_MS = 180;

/**
 * At xl the structures table and the decision stream share one grid row, so
 * their top edges coincide and no reading line can ever separate them. Lighting
 * only the lower one would leave "Structures" permanently dark; the honest
 * answer is that this screenful really is both panels. Detected geometrically
 * rather than with a media query, so it survives any change to the breakpoint
 * or to the column split.
 */
const PAIR: SectionId[] = ["structures", "stream"];
const PAIRED_TOP_TOLERANCE = 24;

// `relative` is load-bearing, not cosmetic: the sr-only unit spans inside are
// position:absolute, and without a positioned row their containing block is the
// sticky rail root. Below xl the <ul> is a horizontal scroller, and an absolute
// box whose containing block sits outside that scroller is not clipped by it —
// the spans then stick out at their un-scrolled x and give the whole document
// ~264px of horizontal scroll at 375px wide.
const ROW =
  "group relative block whitespace-nowrap border-b-[1.5px] px-3 py-2.5 transition-colors duration-150 " +
  // ring-inset, because the ring is a box-shadow outside the border box and both
  // the mobile strip and the xl nav are scroll containers that clip it away.
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-gain/60 " +
  "xl:-ml-px xl:border-b-0 xl:border-l xl:py-[7px] xl:pl-3 xl:pr-2";
const SUB = "mt-[3px] hidden font-mono text-[9.5px] lowercase tracking-[0.02em] xl:block";

export function SectionRail({
  counts, working, equity, pnl, pnlTone, stale, ledgerBroken,
}: SectionRailProps) {
  const [active, setActive] = useState<SectionId>("account");
  const [joined, setJoined] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);
  /**
   * A rail click is an explicit statement of intent, and it outranks the
   * geometry until the reader moves the page themselves. `armed` flips once the
   * click's own smooth scroll has gone quiet, so the very next scroll event
   * after that must have come from the user and hands the highlight back.
   *
   * Not a plain timeout: at the foot of the document the clicked section may be
   * one the geometry can never select (see the promotion below), so a timeout
   * would light a different row a second after the click — which is the bug this
   * exists to prevent, only delayed.
   */
  const lock = useRef<{ armed: boolean } | null>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let frame = 0;

    const measure = () => {
      frame = 0;
      if (lock.current) return;

      const doc = document.documentElement;
      const rect = (id: SectionId) =>
        document.getElementById(id)?.getBoundingClientRect();

      const a = rect(PAIR[0])?.top;
      const b = rect(PAIR[1])?.top;
      const sideBySide =
        a !== undefined && b !== undefined && Math.abs(a - b) < PAIRED_TOP_TOLERANCE;
      setJoined(sideBySide);
      // Side by side, the pair is one band with one entry point.
      const ids = SECTIONS.map((s) => s.id).filter((id) => !(sideBySide && id === PAIR[1]));

      let found: SectionId = ids[0];
      for (const id of ids) {
        const edge = rect(id)?.top;
        // A section that is absent must not stop the walk, or every section
        // below it becomes unreachable in the rail.
        if (edge === undefined || edge > READING_LINE) continue;
        found = id;
      }

      // The last section is short — the gate panel plus the footer is under
      // 450px — so on any viewport taller than that its top edge can never be
      // scrolled up to the reading line, and the walk above can never choose it.
      // Measured at the foot of this page: at 1440x900 the gate sits at y=230
      // with nothing below it but the footer, and the walk still says Refusals.
      //
      // So promote, but only on evidence rather than on scroll position alone:
      // the page must actually be scrollable (an unscrollable one is at its
      // "foot" from first paint, which would pin the rail to the bottom row
      // before the reader has done anything), it must be scrolled to the end,
      // and the last section must be entirely on screen — if you can see all of
      // it and there is nothing after it, there is nothing else you could be
      // reading.
      const scrollable = doc.scrollHeight > window.innerHeight + 2;
      const atFoot = scrollable && window.scrollY + window.innerHeight >= doc.scrollHeight - 2;
      if (atFoot) {
        const lastId = ids[ids.length - 1];
        const last = document.getElementById(lastId)?.getBoundingClientRect();
        if (last && last.top >= 0 && last.bottom <= window.innerHeight) found = lastId;
      }
      setActive(found);
    };

    // A gesture is unambiguous, so it need not wait for the settle timer.
    const release = () => { clearTimeout(settle.current); lock.current = null; };

    const schedule = () => {
      // A hash navigation scrolls smoothly, which emits scroll events for the
      // whole ~600ms animation. Without this the walk lights every row the page
      // travels past, so clicking the last row strobes through all six above it.
      if (lock.current) {
        if (!lock.current.armed) {
          clearTimeout(settle.current);
          settle.current = setTimeout(() => {
            if (lock.current) lock.current.armed = true;
          }, CLICK_SETTLE_MS);
          return;
        }
        release();
      }
      if (!frame) frame = requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    window.addEventListener("wheel", release, { passive: true });
    window.addEventListener("touchstart", release, { passive: true });
    window.addEventListener("keydown", release);
    // Panels grow as the 5s poll lands rows. Offsets therefore change with no
    // scroll event, and without this the highlight is stale until you move.
    const observer = new ResizeObserver(schedule);
    observer.observe(document.body);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      clearTimeout(settle.current);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("wheel", release);
      window.removeEventListener("touchstart", release);
      window.removeEventListener("keydown", release);
      observer.disconnect();
    };
  }, []);

  // Below xl the rail is a horizontal strip, so the lit chip can sit off-screen.
  // scrollLeft is written directly rather than calling scrollIntoView, which can
  // scroll the *page* when the strip is partly off-screen and fights a user
  // mid-drag. A direct write is instant, so it needs no reduced-motion branch.
  useEffect(() => {
    const list = listRef.current;
    if (!list || list.scrollWidth <= list.clientWidth) return;
    const chip = list.querySelector<HTMLElement>(`[data-chip="${active}"]`);
    if (!chip) return;
    list.scrollLeft = chip.offsetLeft - list.clientWidth / 2 + chip.clientWidth / 2;
  }, [active]);

  return (
    // xl:self-start is load-bearing: a grid item defaults to align-self:stretch,
    // which makes the box full-height and turns position:sticky into a silent
    // no-op. z-30 clears PositionsTable's sticky symbol column (z-10) and the
    // stream's floating jump button; z-50 belongs to the marketing nav. The
    // negative margins cancel <main>'s padding so the mobile strip is full-bleed
    // and nothing shows through beside it while stuck; the list's own px-4/px-6
    // puts the labels back on the page's alignment.
    //
    // max-h, never h: a hard calc(100vh-3rem) is only the right height once the
    // rail is actually stuck at y=24. At scroll top it still sits below the
    // header, so that height overhangs the viewport by exactly the header's
    // block size and slices the bottom off the pinned card — a header height CSS
    // cannot know. max-h lets the rail size to its content and only clamps when
    // the nav is genuinely taller than the screen.
    <div className="sticky top-0 z-30 -mx-4 mb-4 border-b border-ink-line bg-ink/90 backdrop-blur-md sm:-mx-6 xl:top-6 xl:z-auto xl:mx-0 xl:mb-0 xl:flex xl:max-h-[calc(100vh-3rem)] xl:flex-col xl:self-start xl:border-b-0 xl:bg-transparent xl:backdrop-blur-none">
      {/* Named because the header also contains links. min-h-0 or the flex child
          refuses to shrink and the pinned card is pushed below the fold.
          Deliberately no aria-live: these counts repoll every five seconds and
          announcing them twelve times a minute is hostile. */}
      <nav aria-label="Dashboard sections" className="xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:overscroll-contain">
        {/* globals.css styles ::-webkit-scrollbar at 9px, which under a ~40px
            strip reads as broken. snap-x plus a clipped final label is enough
            affordance on its own. */}
        <ul
          ref={listRef}
          className="flex snap-x overflow-x-auto px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:px-6 xl:flex-col xl:overflow-visible xl:border-l xl:border-ink-line xl:px-0"
        >
          {SECTIONS.map((s, i) => {
            const on = active === s.id || (joined && PAIR.includes(s.id) && PAIR.includes(active));
            const value = s.count ? counts[s.count] : null;
            const dot = s.id === "structures" && working;
            return (
              <Fragment key={s.id}>
                {/* Minor graduation: state above, machine below. */}
                {i === 2 && <li aria-hidden className="hidden xl:block my-2 ml-3 h-px w-4 bg-ink-line" />}
                <li className="shrink-0 snap-start xl:shrink">
                  <a
                    href={`#${s.id}`}
                    data-chip={s.id}
                    // Only ever one current item, even when the pair is lit as one band.
                    aria-current={active === s.id ? "location" : undefined}
                    // No preventDefault: the hash navigation must stay native, which
                    // is what gives smooth scrolling for free, what makes the row
                    // work before hydration on a statically exported page, and what
                    // keeps the deep link middle-clickable. The focus move only lets
                    // a keyboard user land inside the section; preventScroll stops
                    // the focus jump pre-empting the smooth scroll.
                    onClick={() => {
                      lock.current = { armed: false };
                      setActive(s.id);
                      document.getElementById(s.id)?.focus({ preventScroll: true });
                    }}
                    className={`${ROW} ${on ? "border-gain xl:border-l-gain" : "border-transparent xl:border-l-transparent"}`}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      {/* group-hover, not hover: a bare hover on the span only
                          fires directly over the glyphs. text-muted, not
                          text-faint: this is the whole visible label of a
                          navigation link, and every row but one is in this
                          state at any moment. */}
                      <span
                        className={`font-mono text-[10.5px] uppercase tracking-[0.14em] ${
                          on ? "text-body" : "text-muted group-hover:text-body"
                        }`}
                      >
                        {s.label}
                      </span>
                      {/* A count that has not loaded renders NOTHING — not 0 and
                          not an em dash. In a 148px row an em dash reads as an
                          error state; absence reads as "this row has no badge",
                          which is the truth before data lands. */}
                      {(value !== null || dot) && (
                        <span className="flex shrink-0 items-center gap-1.5">
                          {/* The amber dot is the rail's only sign that orders
                              are out, so it cannot be the *only* sign: colour
                              and shape alone reach neither a screen reader nor
                              a reader who cannot separate amber from grey. */}
                          {dot && (
                            <>
                              <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
                              <span className="sr-only">working orders, </span>
                            </>
                          )}
                          {value !== null && (
                            <span className="tabular shrink-0 font-mono text-[9.5px] text-muted">
                              {value}
                              {/* Carries the unit. No title on the row: a link
                                  with text content uses title as its accessible
                                  *description*, so the unit would be announced
                                  twice — and the title was unconditional while
                                  the badge it describes is not, leaving a
                                  tooltip for a number that is not on screen. */}
                              <span className="sr-only">{s.unit}</span>
                            </span>
                          )}
                        </span>
                      )}
                    </span>
                    {s.sub && <span className={`${SUB} text-muted`}>{s.sub}</span>}
                  </a>
                </li>
              </Fragment>
            );
          })}

          {/* Major graduation: in-page anchors above, a route that leaves below. */}
          <li aria-hidden className="hidden xl:block my-2.5 ml-3 h-px w-8 bg-ink-hair" />
          <li className="shrink-0 snap-start xl:shrink">
            {/* Duplicates the header's Ledger link on purpose: both read
                status.ledger from the same poll so they cannot disagree, and the
                point of this row is keeping the chain-broken alarm on screen
                after the header has scrolled away. Never in the scrollspy walk,
                so it never takes the gain segment or aria-current. */}
            <Link
              href="/ledger/"
              className={`${ROW} ${ledgerBroken ? "border-loss xl:border-l-loss" : "border-transparent xl:border-l-transparent"}`}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span
                  className={`font-mono text-[10.5px] uppercase tracking-[0.14em] ${
                    ledgerBroken ? "text-loss" : "text-muted group-hover:text-body"
                  }`}
                >
                  Ledger
                  <span aria-hidden className="ml-1 text-faint">↗</span>
                </span>
              </span>
              {/* Before load this says "hash-chained", which describes the
                  mechanism rather than claiming the chain has been verified. The
                  broken state is carried by the words as well as the colour, so
                  both states are rendered at full token strength — a dimmed
                  alarm is a colour-only alarm. */}
              <span className={`${SUB} ${ledgerBroken ? "text-loss" : "text-muted"}`}>
                {ledgerBroken ? "chain broken" : "hash-chained"}
              </span>
            </Link>
          </li>
        </ul>
      </nav>

      {/* The Sluice wallet card: equity and P&L stay on screen for the whole
          scroll instead of only at the top of it. The em dash IS correct here —
          this is a Stat-shaped readout with a label to hang it on, unlike the
          bare badges above. It carries nothing else: absorbing the header's
          status strip or Ledger link into the rail is the regression this whole
          rail is built to avoid.

          It is also the only readout on the page that survives the scroll, so it
          is the only one that can still be read long after the backend stopped
          answering. PositionsTable and EquityCurve both mark their own stale
          state; off-screen, neither of those warnings reaches the reader. */}
      <div className="hidden shrink-0 rounded-lg border border-ink-line bg-ink-raised p-3 xl:mt-3 xl:block">
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Equity</div>
        <div
          className={`tabular mt-1 font-mono text-[15px] font-bold ${
            !equity ? "text-faint" : stale ? "text-muted" : "text-body"
          }`}
        >
          {equity ?? "—"}
        </div>
        <div
          className={`tabular mt-1 font-mono text-[10.5px] ${
            !(pnl && pnlTone) ? "text-faint" : stale ? "text-muted" : pnlTone === "gain" ? "text-gain" : "text-loss"
          }`}
        >
          {pnl ?? "—"}
        </div>
        {stale && (
          <div className="mt-1.5 font-mono text-[9.5px] lowercase tracking-[0.02em] text-warn">
            last seen — refresh failed
          </div>
        )}
      </div>
    </div>
  );
}
