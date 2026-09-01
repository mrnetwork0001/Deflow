"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "@/lib/api";

/** Shape of /api/pnl-card. Money fields are null when the day has no basis to
 *  report on -- an empty card is rendered as "no activity", never as $0.00. */
interface Card {
  date: string;
  basis: "alpaca" | "deflow-mid" | "none";
  equity: number | null;
  day_pnl: number | null;
  day_return_pct: number | null;
  cycles: number;
  orders_submitted: number;
  refusals: number;
  vetoes: number;
  ledger_entries_for_day: number;
  ledger_head: string;
  is_today: boolean;
  note?: string;
}

const FIRST_SESSION = "2026-09-01"; // the desk's first live trading day

const usd = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const signedUsd = (n: number) => (n >= 0 ? `+${usd(n)}` : usd(n));

/* ---- the PNG itself ------------------------------------------------------
   Drawn by hand on a canvas: no html-to-image dependency, no font loading
   races, and the output is a deterministic 1200x630 (og-image sized) card
   that looks identical on every machine. */
function draw(
  canvas: HTMLCanvasElement,
  card: Card,
  logo: HTMLImageElement | null,
) {
  const W = 1200;
  const H = 630;
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d");
  if (!g) return;

  const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  const gain = "#00e08a";
  const loss = "#ff5a5a";
  const body = "#dfe4ea";
  const muted = "#7c8595";
  const faint = "#525b6b";

  g.fillStyle = "#08090b";
  g.fillRect(0, 0, W, H);
  g.strokeStyle = "#1e2229";
  g.lineWidth = 2;
  g.strokeRect(1, 1, W - 2, H - 2);

  // Header: wordmark left, date right.
  if (logo) {
    const h = 40;
    g.drawImage(logo, 64, 56, (logo.naturalWidth / logo.naturalHeight) * h, h);
  } else {
    g.fillStyle = body;
    g.font = `700 34px ${MONO}`;
    g.fillText("DEFLOW", 64, 92);
  }
  g.fillStyle = muted;
  g.font = `400 24px ${MONO}`;
  g.textAlign = "right";
  g.fillText(card.date, W - 64, 88);
  g.textAlign = "left";

  // Headline: the day's P&L.
  if (card.day_pnl !== null && card.equity !== null) {
    const tone = card.day_pnl >= 0 ? gain : loss;
    g.fillStyle = faint;
    g.font = `600 22px ${MONO}`;
    g.fillText("DAY P&L", 64, 210);
    g.fillStyle = tone;
    g.font = `700 104px ${MONO}`;
    g.fillText(signedUsd(card.day_pnl), 60, 320);
    g.fillStyle = muted;
    g.font = `400 30px ${MONO}`;
    const pct = card.day_return_pct ?? 0;
    g.fillText(`${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`, 64, 370);

    g.fillStyle = faint;
    g.font = `600 22px ${MONO}`;
    g.textAlign = "right";
    g.fillText("EQUITY", W - 64, 210);
    g.fillStyle = body;
    g.font = `700 44px ${MONO}`;
    g.fillText(usd(card.equity), W - 64, 262);
    g.textAlign = "left";
  } else {
    g.fillStyle = muted;
    g.font = `400 40px ${MONO}`;
    g.fillText("No trading activity on this date.", 64, 300);
  }

  // Stats row.
  const stats: Array<[string, string]> = [
    ["CYCLES", String(card.cycles)],
    ["ORDERS", String(card.orders_submitted)],
    ["REFUSALS", String(card.refusals)],
    ["GATE VETOES", String(card.vetoes)],
    ["LEDGER ENTRIES", String(card.ledger_entries_for_day)],
  ];
  const x0 = 64;
  const step = (W - 128) / stats.length;
  stats.forEach(([label, value], i) => {
    g.fillStyle = faint;
    g.font = `600 18px ${MONO}`;
    g.fillText(label, x0 + i * step, 468);
    g.fillStyle = body;
    g.font = `700 40px ${MONO}`;
    g.fillText(value, x0 + i * step, 516);
  });

  // Footer: the basis the money is on, and the chain that makes it checkable.
  // Two rows, not one: at 18px mono the basis+hash line alone runs ~750px and
  // the disclaimer ~390px -- side by side they overlap in the middle of a
  // 1072px-wide content box, which is exactly how it shipped the first time.
  g.fillStyle = faint;
  g.font = `400 18px ${MONO}`;
  const basis =
    card.basis === "alpaca"
      ? "marked by the broker (Alpaca)"
      : card.basis === "deflow-mid"
        ? "desk quote-mid marks"
        : "no mark basis";
  g.fillText(`${basis} · ledger ${card.ledger_head.slice(0, 16)}… hash-chained`, 64, 570);
  g.textAlign = "right";
  g.fillText("Paper trading · hypothetical results", W - 64, 598);
  g.textAlign = "left";
}

export function PnlCard() {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const logoRef = useRef<HTMLImageElement | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // The wordmark bitmap, fetched once. Same-origin, so it does not taint the
  // canvas; if it fails to load the card falls back to drawn text.
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      logoRef.current = img;
    };
    img.src = "/deflow-header@2x.png";
  }, []);

  const load = useCallback(async (d: string) => {
    setError(null);
    try {
      setCard(await getJSON<Card>(`/api/pnl-card?date=${d}`));
    } catch (e) {
      setCard(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (open) load(date);
  }, [open, date, load]);

  useEffect(() => {
    if (card && canvasRef.current) draw(canvasRef.current, card, logoRef.current);
  }, [card]);

  useEffect(() => {
    if (!open) return;
    dialogRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const download = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !card) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `deflow-pnl-${card.date}.png`;
      a.click();
      // Give the click a beat to start before releasing the blob.
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    }, "image/png");
  }, [card]);

  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-md border border-ink-hair px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted transition-colors hover:border-gain/50 hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
      >
        P&L card
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/85 p-4 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Daily P&L card"
            tabIndex={-1}
            className="w-full max-w-[720px] rounded-xl border border-ink-line bg-ink-card p-4 focus:outline-none"
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                Daily P&L card
              </h2>
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={date}
                  min={FIRST_SESSION}
                  max={today}
                  onChange={(e) => setDate(e.target.value)}
                  aria-label="Trading date"
                  className="rounded-md border border-ink-hair bg-ink px-2 py-1 font-mono text-[11.5px] text-body [color-scheme:dark] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
                />
                <button
                  onClick={download}
                  disabled={!card || card.basis === "none"}
                  className="rounded-md bg-gain px-3 py-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.08em] text-ink transition-colors hover:bg-gain-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gain/50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Download PNG
                </button>
                <button
                  onClick={() => setOpen(false)}
                  aria-label="Close"
                  className="rounded-md border border-ink-hair px-2 py-1 font-mono text-[11px] text-muted transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gain/60"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* The canvas IS the preview: what is on screen is byte-for-byte
                what downloads, so there is no drift between the two. */}
            <canvas
              ref={canvasRef}
              className="block w-full rounded-lg border border-ink-line"
              aria-label={
                card
                  ? `P&L card for ${card.date}: day P&L ${
                      card.day_pnl === null ? "unavailable" : signedUsd(card.day_pnl)
                    }`
                  : "P&L card loading"
              }
            />
            {error && (
              <p className="mt-2 font-mono text-[11px] text-loss">{error}</p>
            )}
            {card?.note && (
              <p className="mt-2 font-mono text-[10.5px] text-faint">{card.note}</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
