"""Structure construction, the position book, the ledger, and the full desk.

The invariants asserted here are the ones a trading system cannot be wrong
about even once: a spread's stated risk must match its geometry, a mark must
stay inside the payoff bounds, and the audit trail must be tamper-evident.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from deflow.agents.analyst import MacroVolatilityAnalyst
from deflow.agents.auditor import AdversarialRiskAuditor
from deflow.agents.executor import ExecutionAgent
from deflow.agents.structurer import OptionsStructurer
from deflow.config import Settings
from deflow.desk import TradingDesk
from deflow.market import SimulatedMarketData, classify_regime
from deflow.models import Leg, OptionQuote, Regime, SpreadProposal, Strategy, occ_symbol
from deflow.portfolio import Portfolio
from risk_gate import DeterministicRiskGate, PortfolioState

EXPIRY = date.today() + timedelta(days=30)


def leg(right, strike, ratio, price, iv=0.20, half_spread=0.02):
    return Leg(occ_symbol("SPY", EXPIRY, right, strike), right, strike, EXPIRY, ratio, price, iv, half_spread)


# --------------------------------------------------------------------------
# Spread economics
# --------------------------------------------------------------------------

def test_bull_call_spread_economics():
    """450/460 for a 4.75 debit: risk the debit, make the width less the debit."""
    p = SpreadProposal("SPY", Strategy.BULL_CALL_SPREAD,
                       [leg("call", 450, +1, 9.10), leg("call", 460, -1, 4.35)],
                       contracts=4, underlying_price=452.0)
    assert p.net_debit == pytest.approx(4.75)
    assert p.max_loss == pytest.approx(1900.0)
    assert p.max_profit == pytest.approx(2100.0)
    assert p.breakevens() == [pytest.approx(454.75)]
    assert p.is_defined_risk


def test_bull_put_spread_economics():
    """530/525 for a 0.80 credit: keep the credit, risk width minus credit."""
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                       [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                       contracts=4, underlying_price=548.0)
    assert p.net_credit == pytest.approx(0.80)
    assert p.max_profit == pytest.approx(320.0)
    assert p.max_loss == pytest.approx(1680.0)
    assert p.breakevens() == [pytest.approx(529.20)]


def test_iron_condor_has_two_breakevens_and_one_width():
    """Only one side of a condor can be tested, so risk is one wing, not two."""
    p = SpreadProposal(
        "SPY", Strategy.IRON_CONDOR,
        [leg("put", 520, -1, 2.00), leg("put", 515, +1, 1.30),
         leg("call", 570, -1, 2.20), leg("call", 575, +1, 1.40)],
        contracts=2, underlying_price=548.0,
    )
    assert p.net_credit == pytest.approx(1.50)
    assert p.widest_wing == pytest.approx(5.0)
    assert p.max_loss == pytest.approx((5.0 - 1.50) * 100 * 2)
    assert len(p.breakevens()) == 2
    assert p.is_defined_risk


@pytest.mark.parametrize(
    "strategy,direction",
    [(Strategy.BULL_CALL_SPREAD, "bullish"), (Strategy.BULL_PUT_SPREAD, "bullish"),
     (Strategy.BEAR_PUT_SPREAD, "bearish"), (Strategy.BEAR_CALL_SPREAD, "bearish"),
     (Strategy.IRON_CONDOR, "neutral")],
)
def test_strategy_direction_mapping(strategy, direction):
    assert strategy.direction == direction


def test_credit_and_debit_classification_are_exclusive():
    for s in Strategy:
        assert s.is_credit != s.is_debit


def test_naked_short_is_not_defined_risk():
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD, [leg("put", 530, -1, 3.10)],
                       contracts=1, underlying_price=548.0)
    assert not p.is_defined_risk


def test_uncovered_right_is_not_defined_risk():
    """A long put does not cover a short call."""
    p = SpreadProposal("SPY", Strategy.IRON_CONDOR,
                       [leg("call", 570, -1, 2.20), leg("put", 515, +1, 1.30)],
                       contracts=1, underlying_price=548.0)
    assert not p.is_defined_risk


def test_risk_payload_reports_geometry_not_assertions():
    """The gate's inputs are derived from the legs, so they cannot be faked."""
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                       [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                       contracts=4, underlying_price=548.0)
    payload = p.to_risk_payload()
    assert payload["max_loss"] == p.max_loss
    assert payload["is_defined_risk_spread"] is True
    assert payload["leg_count"] == 2
    assert 0.0 <= payload["probability_of_profit"] <= 1.0


