"""Deflow runtime configuration.

Every knob is read once, at import, from the environment (optionally via .env).
Nothing here reaches out to the network -- config must be importable in any
context, including the deterministic risk-gate unit tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _load_dotenv() -> None:
    """Populate os.environ from .env without requiring python-dotenv."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment always wins over the file.
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# Placeholder credentials shipped in .env.example must never be treated as live.
_PLACEHOLDER_MARKERS = ("XXXX", "xxxx", "your_", "YOUR_", "changeme")


def _is_placeholder(value: str) -> bool:
    return (not value) or any(marker in value for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of Deflow's runtime configuration."""

    # --- Alpaca credentials -------------------------------------------------
    # `ALPACA_API_KEY` is what Alpaca's official CLI and MCP server both read,
    # so it is the primary name here; the older `*_API_KEY_ID` / `APCA_*` forms
    # used by alpaca-py and the REST docs are accepted as aliases.
    alpaca_key: str = field(
        default_factory=lambda: _env("ALPACA_API_KEY", "ALPACA_API_KEY_ID", "APCA_API_KEY_ID")
    )
    alpaca_secret: str = field(
        default_factory=lambda: _env("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
    )
    trading_base_url: str = field(
        default_factory=lambda: _env(
            "ALPACA_PAPER_BASE_URL", "APCA_API_BASE_URL", default="https://paper-api.alpaca.markets"
        ).rstrip("/")
    )
    data_base_url: str = field(
        default_factory=lambda: _env("ALPACA_DATA_BASE_URL", default="https://data.alpaca.markets").rstrip("/")
    )

    # --- Featherless AI (hackathon technology partner) ----------------------
    featherless_key: str = field(default_factory=lambda: _env("FEATHERLESS_API_KEY"))
    featherless_base_url: str = field(
        default_factory=lambda: _env("FEATHERLESS_BASE_URL", default="https://api.featherless.ai/v1").rstrip("/")
    )
    featherless_model: str = field(
        default_factory=lambda: _env("FEATHERLESS_MODEL", default="Qwen/Qwen2.5-72B-Instruct")
    )

    # --- Universe & cadence -------------------------------------------------
    universe: List[str] = field(
        default_factory=lambda: [
            s.strip().upper()
            for s in _env(
                "DEFLOW_UNIVERSE",
                # Deep, liquid option chains only. A defined-risk desk lives or
                # dies on being able to exit, so the universe is chosen for
                # penny-wide markets rather than for interesting stories.
                default="SPY,QQQ,IWM,NVDA,AAPL,MSFT,AMD,TSLA",
            ).split(",")
            if s.strip()
        ]
    )
    cycle_seconds: int = field(default_factory=lambda: _int("DEFLOW_CYCLE_SECONDS", 300))
    api_host: str = field(default_factory=lambda: _env("DEFLOW_HOST", default="127.0.0.1"))
    api_port: int = field(default_factory=lambda: _int("DEFLOW_PORT", 8000))

    # --- Risk envelope (mirrored into risk_gate.py constants) ---------------
    starting_equity: float = field(default_factory=lambda: _float("DEFLOW_STARTING_EQUITY", 100_000.0))
    max_risk_pct: float = field(default_factory=lambda: _float("DEFLOW_MAX_RISK_PCT", 0.02))
    max_net_delta: float = field(default_factory=lambda: _float("DEFLOW_MAX_NET_DELTA", 0.35))
    max_open_positions: int = field(default_factory=lambda: _int("DEFLOW_MAX_OPEN_POSITIONS", 6))
    max_concurrent_per_symbol: int = field(default_factory=lambda: _int("DEFLOW_MAX_PER_SYMBOL", 2))

    # --- Execution routing --------------------------------------------------
    execution_route: str = field(default_factory=lambda: _env("DEFLOW_EXECUTION_ROUTE", default="auto").lower())
    alpaca_cli_bin: str = field(default_factory=lambda: _env("DEFLOW_ALPACA_CLI", default="alpaca"))
    mcp_command: str = field(default_factory=lambda: _env("DEFLOW_MCP_COMMAND", default=""))
    dry_run: bool = field(default_factory=lambda: _bool("DEFLOW_DRY_RUN", False))

    @property
    def has_alpaca_credentials(self) -> bool:
        return not _is_placeholder(self.alpaca_key) and not _is_placeholder(self.alpaca_secret)

    @property
    def has_featherless(self) -> bool:
        return not _is_placeholder(self.featherless_key)

    @property
    def mode(self) -> str:
        """'paper' when Alpaca credentials exist, otherwise 'simulation'."""
        return "paper" if self.has_alpaca_credentials else "simulation"

    @property
    def is_paper_endpoint(self) -> bool:
        """Hard guarantee we are never pointed at Alpaca live trading."""
        return "paper-api" in self.trading_base_url


SETTINGS = Settings()

__all__ = ["Settings", "SETTINGS", "ROOT", "DATA_DIR"]
