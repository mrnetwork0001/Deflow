"""Agent 4 - Execution Agent.

The only component that talks to the broker, and the last place a bad trade
can be stopped.

Routing preference, highest first:

    cli   -> Alpaca's official CLI (`alpaca order submit --order-class mleg`).
             The default. Carries its own 429/5xx backoff, resolves
             credentials itself, and supports `--dry-run`, so the desk can
             prove the exact request body it would have sent.
    rest  -> Direct POST /v2/orders. Used when the CLI binary is absent.
    paper -> Local simulated fill. Used when there are no credentials at all,
             so a fresh clone still demonstrates the full pipeline. Every
             record it produces is tagged `simulated=True`.

Before routing anything, the executor **re-runs the deterministic risk gate**.
The desk has already run it once; running it again here means that no code
path -- including a future refactor, a retry, or a caller that forgot -- can
reach `submit` without a fresh approval on the exact proposal being sent.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from risk_gate import DeterministicRiskGate, PortfolioState, RiskVerdict

from ..alpaca_cli import AlpacaCLI
from ..alpaca_rest import AlpacaClient
from ..models import SpreadProposal, utcnow

log = logging.getLogger("deflow.executor")

# Cross the spread by this fraction of the bid/ask width to get filled without
# donating the whole edge. Mid-price limits on multi-leg spreads frequently sit
# unfilled all session.
SLIPPAGE_BUFFER = 0.03


@dataclass
class ExecutionResult:
    """Outcome of one routing attempt."""

    submitted: bool
    route: str
    proposal_id: str
    symbol: str
    strategy: str
    contracts: int
    limit_price: float
    order_id: str = ""
    client_order_id: str = ""
    simulated: bool = False
    dry_run: bool = False
    error: str = ""
    request_body: Dict[str, Any] = field(default_factory=dict)
    raw_response: Any = None
    at: str = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submitted": self.submitted,
            "route": self.route,
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "contracts": self.contracts,
            "limit_price": round(self.limit_price, 2),
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "simulated": self.simulated,
            "dry_run": self.dry_run,
            "error": self.error[:400],
            "request_body": self.request_body,
            "at": self.at,
        }


class ExecutionAgent:
    """Routes approved multi-leg orders to Alpaca."""

    name = "Agent 4 · Execution Agent"

    def __init__(
        self,
        gate: DeterministicRiskGate,
        cli: Optional[AlpacaCLI] = None,
        rest: Optional[AlpacaClient] = None,
        preferred_route: str = "auto",
        dry_run: bool = False,
    ) -> None:
        self.gate = gate
        self.cli = cli
        self.rest = rest
        self.preferred_route = preferred_route
        self.dry_run = dry_run
        self.submitted = 0
        self.rejected = 0

    # -- routing ------------------------------------------------------------

    def resolve_route(self) -> str:
        """Pick the execution route from what is actually available."""
        if self.preferred_route in {"cli", "rest", "paper"}:
            return self.preferred_route
        if self.cli and self.cli.available and self.cli.settings.has_alpaca_credentials:
            return "cli"
        if self.rest and self.rest.settings.has_alpaca_credentials:
            return "rest"
        return "paper"

    def describe_route(self) -> Dict[str, Any]:
        route = self.resolve_route()
        return {
            "route": route,
            "cli_available": bool(self.cli and self.cli.available),
            "cli_version": self.cli.version() if (self.cli and self.cli.available) else "",
            "rest_available": bool(self.rest and self.rest.settings.has_alpaca_credentials),
            "dry_run": self.dry_run,
            "simulated": route == "paper",
        }

    # -- pricing ------------------------------------------------------------

    @staticmethod
    def _buffered(net: float) -> float:
        """Apply the slippage concession to a net package price.

        Positive is a debit paid, negative is a credit received. The buffer
        moves the limit *against* us -- pay a touch more for a debit, accept a
        touch less for a credit -- so the order is marketable rather than
        resting at an untouched mid.
        """
        if net >= 0:
            return round(net * (1.0 + SLIPPAGE_BUFFER), 2)
        return round(net * (1.0 - SLIPPAGE_BUFFER), 2)

    @classmethod
    def limit_price_for(cls, proposal: SpreadProposal) -> float:
        """Net limit for OPENING the package, from its proposal-time premium."""
        return cls._buffered(proposal.net_premium)

    @staticmethod
    def legs_payload(proposal: SpreadProposal, closing: bool = False) -> List[Dict[str, Any]]:
        payload = []
        for leg in proposal.legs:
            side = "buy" if leg.ratio > 0 else "sell"
            if closing:
                side = "sell" if leg.ratio > 0 else "buy"
                intent = "sell_to_close" if leg.ratio > 0 else "buy_to_close"
            else:
                intent = "buy_to_open" if leg.ratio > 0 else "sell_to_open"
            payload.append(
                {
                    "symbol": leg.symbol,
                    "ratio_qty": abs(leg.ratio),
                    "side": side,
                    "position_intent": intent,
                }
            )
        return payload

    # -- submission ---------------------------------------------------------

    def submit(
        self,
        proposal: SpreadProposal,
        portfolio: PortfolioState,
        prior_verdict: Optional[RiskVerdict] = None,
    ) -> ExecutionResult:
        """Route an approved proposal. Re-checks the gate first, always."""
        client_order_id = f"deflow-{uuid.uuid4().hex[:24]}"
        limit_price = self.limit_price_for(proposal)

        base = dict(
            route=self.resolve_route(),
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            strategy=proposal.strategy.value,
            contracts=proposal.contracts,
            limit_price=limit_price,
            client_order_id=client_order_id,
            dry_run=self.dry_run,
        )

        # --- Defence in depth: the gate runs again, here, on this exact
        # --- proposal, no matter what the caller already decided.
        verdict = self.gate.evaluate_trade(proposal.to_risk_payload(), portfolio)
        if not verdict.approved:
            self.rejected += 1
            log.warning("Executor refused %s: %s", proposal.symbol, verdict.reason)
            return ExecutionResult(
                submitted=False,
                error=f"Execution-time risk gate refused the order. {verdict.reason}",
                **base,
            )

        # Contract count must not have grown since the gate sized it.
        if prior_verdict and proposal.contracts > prior_verdict.approved_contracts > 0:
            self.rejected += 1
            return ExecutionResult(
                submitted=False,
                error=(
                    f"Size mismatch: {proposal.contracts} contracts exceeds the "
                    f"{prior_verdict.approved_contracts} the gate approved."
                ),
                **base,
            )

        route = base["route"]
        if route == "cli":
            return self._submit_cli(proposal, limit_price, client_order_id, base)
        if route == "rest":
            return self._submit_rest(proposal, limit_price, base)
        return self._submit_paper(proposal, limit_price, base)

    def _submit_cli(
        self, proposal: SpreadProposal, limit_price: float, client_order_id: str, base: Dict[str, Any]
    ) -> ExecutionResult:
        assert self.cli is not None
        legs = self.legs_payload(proposal)
        result = self.cli.submit_mleg(
            legs=legs,
            quantity=proposal.contracts,
            limit_price=limit_price,
            client_order_id=client_order_id,
            dry_run=self.dry_run,
        )
        body = {
            "order_class": "mleg",
            "qty": str(proposal.contracts),
            "type": "limit",
            "time_in_force": "day",
            "limit_price": f"{limit_price:.2f}",
            "legs": legs,
        }
        if not result.ok:
            self.rejected += 1
            return ExecutionResult(submitted=False, error=result.stderr, request_body=body, **base)

        if self.dry_run:
            # `alpaca order submit --dry-run` prints the request body and exits
            # 0 without sending anything. Reporting that as a fill would book a
            # position that does not exist at the broker.
            return ExecutionResult(
                submitted=False,
                error="dry run: request rendered by the Alpaca CLI, not submitted",
                request_body=body,
                raw_response=result.data,
                **base,
            )

        self.submitted += 1
        payload = result.data if isinstance(result.data, dict) else {}
        return ExecutionResult(
            submitted=True,
            order_id=str(payload.get("id", "")),
            request_body=body,
            raw_response=result.data,
            **base,
        )

    def _submit_rest(
        self, proposal: SpreadProposal, limit_price: float, base: Dict[str, Any]
    ) -> ExecutionResult:
        assert self.rest is not None
        legs = self.legs_payload(proposal)
        body = AlpacaClient.build_mleg_payload(
            legs=[{**l, "ratio": l["ratio_qty"]} for l in legs],
            quantity=proposal.contracts,
            limit_price=limit_price,
        )
        if self.dry_run:
            return ExecutionResult(submitted=False, error="dry run: not submitted", request_body=body, **base)

        result = self.rest.submit_mleg_order(body)
        if not result.ok:
            self.rejected += 1
            return ExecutionResult(submitted=False, error=result.error, request_body=body, **base)

        self.submitted += 1
        payload = result.data if isinstance(result.data, dict) else {}
        return ExecutionResult(
            submitted=True,
            order_id=str(payload.get("id", "")),
            request_body=body,
            raw_response=result.data,
            **base,
        )

    def _submit_paper(
        self, proposal: SpreadProposal, limit_price: float, base: Dict[str, Any]
    ) -> ExecutionResult:
        """Local simulated fill for credential-free runs.

        Fills at the limit, which is already slippage-adjusted. Marked
        `simulated=True` everywhere it surfaces so it cannot be mistaken for a
        broker fill in the dashboard, the ledger, or the write-up.
        """
        legs = self.legs_payload(proposal)
        if self.dry_run:
            # --dry-run has to mean the same thing on every route, or the flag
            # is untrustworthy exactly where it matters most.
            return ExecutionResult(
                submitted=False,
                simulated=True,
                error="dry run: order rendered, not filled",
                request_body={"order_class": "mleg", "qty": str(proposal.contracts),
                              "limit_price": f"{limit_price:.2f}", "legs": legs},
                **base,
            )

        self.submitted += 1
        return ExecutionResult(
            submitted=True,
            order_id=f"sim-{uuid.uuid4().hex[:12]}",
            simulated=True,
            request_body={
                "order_class": "mleg",
                "qty": str(proposal.contracts),
                "type": "limit",
                "time_in_force": "day",
                "limit_price": f"{limit_price:.2f}",
                "legs": legs,
            },
            raw_response={"note": "simulated fill - no Alpaca credentials configured"},
            **base,
        )

    # -- fill reconciliation ------------------------------------------------

    def order_status(self, order_id: str) -> Dict[str, Any]:
        """Current state of a submitted order.

        Returns {status, filled_qty, filled_avg_price, found}. `submitted` only
        ever meant the broker accepted the request; whether a position exists
        is a separate question that has to be asked.
        """
        if order_id.startswith("sim-"):
            # A locally simulated fill is, by construction, filled.
            return {"status": "filled", "filled_qty": None, "filled_avg_price": None, "found": True}
        if not order_id:
            # An empty id used to fall into the simulated branch and report
            # "filled" -- which meant a CLI stdout parse quirk (ok=True, data
            # not a dict, id lost) booked a close at the last mid-mark while
            # the real order rested live and unpollable at the broker. An
            # order the desk cannot name is an order whose state it does not
            # know.
            return {"status": "unknown", "filled_qty": None, "filled_avg_price": None, "found": False}

        data: Optional[Dict[str, Any]] = None
        if self.cli and self.cli.available and self.cli.settings.has_alpaca_credentials:
            result = self.cli.get_order(order_id)
            if result.ok and isinstance(result.data, dict):
                data = result.data
        if data is None and self.rest is not None:
            result = self.rest.get_order(order_id)
            if result.ok and isinstance(result.data, dict):
                data = result.data

        if data is None:
            return {"status": "unknown", "filled_qty": None, "filled_avg_price": None, "found": False}

        def _f(key: str) -> Optional[float]:
            try:
                return float(data[key]) if data.get(key) not in (None, "") else None
            except (TypeError, ValueError):
                return None

        return {
            "status": str(data.get("status", "unknown")),
            "filled_qty": _f("filled_qty"),
            "filled_avg_price": _f("filled_avg_price"),
            "found": True,
        }

    def cancel(self, order_id: str) -> bool:
        if not order_id or order_id.startswith("sim-"):
            return True
        if self.cli and self.cli.available and self.cli.settings.has_alpaca_credentials:
            if self.cli.cancel_order(order_id).ok:
                return True
        if self.rest is not None:
            return bool(self.rest.cancel_order(order_id).ok)
        return False

    # -- exits --------------------------------------------------------------

    def close(
        self,
        proposal: SpreadProposal,
        reason: str,
        mark_premium: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> ExecutionResult:
        """Close an open structure. Exits are never gated -- the risk gate
        exists to stop new risk, not to trap the desk in an existing position.

        `mark_premium` is the structure's CURRENT net value, in the entry sign
        convention. The closing limit must come from it, not from the entry
        price: pricing the close off proposal.net_premium demanded entry+3%
        back on every exit, which a winner clears and a loser never can. That
        made the stop-loss decorative -- the one order it exists to send was,
        by construction, unfillable. Closing an asset (mark > 0) means selling
        it, so the close nets a credit of -mark; the usual concession is then
        applied so the order is marketable on today's market, whatever today
        looks like.
        """
        if mark_premium is not None and math.isfinite(mark_premium):
            limit_price = self._buffered(-mark_premium)
        else:
            # No usable mark. The entry price is wrong for any position that
            # has moved, but an exit attempt beats refusing to try. Negate
            # FIRST, then concede: -limit_price_for() negated after buffering,
            # which pushed the 3% in the desk's favour and produced an exit
            # priced not to fill -- the very defect this parameter fixed,
            # reintroduced in its own fallback.
            log.warning(
                "Closing %s without a current mark; falling back to the entry-derived limit",
                proposal.symbol,
            )
            limit_price = self._buffered(-proposal.net_premium)
        if client_order_id is None:
            client_order_id = f"deflow-x-{uuid.uuid4().hex[:22]}"

        if self.dry_run:
            # Every ENTRY route already refuses to submit under dry-run; the
            # REST close branch did not, so a rehearsal run could park a real,
            # untracked closing order on the live account. No route submits a
            # close in dry-run, uniformly.
            return ExecutionResult(
                submitted=False, dry_run=True, route=self.resolve_route(),
                proposal_id=proposal.proposal_id, symbol=proposal.symbol,
                strategy=proposal.strategy.value, contracts=proposal.contracts,
                limit_price=limit_price, client_order_id=client_order_id,
            )
        base = dict(
            route=self.resolve_route(),
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            strategy=proposal.strategy.value,
            contracts=proposal.contracts,
            limit_price=limit_price,
            client_order_id=client_order_id,
            dry_run=self.dry_run,
        )
        legs = self.legs_payload(proposal, closing=True)
        log.info("Closing %s (%s)", proposal.symbol, reason)

        route = base["route"]
        if route == "cli" and self.cli:
            result = self.cli.submit_mleg(
                legs=legs, quantity=proposal.contracts, limit_price=limit_price,
                client_order_id=client_order_id, dry_run=self.dry_run,
            )
            return ExecutionResult(
                submitted=result.ok, error="" if result.ok else result.stderr,
                order_id=str((result.data or {}).get("id", "")) if isinstance(result.data, dict) else "",
                request_body={"legs": legs}, **base,
            )
        if route == "rest" and self.rest:
            body = AlpacaClient.build_mleg_payload(
                legs=[{**l, "ratio": l["ratio_qty"]} for l in legs],
                quantity=proposal.contracts, limit_price=limit_price, closing=True,
            )
            result = self.rest.submit_mleg_order(body)
            return ExecutionResult(
                submitted=result.ok, error="" if result.ok else result.error,
                order_id=str((result.data or {}).get("id", "")) if isinstance(result.data, dict) else "",
                request_body=body, **base,
            )
        return ExecutionResult(
            submitted=True, simulated=True, order_id=f"sim-x-{uuid.uuid4().hex[:12]}",
            request_body={"legs": legs}, **base,
        )


__all__ = ["ExecutionAgent", "ExecutionResult", "SLIPPAGE_BUFFER"]