def test_net_delta_is_size_invariant():
    """Per-contract delta must be comparable to the gate's 0.35 bound at any size."""
    legs = [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)]
    one = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD, legs, 1, 548.0)
    ten = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD, legs, 10, 548.0)
    assert one.net_delta == pytest.approx(ten.net_delta, rel=1e-9)


# --------------------------------------------------------------------------
# Regime classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "iv_rank,trend,expected",
    [(0.8, 0.5, Regime.HIGH_VOL_BULL), (0.8, -0.5, Regime.HIGH_VOL_BEAR),
     (0.8, 0.0, Regime.HIGH_VOL_RANGE), (0.2, 0.5, Regime.LOW_VOL_BULL),
     (0.2, -0.5, Regime.LOW_VOL_BEAR), (0.2, 0.0, Regime.LOW_VOL_RANGE)],
)
def test_regime_grid(iv_rank, trend, expected):
    assert classify_regime(iv_rank, trend) == expected


# --------------------------------------------------------------------------
# Structurer
# --------------------------------------------------------------------------

@pytest.fixture
def provider():
    return SimulatedMarketData()


@pytest.fixture
def gate():
    return DeterministicRiskGate(100_000.0)


def test_structurer_builds_only_defined_risk_structures(provider, gate):
    """Whatever the market looks like, nothing naked may leave this agent."""
    structurer = OptionsStructurer(provider, gate)
    analyst = MacroVolatilityAnalyst(provider)
    flat = PortfolioState(equity=100_000.0)
    built = 0
    for symbol in ("SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMD", "TSLA"):
        view = analyst.analyse(symbol)
        if view is None or not view.tradeable:
            continue
        for candidate in structurer.build(view, flat):
            built += 1
            p = candidate.proposal
            assert p.is_defined_risk, f"{symbol}: naked structure escaped the structurer"
            assert p.max_loss > 0
            assert 2 <= len(p.legs) <= 4
            assert p.contracts >= 1
    assert built > 0, "simulated market produced no candidates at all"


def test_every_candidate_would_survive_its_own_risk_gate(provider, gate):
    """The structurer is gate-aware: it must not emit what the gate refuses."""
    structurer = OptionsStructurer(provider, gate)
    analyst = MacroVolatilityAnalyst(provider)
    flat = PortfolioState(equity=100_000.0)
    for symbol in ("NVDA", "MSFT", "AMD"):
        view = analyst.analyse(symbol)
        if view is None or not view.tradeable:
            continue
        for candidate in structurer.build(view, flat):
            verdict = gate.evaluate_trade(candidate.proposal.to_risk_payload(), flat)
            structural = [b for b in verdict.failed if b.id in (1, 2, 5, 6, 10)]
            assert not structural, (
                f"{symbol}: structurer emitted a candidate failing "
                f"{[b.name for b in structural]}"
            )


