"""Client for Alpaca's official MCP server (`alpaca-mcp-server`, FastMCP v2).

The hackathon asks projects to use Alpaca's MCP server or CLI. Deflow uses
both, for different jobs:

    CLI  -> order routing and cron-driven position management (deterministic,
            retryable, auditable via --dry-run)
    MCP  -> structured *discovery*: option chains, contract metadata and
            account state exposed as typed tools

This speaks MCP's JSON-RPC 2.0 over stdio directly rather than pulling in an
SDK. The protocol surface Deflow needs is three calls -- `initialize`,
`tools/list`, `tools/call` -- and implementing them here keeps the dependency
footprint of a trading system that must start reliably down to httpx.

The server is launched with `uvx alpaca-mcp-server` and inherits credentials
through the environment, with paper trading pinned on.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import ROOT, SETTINGS, Settings

log = logging.getLogger("deflow.mcp")

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class McpResult:
    ok: bool
    data: Any = None
    error: str = ""

    def __bool__(self) -> bool:
        return self.ok


class AlpacaMCPClient:
    """Minimal MCP stdio client scoped to what the desk actually calls.

    Lifecycle is explicit (`start` / `stop`) and the class is a context
    manager, because an orphaned MCP subprocess holding a trading session open
    is not an acceptable failure mode.
    """

    def __init__(self, settings: Settings = SETTINGS, timeout: float = 60.0) -> None:
        self.settings = settings
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen] = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: List[Dict[str, Any]] = []
        self.server_info: Dict[str, Any] = {}

    # -- launch -------------------------------------------------------------

    def _command(self) -> Optional[List[str]]:
        if self.settings.mcp_command:
            return self.settings.mcp_command.split()
        # uv is installed privately alongside the application by the deployment
        # script, for the same reason the Alpaca CLI is: not shadowing a system
        # binary on a shared host. That directory is not on PATH for a manual
        # invocation, so look there before giving up.
        local_uvx = ROOT / "bin" / "uvx"
        if local_uvx.exists() and os.access(local_uvx, os.X_OK):
            return [str(local_uvx), "--with", "fastmcp>=3.1,<4", "alpaca-mcp-server"]
        if shutil.which("uvx"):
            # The fastmcp pin is load-bearing. alpaca-mcp-server 2.3.0 declares
            # `fastmcp>=3.1.0` with no upper bound, so a fresh `uvx
            # alpaca-mcp-server` resolves fastmcp 4.x, which moved
            # `fastmcp.tools.tool` and makes the server die on import before it
            # emits a single byte. Pinning to the 3.x line is what makes this
            # integration actually start. Override with DEFLOW_MCP_COMMAND once
            # upstream constrains it.
            return ["uvx", "--with", "fastmcp>=3.1,<4", "alpaca-mcp-server"]
        if shutil.which("alpaca-mcp-server"):
            return ["alpaca-mcp-server"]
        return None

    @property
    def available(self) -> bool:
        return self._command() is not None and self.settings.has_alpaca_credentials

    def install_hint(self) -> str:
        return (
            "Alpaca MCP server not found. Install uv, then it runs on demand:\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "  uvx alpaca-mcp-server        # launched automatically by Deflow"
        )

    def start(self) -> McpResult:
        command = self._command()
        if command is None:
            return McpResult(False, error=self.install_hint())
        if not self.settings.has_alpaca_credentials:
            return McpResult(False, error="MCP server needs Alpaca credentials")

        env = os.environ.copy()
        env["ALPACA_API_KEY"] = self.settings.alpaca_key
        env["ALPACA_SECRET_KEY"] = self.settings.alpaca_secret
        env["ALPACA_PAPER_TRADE"] = "true"   # never live, regardless of inherited env

        try:
            self.proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                # Run from the application directory, not whatever directory the
                # caller happened to be in. alpaca-mcp-server reads settings
                # through pydantic-settings, which resolves `.env` RELATIVE to
                # the working directory -- so launching `--check` from /root as
                # the service user made it try to read /root/.env and die with
                # a bare PermissionError before emitting a single byte.
                cwd=str(ROOT),
            )
        except OSError as exc:
            return McpResult(False, error=f"could not launch MCP server: {exc}")

        init = self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "deflow", "version": "1.0.0"},
            },
        )
        if not init.ok:
            # A server that dies on import says why on stderr. Reporting only
            # "closed the connection" turns a one-line diagnosis into a hunt.
            detail = ""
            if self.proc is not None and self.proc.stderr is not None:
                try:
                    self.proc.stderr.flush()
                    detail = (self.proc.stderr.read() or "").strip().splitlines()[-1:] or [""]
                    detail = detail[0][:200]
                except Exception:
                    detail = ""
            self.stop()
            return McpResult(False, error=f"{init.error}{' — ' + detail if detail else ''}")
        self.server_info = (init.data or {}).get("serverInfo", {})
        self._notify("notifications/initialized")

        listed = self._call("tools/list", {})
        if listed.ok:
            self.tools = (listed.data or {}).get("tools", [])
        return McpResult(True, data={"server": self.server_info, "tools": len(self.tools)})

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            self.proc.kill()
        finally:
            self.proc = None

    def __enter__(self) -> AlpacaMCPClient:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # -- JSON-RPC -----------------------------------------------------------

    def _write(self, message: Dict[str, Any]) -> bool:
        if self.proc is None or self.proc.stdin is None:
            return False
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError) as exc:
            log.warning("MCP write failed: %s", exc)
            return False

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _call(self, method: str, params: Dict[str, Any]) -> McpResult:
        if self.proc is None or self.proc.stdout is None:
            return McpResult(False, error="MCP server not running")

        with self._lock:
            self._id += 1
            request_id = self._id
            if not self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}):
                return McpResult(False, error="MCP server stdin closed")

            # Read until the matching id arrives; skip server-initiated
            # notifications and any non-JSON banner lines.
            for _ in range(200):
                line = self.proc.stdout.readline()
                if not line:
                    return McpResult(False, error="MCP server closed the connection")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    return McpResult(False, error=str(message["error"]))
                return McpResult(True, data=message.get("result"))
            return McpResult(False, error="no matching MCP response")

    # -- tools --------------------------------------------------------------

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> McpResult:
        """Invoke one MCP tool and unwrap its content block."""
        result = self._call("tools/call", {"name": name, "arguments": arguments or {}})
        if not result.ok:
            return result

        payload = result.data or {}
        if payload.get("isError"):
            return McpResult(False, error=str(payload.get("content", "tool reported an error")))

        # FastMCP returns a list of content blocks; the useful one is text,
        # which is itself usually JSON.
        for block in payload.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return McpResult(True, data=json.loads(text))
                except json.JSONDecodeError:
                    return McpResult(True, data=text)
        return McpResult(True, data=payload.get("structuredContent", payload))

    def tool_names(self) -> List[str]:
        return [t.get("name", "") for t in self.tools]

    def find_tool(self, *keywords: str) -> Optional[str]:
        """Locate a tool by keyword.

        The MCP server generates its tool names from Alpaca's OpenAPI specs and
        renames them between releases, so Deflow discovers the right tool at
        runtime rather than hard-coding a name that a server update would break.
        """
        for name in self.tool_names():
            lowered = name.lower()
            if all(k.lower() in lowered for k in keywords):
                return name
        return None

    # -- convenience wrappers ------------------------------------------------

    def get_account(self) -> McpResult:
        tool = self.find_tool("account")
        if not tool:
            return McpResult(False, error="no account tool exposed by this MCP server")
        return self.call_tool(tool, {})

    def get_option_chain(self, underlying: str, **kwargs: Any) -> McpResult:
        tool = self.find_tool("option", "chain") or self.find_tool("option", "snapshot")
        if not tool:
            return McpResult(False, error="no option chain tool exposed by this MCP server")
        return self.call_tool(tool, {"underlying_symbol": underlying.upper(), **kwargs})

    def get_option_contracts(self, underlying: str, **kwargs: Any) -> McpResult:
        tool = self.find_tool("option", "contract")
        if not tool:
            return McpResult(False, error="no option contract tool exposed by this MCP server")
        return self.call_tool(tool, {"underlying_symbols": underlying.upper(), **kwargs})

    def describe(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "running": self.proc is not None,
            "server": self.server_info,
            "tool_count": len(self.tools),
            "tools": self.tool_names()[:40],
        }


__all__ = ["AlpacaMCPClient", "McpResult"]
