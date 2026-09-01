"use client";

import { Position, money, pct, signedMoney } from "@/lib/api";
import { Badge, Empty, Panel } from "./ui";

export function PositionsTable({ open, closed }: { open: Position[]; closed: Position[] }) {
  return (
    <Panel
      title="Open structures"
      right={<Badge tone={open.length ? "info" : "muted"}>{open.length} live · {closed.length} closed</Badge>}
    >
      {open.length === 0 ? (
        <Empty>No open positions. The desk trades only when it measures an edge.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-ink-line text-left text-[10px] uppercase tracking-wider text-muted">
                <th className="pb-2 pr-3 font-medium">Symbol</th>
                <th className="pb-2 pr-3 font-medium">Structure</th>
                <th className="pb-2 pr-3 text-right font-medium">Qty</th>
                <th className="pb-2 pr-3 text-right font-medium">Strikes</th>
                <th className="pb-2 pr-3 text-right font-medium">DTE</th>
                <th className="pb-2 pr-3 text-right font-medium">Max loss</th>
                <th className="pb-2 pr-3 text-right font-medium">Max profit</th>
                <th className="pb-2 pr-3 text-right font-medium">P(profit)</th>
                <th className="pb-2 pr-3 text-right font-medium">Δ</th>
                <th className="pb-2 pr-3 text-right font-medium">Θ/day</th>
                <th className="pb-2 text-right font-medium">Unrealised</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.proposal_id} className="border-b border-ink-line/40 last:border-0">
                  <td className="py-2 pr-3 font-bold text-body">
                    {p.symbol}
                    {p.simulated && <span className="ml-1.5 text-[9px] font-normal text-warn">sim</span>}
                    {p.mark_suspect && <span className="ml-1.5 text-[9px] font-normal text-loss" title="Last mark fell outside the structure's payoff bounds">?</span>}
                  </td>
                  <td className="py-2 pr-3 text-muted">{p.strategy.replace(/_/g, " ")}</td>
                  <td className="tabular py-2 pr-3 text-right">{p.contracts}</td>
                  <td className="tabular py-2 pr-3 text-right text-muted">
                    {p.legs.map((l) => l.strike).join(" / ")}
                  </td>
                  <td className="tabular py-2 pr-3 text-right">{p.dte}</td>
                  <td className="tabular py-2 pr-3 text-right text-loss">{money(p.max_loss, 0)}</td>
                  <td className="tabular py-2 pr-3 text-right text-gain">{money(p.max_profit, 0)}</td>
                  <td className="tabular py-2 pr-3 text-right">{pct(p.probability_of_profit, 0)}</td>
                  <td className="tabular py-2 pr-3 text-right text-muted">{p.net_delta >= 0 ? "+" : ""}{p.net_delta.toFixed(3)}</td>
                  <td className="tabular py-2 pr-3 text-right text-muted">{p.greeks.theta >= 0 ? "+" : ""}{p.greeks.theta.toFixed(1)}</td>
                  <td className={`tabular py-2 text-right font-semibold ${p.unrealized_pnl >= 0 ? "text-gain" : "text-loss"}`}>
                    {signedMoney(p.unrealized_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {closed.length > 0 && (
        <div className="mt-4 border-t border-ink-line pt-3">
          <h3 className="mb-2 text-[10px] uppercase tracking-[0.12em] text-muted">Closed</h3>
          <ul className="space-y-1">
            {closed.slice(-6).reverse().map((c) => (
              <li key={c.proposal_id + c.entry_at} className="flex items-baseline gap-2 text-[10px]">
                <span className={`tabular w-20 shrink-0 text-right font-semibold ${(c.realized_pnl ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
                  {signedMoney(c.realized_pnl ?? 0)}
                </span>
                <span className="w-12 shrink-0 font-bold text-body">{c.symbol}</span>
                <span className="truncate text-muted">{c.close_reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