def test_wing_always_sits_beyond_the_short_leg(provider, gate):
    """The property that makes a spread defined-risk in the first place."""
    structurer = OptionsStructurer(provider, gate)
    analyst = MacroVolatilityAnalyst(provider)
    flat = PortfolioState(equity=100_000.0)
    for symbol in ("NVDA", "MSFT", "AMD", "SPY", "TSLA"):
        view = analyst.analyse(symbol)
        if view is None or not view.tradeable:
            continue
        for candidate in structurer.build(view, flat):
            for right in ("call", "put"):
                shorts = [l.strike for l in candidate.proposal.legs if l.right == right and l.ratio < 0]
                longs = [l.strike for l in candidate.proposal.legs if l.right == right and l.ratio > 0]
                for s in shorts:
                    assert longs, f"{symbol}: short {right} with no wing"
                    if right == "call":
                        assert max(longs) > s
                    else:
                        assert min(longs) < s


def test_structurer_declines_convexity_on_a_neutral_tape(provider, gate):
    analyst = MacroVolatilityAnalyst(provider)
    view = analyst.analyse("SPY")
    view.stance, view.bias = "buy_convexity", "neutral"
    assert OptionsStructurer.strategy_for(view) is None


@pytest.mark.parametrize(
    "stance,bias,expected",
    [("sell_premium", "bullish", Strategy.BULL_PUT_SPREAD),
     ("sell_premium", "bearish", Strategy.BEAR_CALL_SPREAD),
     ("sell_premium", "neutral", Strategy.IRON_CONDOR),
     ("buy_convexity", "bullish", Strategy.BULL_CALL_SPREAD),
     ("buy_convexity", "bearish", Strategy.BEAR_PUT_SPREAD),
     ("stand_down", "bullish", None)],
)
def test_strategy_selection_matrix(provider, stance, bias, expected):
    view = MacroVolatilityAnalyst(provider).analyse("SPY")
    view.stance, view.bias = stance, bias
    assert OptionsStructurer.strategy_for(view) == expected


# --------------------------------------------------------------------------
# Auditor
# --------------------------------------------------------------------------

def test_auditor_vetoes_a_structure_that_is_not_defined_risk():
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD, [leg("put", 530, -1, 3.10)],
                       contracts=1, underlying_price=548.0)
    report = AdversarialRiskAuditor(paths=300).audit(p, realised_vol=0.15)
    assert not report.passed
    assert any(o.code == "undefined_risk" for o in report.fatal)


def test_auditor_vetoes_negative_expectancy():
    """High win rate, negative mean -- the classic short-premium trap."""
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                       [leg("put", 545, -1, 0.20, 0.60), leg("put", 500, +1, 0.05, 0.60)],
                       contracts=1, underlying_price=548.0)
    report = AdversarialRiskAuditor(paths=800).audit(p, realised_vol=0.60)
    assert not report.passed
    assert any(o.code == "negative_expectancy" for o in report.fatal)


def test_auditor_reports_both_measures():
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                       [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                       contracts=4, underlying_price=548.0)
    report = AdversarialRiskAuditor(paths=500).audit(p, realised_vol=0.10)
    assert report.physical is not None and report.risk_neutral is not None
    # Realised vol well below implied must show a positive variance edge.
    assert report.variance_edge_usd > 0


def test_auditor_risk_payload_uses_simulated_win_rate():
    p = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                       [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                       contracts=4, underlying_price=548.0)
    report = AdversarialRiskAuditor(paths=500).audit(p, realised_vol=0.12)
    payload = AdversarialRiskAuditor.risk_payload(p, report)
    assert payload["probability_of_profit"] == report.physical.prob_profit


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------

def _spread(contracts=4):
    return SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                          [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                          contracts=contracts, underlying_price=548.0)


def test_portfolio_tracks_risk_and_exposure(gate):
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    pf.add(p)
    state = pf.state()
    assert state.open_positions == 1
    assert state.total_capital_at_risk == pytest.approx(p.max_loss)
    assert state.risk_by_symbol["SPY"] == pytest.approx(p.max_loss)


def test_mark_cannot_exceed_structural_bounds(gate):
    """A bad quote must not be able to manufacture P&L that geometry forbids."""
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    position = pf.add(p)
    # A wildly wrong quote on one leg only.
    bogus = OptionQuote(p.legs[0].symbol, 90.0, 92.0, 548.0, 530, "put", EXPIRY, 0.2, 500, 100)
    position.mark({bogus.symbol: bogus}, spot=548.0)
    assert -p.max_loss - 0.01 <= position.unrealized_pnl <= p.max_profit + 0.01
    assert position.mark_suspect


