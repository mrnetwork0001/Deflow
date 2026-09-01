"""Bridge to Alpaca's official CLI (`github.com/alpacahq/cli`, binary `alpaca`).

The hackathon requires a project to use Alpaca's MCP server *or* its CLI.
Deflow uses both, and this is the CLI half: the executor's default order route
and the mechanism behind headless cron operation.

Why route orders through a subprocess at all, when `alpaca_rest.py` could POST
the same JSON? Because the CLI is the interface an unattended agent actually
gets deployed behind -- it carries its own retry/backoff on 429s and 5xx, its
own credential resolution, and a `--dry-run` that renders the exact request
body without sending it. That last one means Deflow can prove what it *would*
have submitted, which is the difference between an auditable desk and a
plausible one.

Verified against CLI v0.0.14:
  * multi-leg orders are first-class: `--order-class mleg --legs '<json>'`
  * JSON on stdout, JSON errors on stderr
  * exit codes: 0 success, 1 API/general error, 2 auth error
  * credentials come from ALPACA_API_KEY / ALPACA_SECRET_KEY; paper is the
    default and live requires ALPACA_LIVE_TRADE=true, which Deflow never sets.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .config import ROOT, SETTINGS, Settings

log = logging.getLogger("deflow.cli")

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_AUTH_ERROR = 2


@dataclass
class CliResult:
    """Outcome of one CLI invocation."""

    ok: bool
    data: Any = None
    stderr: str = ""
    exit_code: int = 0
    command: List[str] = field(default_factory=list)

    @property
    def auth_failed(self) -> bool:
        return self.exit_code == EXIT_AUTH_ERROR

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "command": " ".join(self.command),
            "stderr": self.stderr[:400],
        }


class AlpacaCLI:
    """Subprocess wrapper around the `alpaca` binary."""

    def __init__(self, settings: Settings = SETTINGS, timeout: float = 45.0) -> None:
        self.settings = settings
        self.timeout = timeout
        self.binary = self._resolve_binary(settings.alpaca_cli_bin)
        self.invocations = 0

    # -- discovery ----------------------------------------------------------

    @staticmethod
    def _resolve_binary(preferred: str) -> Optional[str]:
        """Find the `alpaca` binary.

        PATH alone is not enough. The deployment installs the CLI privately
        into the project's own `bin/` -- deliberately, so it cannot shadow a
        system binary on a shared host -- and that directory is on PATH only
        for the systemd unit. Anyone running a command by hand, `--check`
        included, would otherwise be told the CLI is missing while it sits
        beside the code. `go install` has the same problem with GOPATH, which
        a GUI-launched shell routinely omits.
        """
        found = shutil.which(preferred)
        if found:
            return found

        candidates = [
            # Installed by deploy/install-safe.sh, next to the application.
            ROOT / "bin" / "alpaca",
            Path.home() / "go" / "bin" / "alpaca",
            Path("/opt/homebrew/bin/alpaca"),
            Path("/usr/local/bin/alpaca"),
        ]
        gopath = os.environ.get("GOPATH")
        if gopath:
            candidates.insert(0, Path(gopath) / "bin" / "alpaca")
        for path in candidates:
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        return None

    @property
    def available(self) -> bool:
        return self.binary is not None

    def version(self) -> str:
        if not self.available:
            return ""
        result = self._run(["version"], parse_json=False)
        return str(result.data or "").strip()

    def install_hint(self) -> str:
        return (
            "Alpaca CLI not found. Install it with:\n"
            "  go install github.com/alpacahq/cli/cmd/alpaca@latest\n"
            "  # or: brew install alpacahq/tap/cli"
        )

    # -- plumbing -----------------------------------------------------------

    def _env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["ALPACA_API_KEY"] = self.settings.alpaca_key
        env["ALPACA_SECRET_KEY"] = self.settings.alpaca_secret
        # Belt and braces: the CLI defaults to paper, and Deflow pins it there
        # explicitly so no inherited environment can flip the route to live.
        env["ALPACA_LIVE_TRADE"] = "false"
        env["ALPACA_QUIET"] = "true"
        return env

    def _run(self, args: Sequence[str], parse_json: bool = True) -> CliResult:
        if not self.available:
            return CliResult(False, stderr=self.install_hint(), exit_code=127, command=list(args))

        cmd = [self.binary, *args]
        self.invocations += 1
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CliResult(False, stderr=f"timed out after {self.timeout}s", exit_code=124, command=cmd)
        except OSError as exc:
            return CliResult(False, stderr=str(exc), exit_code=126, command=cmd)

        # Redact the binary path in the recorded command so audit logs stay portable.
        recorded = ["alpaca", *args]

        if proc.returncode != EXIT_OK:
            detail = proc.stderr.strip() or proc.stdout.strip()
            log.warning("alpaca %s -> exit %s: %s", " ".join(args), proc.returncode, detail[:200])
            return CliResult(False, stderr=detail, exit_code=proc.returncode, command=recorded)

        if not parse_json:
            return CliResult(True, data=proc.stdout, exit_code=0, command=recorded)

        try:
            return CliResult(True, data=json.loads(proc.stdout or "null"), exit_code=0, command=recorded)
        except json.JSONDecodeError:
            return CliResult(True, data=proc.stdout.strip(), exit_code=0, command=recorded)

    # -- read commands ------------------------------------------------------

    def account(self) -> CliResult:
        return self._run(["account", "get"])

    def clock(self) -> CliResult:
        return self._run(["clock"])

    def positions(self) -> CliResult:
        return self._run(["position", "list"])

    def orders(self, status: str = "open", limit: int = 100) -> CliResult:
        return self._run(["order", "list", "--status", status, "--limit", str(limit)])

    def option_chain(self, underlying: str) -> CliResult:
        return self._run(["data", "option", "chain", "--underlying-symbol", underlying.upper()])

    def option_snapshot(self, symbols: Sequence[str]) -> CliResult:
        return self._run(["data", "option", "snapshot", "--symbols", ",".join(symbols)])

    def doctor(self) -> CliResult:
        return self._run(["doctor"], parse_json=False)

    # -- order routing ------------------------------------------------------

    def submit_mleg(
        self,
        legs: Sequence[Dict[str, Any]],
        quantity: int,
        limit_price: float,
        time_in_force: str = "day",
        client_order_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> CliResult:
        """Submit a multi-leg options order.

        `client_order_id` is always sent. If a submission fails ambiguously --
        a timeout after the request left the machine, say -- a retry with the
        same id is rejected by Alpaca as a duplicate instead of opening a
        second position. For an unattended desk that is the difference between
        a retry and a doubled book.

        `limit_price` follows Alpaca's net convention: positive is a debit,
        negative is a credit.
        """
        if not 2 <= len(legs) <= 4:
            return CliResult(False, stderr=f"mleg orders take 2-4 legs, got {len(legs)}", exit_code=1)

        payload_legs = [
            {
                "symbol": leg["symbol"],
                "ratio_qty": str(abs(int(leg.get("ratio_qty", leg.get("ratio", 1))))),
                "side": leg["side"],
                "position_intent": leg["position_intent"],
            }
            for leg in legs
        ]
        args = [
            "order", "submit",
            "--order-class", "mleg",
            "--qty", str(int(quantity)),
            "--type", "limit",
            "--time-in-force", time_in_force,
            "--limit-price", f"{limit_price:.2f}",
            "--legs", json.dumps(payload_legs, separators=(",", ":")),
            "--client-order-id", client_order_id or f"deflow-{uuid.uuid4().hex[:24]}",
        ]
        if dry_run:
            args.append("--dry-run")
        return self._run(args)

    def cancel_order(self, order_id: str) -> CliResult:
        return self._run(["order", "cancel", order_id])

    def raw_api(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> CliResult:
        """`alpaca api <METHOD> <path>` escape hatch for endpoints without a
        dedicated subcommand. Body is piped in on stdin, as the CLI expects."""
        if not self.available:
            return CliResult(False, stderr=self.install_hint(), exit_code=127)
        cmd = [self.binary, "api", method.upper(), path]
        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(body) if body else None,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._env(),
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return CliResult(False, stderr=str(exc), exit_code=1, command=["alpaca", "api", method, path])
        recorded = ["alpaca", "api", method.upper(), path]
        if proc.returncode != EXIT_OK:
            return CliResult(False, stderr=proc.stderr.strip(), exit_code=proc.returncode, command=recorded)
        try:
            return CliResult(True, data=json.loads(proc.stdout or "null"), command=recorded)
        except json.JSONDecodeError:
            return CliResult(True, data=proc.stdout, command=recorded)


__all__ = ["AlpacaCLI", "CliResult"]
