// Client for the Deflow FastAPI backend.
//
// In production the dashboard is served by that same backend as a static
// export, so relative URLs resolve correctly. In `next dev` it runs on :3000
// and talks to :8000, which is why the base URL is configurable.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (typeof window !== "undefined" && window.location.port === "3000"
    ? "http://127.0.0.1:8000"
    : "");

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return response.json() as Promise<T>;
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${path} → ${response.status}`);
  return response.json() as Promise<T>;
}

export const money = (n: number, digits = 2) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });

export const signedMoney = (n: number) => `${n >= 0 ? "+" : "−"}${money(Math.abs(n))}`;

export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;

export const signedPct = (n: number, digits = 2) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(digits)}%`;

// --- Shapes returned by the backend ---------------------------------------

export interface Performance {
  starting_equity: number; equity: number; realized_pnl: number; unrealized_pnl: number;
  total_pnl: number; return_pct: number; day_pnl: number; open_positions: number;
  closed_positions: number; wins: number; losses: number; win_rate: number;
  avg_win: number; avg_loss: number; profit_factor: number | null;
  capital_at_risk: number; capital_at_risk_pct: number; net_delta: number; net_vega: number;
}

export interface Breaker { id: number; name: string; passed: boolean; detail: string; observed: number | null; limit: number | null; }

export interface WorkingOrder {
  proposal_id: string; symbol: string; strategy: string; contracts: number;
  order_id: string; limit_price: number; status: string; age_seconds: number;
  max_loss: number; simulated: boolean;
}

export interface Status {
  mode: string;
  market_open?: boolean;
  working_orders?: WorkingOrder[];
  simulated_market_data: boolean;
  universe: string[];
  cycles_run: number;
  execution: { route: string; cli_available: boolean; cli_version: string; rest_available: boolean; dry_run: boolean; simulated: boolean };
  reasoning: { featherless_enabled: boolean; model: string; calls: number; failures: number };
  risk_envelope: Record<string, any>;
  performance: Performance;
  ledger: { entries: number; head: string; valid: boolean; broken_at: number | null; detail: string };
  scheduler?: { running: boolean; interval_seconds: number };
  last_cycle: any;
}

export interface AnalystView {
  symbol: string; price: number; iv_rank: number; iv_30d: number; hv_60d: number;
  variance_premium: number; trend_score: number; regime: string; rsi14: number;
  stance: string; bias: string; conviction: number; tradeable: boolean;
  reasons: string[]; brief: string;
}

export interface Position {
  proposal_id: string; symbol: string; strategy: string; direction: string;
  contracts: number; legs: { symbol: string; right: string; strike: number; ratio: number; price: number }[];
  max_loss: number; max_profit: number; probability_of_profit: number;
  breakevens: number[]; net_delta: number; dte: number;
  unrealized_pnl: number; pnl_pct_of_max_loss: number; realized_pnl?: number;
  entry_at: string; simulated: boolean; mark_suspect?: boolean;
  close_reason?: string; thesis: string;
  greeks: { delta: number; gamma: number; vega: number; theta: number };
}

export interface LedgerEntry { seq: number; at: string; event: string; payload: any; hash: string; prev_hash: string; }

// --- Equity curve ----------------------------------------------------------

export interface EquityPoint {
  /** Unix seconds when sourced from Alpaca, ISO-8601 when from the ledger. */
  t: number | string;
  equity: number;
  pnl: number;
}

export interface EquityCurve {
  source: "alpaca" | "ledger";
  base_value: number;
  points: EquityPoint[];
  note?: string;
}

/** Normalise either timestamp form to milliseconds. */
export const pointMillis = (t: number | string): number =>
  typeof t === "number" ? t * 1000 : Date.parse(t);

// --- Refusals --------------------------------------------------------------

export type RefusalStage = "analyst" | "reasoning" | "auditor" | "risk_gate";

export interface Refusal {
  seq: number;
  at: string;
  stage: RefusalStage;
  symbol: string;
  reason: string;
}

export interface Refusals {
  total: number;
  by_stage: Partial<Record<RefusalStage, number>>;
  refusals: Refusal[];
}

// --- Ledger ----------------------------------------------------------------

export interface ChainStatus {
  valid: boolean;
  entries: number;
  head: string;
  broken_at: number | null;
  detail: string;
}