def test_mark_uses_the_current_spot_not_the_entry_spot(gate):
    """A missing quote must be modelled at today's price, not entry day's."""
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    position = pf.add(p)
    at_entry = position.mark({}, spot=548.0)
    crashed = position.mark({}, spot=505.0)
    assert crashed < at_entry, "a gap down must show a loss on a short put spread"


def test_exit_guard_fires_on_profit_target(gate):
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    position = pf.add(p)
    position.unrealized_pnl = p.max_profit * 0.80
    due = pf.exits_due()
    assert len(due) == 1 and "PROFIT TARGET" in due[0][1]


def test_exit_guard_fires_on_stop_loss(gate):
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    position = pf.add(p)
    position.unrealized_pnl = -p.max_loss * 0.60
    assert "STOP LOSS" in pf.exits_due()[0][1]


def test_closing_moves_unrealised_into_realised(gate):
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    pf.add(p).unrealized_pnl = 250.0
    closed = pf.close("p1", "test")
    assert closed.realized_pnl == 250.0
    assert pf.realized_pnl == 250.0
    assert pf.equity == pytest.approx(100_250.0)
    assert not pf.open


def test_profit_factor_is_none_rather_than_infinite(gate):
    pf = Portfolio(gate, 100_000.0)
    p = _spread()
    p.proposal_id = "p1"
    pf.add(p).unrealized_pnl = 100.0
    pf.close("p1", "win")
    assert pf.performance()["profit_factor"] is None


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

def test_ledger_chain_is_intact_when_untouched(tmp_path, monkeypatch):
    import deflow.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    ledger = ledger_module.DecisionLedger("t.jsonl")
    for i in range(10):
        ledger.append("proposal", {"i": i})
    status = ledger.verify()
    assert status.valid and status.entries == 10


def test_ledger_detects_a_modified_entry(tmp_path, monkeypatch):
    import deflow.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    ledger = ledger_module.DecisionLedger("t.jsonl")
    for i in range(6):
        ledger.append("proposal", {"i": i, "max_loss": 1000 + i})

    path = tmp_path / "t.jsonl"
    lines = path.read_text().splitlines()
    record = json.loads(lines[3])
    record["payload"]["max_loss"] = 99_999
    lines[3] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n")

    status = ledger_module.DecisionLedger("t.jsonl").verify()
    assert not status.valid and status.broken_at == 3


def test_ledger_detects_a_deleted_entry(tmp_path, monkeypatch):
    import deflow.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    ledger = ledger_module.DecisionLedger("t.jsonl")
    for i in range(6):
        ledger.append("proposal", {"i": i})

    path = tmp_path / "t.jsonl"
    lines = path.read_text().splitlines()
    del lines[2]
    path.write_text("\n".join(lines) + "\n")

    assert not ledger_module.DecisionLedger("t.jsonl").verify().valid


def test_ledger_resumes_the_chain_across_restarts(tmp_path, monkeypatch):
    import deflow.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    first = ledger_module.DecisionLedger("t.jsonl")
    first.append("a", {"x": 1})
    head = first.head

    second = ledger_module.DecisionLedger("t.jsonl")
    assert second.head == head
    second.append("b", {"x": 2})
    assert second.verify().valid


# --------------------------------------------------------------------------
# Executor
# --------------------------------------------------------------------------

def test_executor_refuses_an_unapproved_trade(gate):
    """Defence in depth: the gate runs again inside the executor."""
    pf = Portfolio(gate, 100_000.0)
    executor = ExecutionAgent(gate)
    oversized = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                               [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                               contracts=40, underlying_price=548.0)
    oversized.proposal_id = "big"
    result = executor.submit(oversized, pf.state())
    assert not result.submitted
    assert "risk gate refused" in result.error


def test_credit_spreads_submit_a_negative_limit_price():
    """Alpaca's net convention: positive is a debit, negative is a credit."""
    credit = SpreadProposal("SPY", Strategy.BULL_PUT_SPREAD,
                            [leg("put", 530, -1, 3.10), leg("put", 525, +1, 2.30)],
                            contracts=4, underlying_price=548.0)
    debit = SpreadProposal("SPY", Strategy.BULL_CALL_SPREAD,
                           [leg("call", 450, +1, 9.10), leg("call", 460, -1, 4.35)],
                           contracts=4, underlying_price=452.0)
    assert ExecutionAgent.limit_price_for(credit) < 0
    assert ExecutionAgent.limit_price_for(debit) > 0


def test_opening_legs_carry_opening_intents():
    p = _spread()
    legs = ExecutionAgent.legs_payload(p, closing=False)
    assert {l["position_intent"] for l in legs} == {"sell_to_open", "buy_to_open"}
    assert all(int(l["ratio_qty"]) > 0 for l in legs)


def test_closing_legs_reverse_side_and_intent():
    p = _spread()
    opening = {l["symbol"]: l for l in ExecutionAgent.legs_payload(p, closing=False)}
    closing = {l["symbol"]: l for l in ExecutionAgent.legs_payload(p, closing=True)}
    for symbol, leg_open in opening.items():
        assert closing[symbol]["side"] != leg_open["side"]
        assert closing[symbol]["position_intent"].endswith("_to_close")


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

@pytest.fixture
def desk(tmp_path, monkeypatch):
    import deflow.ledger as ledger_module
    import deflow.market as market_module

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(market_module, "DATA_DIR", tmp_path)
    import deflow.portfolio as portfolio_module

    monkeypatch.setattr(portfolio_module, "DATA_DIR", tmp_path)

    gate = DeterministicRiskGate(100_000.0)
    portfolio = Portfolio(gate, 100_000.0)
    settings = Settings()
    return TradingDesk(
        provider=SimulatedMarketData(),
        gate=gate,
        portfolio=portfolio,
        executor=ExecutionAgent(gate, preferred_route="paper"),
        ledger=ledger_module.DecisionLedger("e2e.jsonl"),
        settings=settings,
    )


def test_full_cycle_runs_without_error(desk):
    report = desk.run_cycle()
    assert len(report.outcomes) == len(desk.settings.universe)
    assert not report.errors


def test_every_symbol_reaches_a_terminal_stage(desk):
    valid = {"analyst", "structurer", "reasoning", "audit", "risk_gate", "execution", "error"}
    for outcome in desk.run_cycle().outcomes:
        assert outcome.stage in valid
        assert outcome.detail


def test_cycle_never_breaches_the_aggregate_risk_cap(desk):
    for _ in range(4):
        desk.run_cycle()
    performance = desk.portfolio.performance()
    assert performance["capital_at_risk_pct"] <= 6.01


def test_cycle_never_breaches_the_position_count_cap(desk):
    for _ in range(6):
        desk.run_cycle()
    assert desk.portfolio.performance()["open_positions"] <= 6


def test_every_filled_position_is_defined_risk(desk):
    for _ in range(4):
        desk.run_cycle()
    for position in desk.portfolio.open.values():
        assert position.proposal.is_defined_risk
        assert position.max_loss <= 2_000.0 + 0.01


def test_cycle_writes_an_intact_ledger(desk):
    desk.run_cycle()
    assert len(desk.ledger) > 0
    assert desk.ledger.verify().valid


def test_refusals_are_recorded_not_just_fills(desk):
    """A desk that only logs its trades cannot be audited."""
    desk.run_cycle()
    events = {r["event"] for r in desk.ledger.read()}
    assert "analyst_view" in events
    assert "cycle_start" in events and "cycle_end" in events


def test_status_is_json_serialisable(desk):
    desk.run_cycle()
    assert json.loads(json.dumps(desk.status(), default=str))["mode"] in {"paper", "simulation"}


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------

def test_dry_run_books_nothing(tmp_path, monkeypatch):
    """--dry-run must mean the same thing on every route.

    The CLI's own --dry-run prints the request body and exits 0; treating that
    success as a fill would book positions that do not exist at the broker.
    """
    import deflow.ledger as ledger_module
    import deflow.market as market_module
    import deflow.portfolio as portfolio_module

    for module in (ledger_module, market_module, portfolio_module):
        monkeypatch.setattr(module, "DATA_DIR", tmp_path)

    gate = DeterministicRiskGate(100_000.0)
    portfolio = Portfolio(gate, 100_000.0)
    desk = TradingDesk(
        provider=SimulatedMarketData(),
        gate=gate,
        portfolio=portfolio,
        executor=ExecutionAgent(gate, preferred_route="paper", dry_run=True),
        ledger=ledger_module.DecisionLedger("dry.jsonl"),
        settings=Settings(),
    )
    report = desk.run_cycle()

    reached_execution = [o for o in report.outcomes if o.stage == "execution"]
    assert reached_execution, "no proposal reached the execution stage to dry-run"
    assert report.orders_submitted == 0
    assert not portfolio.open
    assert portfolio.capital_at_risk == 0.0
    for outcome in reached_execution:
        assert outcome.execution["dry_run"] is True
        # A proposal the execution-time gate re-check refused never reaches the
        # point of rendering a request body, so only assert on the ones that did.
        if not outcome.execution["error"].startswith("Execution-time risk gate"):
            assert outcome.execution["request_body"]["legs"]


def test_dry_run_still_renders_a_complete_order(tmp_path, monkeypatch):
    import deflow.portfolio as portfolio_module

    monkeypatch.setattr(portfolio_module, "DATA_DIR", tmp_path)
    gate = DeterministicRiskGate(100_000.0)
    portfolio = Portfolio(gate, 100_000.0)
    executor = ExecutionAgent(gate, preferred_route="paper", dry_run=True)

    proposal = _spread()
    proposal.proposal_id = "dry1"
    result = executor.submit(proposal, portfolio.state())

    assert not result.submitted and result.dry_run
    legs = result.request_body["legs"]
    assert len(legs) == len(proposal.legs)
    assert {l["position_intent"] for l in legs} == {"sell_to_open", "buy_to_open"}


# --------------------------------------------------------------------------
# Breaker 4 is strategy-aware
# --------------------------------------------------------------------------

def _proposal(**kw):
    base = {
        "symbol": "SPY", "is_defined_risk_spread": True, "leg_count": 2,
        "contracts": 2, "net_delta": 0.20, "net_vega": 5.0, "dte": 30,
    }
    base.update(kw)
    return base


def _breaker(verdict, n):
    return next(b for b in verdict.breakers if b.id == n)


@pytest.mark.parametrize("pop,expected", [(0.78, True), (0.65, True), (0.649, False), (0.40, False)])
def test_credit_spreads_keep_the_65pct_win_rate_floor(gate, pop, expected):
    v = gate.evaluate_trade(
        _proposal(strategy="bull_put_spread", probability_of_profit=pop,
                  max_loss=1600.0, max_profit=400.0),
        PortfolioState(equity=100_000.0),
    )
    assert _breaker(v, 4).passed is expected


def test_debit_spread_with_positive_expectancy_is_allowed(gate):
    """A 45%-win-rate call spread paying 2:1 is a good trade, not a bad one."""
    v = gate.evaluate_trade(
        _proposal(strategy="bull_call_spread", probability_of_profit=0.45,
                  max_loss=1000.0, max_profit=2000.0),
        PortfolioState(equity=100_000.0),
    )
    assert _breaker(v, 4).passed


def test_debit_spread_with_negative_expectancy_is_refused(gate):
    """Same win rate, worse payoff: 0.45x900 < 0.55x1000."""
    v = gate.evaluate_trade(
        _proposal(strategy="bull_call_spread", probability_of_profit=0.45,
                  max_loss=1000.0, max_profit=900.0),
        PortfolioState(equity=100_000.0),
    )
    assert not _breaker(v, 4).passed


def test_debit_lottery_ticket_is_refused_despite_positive_expectancy(gate):
    """+$625 expected value, but it loses three times out of four."""
    v = gate.evaluate_trade(
        _proposal(strategy="bull_call_spread", probability_of_profit=0.25,
                  max_loss=500.0, max_profit=4000.0),
        PortfolioState(equity=100_000.0),
    )
    assert not _breaker(v, 4).passed


def test_debit_branch_still_fails_closed_on_missing_fields(gate):
    v = gate.evaluate_trade(
        _proposal(strategy="bull_call_spread", max_loss=1000.0),  # no pop, no max_profit
        PortfolioState(equity=100_000.0),
    )
    assert not _breaker(v, 4).passed


# --------------------------------------------------------------------------
# Jump-robust volatility
# --------------------------------------------------------------------------

def test_bipower_is_barely_moved_by_a_single_jump():
    """The MSFT case: one +14% earnings gap nearly doubled 60-day realised vol."""
    import math

    from deflow.indicators import bipower_vol, realized_vol

    calm = [100.0]
    for i in range(60):
        calm.append(calm[-1] * math.exp(0.004 * (1 if i % 2 else -1)))

    jumped = list(calm)
    jumped[30:] = [p * 1.14 for p in jumped[30:]]   # one gap, no change in daily noise

    plain_ratio = realized_vol(jumped, 60) / realized_vol(calm, 60)
    robust_ratio = bipower_vol(jumped, 60) / bipower_vol(calm, 60)
    assert plain_ratio > 3.0, "the naive estimator should be badly distorted"
    assert robust_ratio < plain_ratio / 2, "bipower should absorb most of the jump"


def test_forecast_vol_falls_back_on_short_history():
    from deflow.indicators import forecast_vol

    assert forecast_vol([100.0, 101.0]) == 0.0
    assert forecast_vol([]) == 0.0


def test_snapshot_measures_variance_premium_against_the_forecast():
    provider = SimulatedMarketData()
    snap = provider.snapshot("SPY")
    assert snap.hv_forecast > 0
    assert snap.variance_premium == pytest.approx(snap.iv_30d - snap.hv_forecast, abs=1e-9)


def test_ledger_survives_concurrent_writers(tmp_path, monkeypatch):
    """Two Deflow processes sharing a data directory must not fork the chain.

    An in-memory head is correct only while exactly one process is running.
    A stray background server, a --once run beside a live one, or a deployment
    scaled to two replicas all interleave appends, and every record after the
    collision points at a predecessor that is no longer its neighbour.
    """
    import subprocess
    import sys as _sys

    import deflow.ledger as ledger_module

    worker = (
        "import sys; sys.path.insert(0, %r)\n"
        "import deflow.ledger as L\n"
        "L.DATA_DIR = __import__('pathlib').Path(%r)\n"
        "led = L.DecisionLedger('concurrent.jsonl')\n"
        "[led.append('probe', {'w': sys.argv[1], 'i': i}) for i in range(40)]\n"
        % (str(Path(__file__).resolve().parent.parent), str(tmp_path))
    )
    procs = [subprocess.Popen([_sys.executable, "-c", worker, str(w)]) for w in range(3)]
    for proc in procs:
        assert proc.wait() == 0

    monkeypatch.setattr(ledger_module, "DATA_DIR", tmp_path)
    status = ledger_module.DecisionLedger("concurrent.jsonl").verify()
    assert status.valid, status.detail
    assert status.entries == 120, f"expected 120 appends, chain has {status.entries}"
