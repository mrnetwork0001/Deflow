"""Featherless AI inference client (OpenAI-compatible chat completions).

The contract between Deflow and any language model is deliberately narrow:

    The model never produces a number that reaches the broker.

Strikes, widths, premiums, Greeks, position size and every risk figure are
computed by `deflow.structurer` and `deflow.greeks` from live quotes. What the
model does is *choose among candidates that already exist* and explain the
choice in English. Its entire output surface is one integer index, one
confidence float, and one paragraph of prose -- and the index is bounds-checked
before it is used.

That is why a total model failure (no key, timeout, garbage JSON, an index of
9999) degrades to a documented deterministic ranking rather than to a bad
trade.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from .config import SETTINGS, Settings

log = logging.getLogger("deflow.llm")


@dataclass
class LLMChoice:
    """A model's selection among pre-built candidates."""

    index: int                     # -1 means "abstain / no trade"
    confidence: float              # 0.0 - 1.0
    rationale: str
    model: str = "deterministic"
    used_llm: bool = False
    raw: str = ""
    error: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "model": self.model,
            "used_llm": self.used_llm,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 1),
        }


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of a model response.

    Open-weight models routinely wrap JSON in prose or a ```json fence even
    when told not to, so parsing is done defensively rather than optimistically.
    """
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} block.
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class FeatherlessClient:
    """Serverless open-model inference for the desk's reasoning layer."""

    def __init__(
        self,
        settings: Settings = SETTINGS,
        timeout: float = 45.0,
        enabled: Optional[bool] = None,
    ) -> None:
        """`enabled=False` forces the deterministic path regardless of config.

        Tests need this. Without it, merely having a working key in .env makes
        the whole suite reach across the network on every simulated cycle --
        slow, flaky, dependent on a third party, and quietly spending the
        hackathon's inference credits to assert things that have nothing to do
        with the model.
        """
        self.settings = settings
        self.model = settings.featherless_model
        self.enabled = settings.has_featherless if enabled is None else bool(enabled)
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {settings.featherless_key}",
                "Content-Type": "application/json",
            },
        )
        self.calls = 0
        self.failures = 0

    def close(self) -> None:
        self._client.close()

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> tuple[str, str]:
        """Return `(content, error)`. Never raises into the trading loop."""
        if not self.enabled:
            return "", "FEATHERLESS_API_KEY not configured"

        self.calls += 1
        try:
            resp = self._client.post(
                f"{self.settings.featherless_base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    # Low but non-zero: the desk wants a stable selection, not
                    # a creative one.
                    "temperature": temperature,
                },
            )
        except httpx.HTTPError as exc:
            self.failures += 1
            return "", f"transport: {exc}"

        if resp.status_code >= 400:
            self.failures += 1
            return "", f"http {resp.status_code}: {resp.text[:200]}"

        try:
            payload = resp.json()
            return payload["choices"][0]["message"]["content"], ""
        except (KeyError, IndexError, ValueError) as exc:
            self.failures += 1
            return "", f"malformed response: {exc}"


SELECTION_SYSTEM = """You are the portfolio manager of an autonomous options desk.

You are shown option spreads that have ALREADY been constructed and priced from \
live market quotes by deterministic code. Every number you see -- strikes, \
premiums, Greeks, max loss, probability of profit, Monte Carlo results -- was \
computed, not estimated. You cannot change any of them.

Your only job is to choose which single candidate best fits the stated market \
regime, or to abstain. You are explicitly expected to abstain when nothing on \
the list is compelling; a skipped cycle costs nothing.

Prefer, in order:
1. Positive Monte Carlo expected value. A high probability of profit with \
negative expected value is a trap -- reject it.
2. Alignment between the structure's direction and the measured regime.
3. Wider tails covered: shallower CVaR relative to max loss.
4. Tighter bid/ask, higher open interest.

Respond with ONLY a JSON object, no prose outside it:
{"index": <integer index of your choice, or -1 to abstain>,
 "confidence": <float 0.0-1.0>,
 "rationale": "<two sentences explaining the choice in trader's terms>"}"""


class ReasoningEngine:
    """Wraps the model with a deterministic fallback ranking.

    `select` always returns a usable `LLMChoice`. When the model is
    unavailable or misbehaves, `fallback_index` -- the top candidate under the
    desk's own deterministic score -- is used instead, and the result is
    flagged `used_llm=False` so the audit log records exactly which brain made
    the call.
    """

    def __init__(
        self,
        client: Optional[FeatherlessClient] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.client = client or FeatherlessClient(enabled=enabled)

    @property
    def enabled(self) -> bool:
        return self.client.enabled

    def select(
        self,
        regime_brief: str,
        candidates: List[Dict[str, Any]],
        fallback_index: int = 0,
        fallback_reason: str = "",
    ) -> LLMChoice:
        import time

        if not candidates:
            return LLMChoice(-1, 0.0, "No candidates survived structural screening.", used_llm=False)

        deterministic = LLMChoice(
            index=fallback_index,
            confidence=0.55,
            rationale=fallback_reason or "Top-ranked candidate under the deterministic composite score.",
            model="deterministic-ranker",
            used_llm=False,
        )

        if not self.client.enabled:
            deterministic.error = "Featherless disabled (no API key); using deterministic ranker."
            return deterministic

        prompt = (
            f"MARKET REGIME\n{regime_brief}\n\n"
            f"CANDIDATE SPREADS ({len(candidates)})\n"
            f"{json.dumps(candidates, indent=1, default=str)}\n\n"
            f"Choose one index in [0, {len(candidates) - 1}] or -1 to abstain."
        )

        t0 = time.perf_counter()
        content, error = self.client.complete(SELECTION_SYSTEM, prompt)
        elapsed = (time.perf_counter() - t0) * 1000.0

        if error:
            deterministic.error = error
            deterministic.latency_ms = elapsed
            log.warning("Featherless call failed (%s); falling back to deterministic ranker.", error)
            return deterministic

        parsed = _extract_json(content)
        if not parsed or "index" not in parsed:
            deterministic.error = "model returned unparseable JSON"
            deterministic.raw = content[:400]
            deterministic.latency_ms = elapsed
            return deterministic

        try:
            index = int(parsed["index"])
        except (TypeError, ValueError):
            deterministic.error = f"non-integer index: {parsed.get('index')!r}"
            deterministic.latency_ms = elapsed
            return deterministic

        # Bounds check. A model that hallucinates index 9999 gets ignored,
        # not indexed with.
        if index != -1 and not (0 <= index < len(candidates)):
            deterministic.error = f"index {index} out of range 0..{len(candidates) - 1}"
            deterministic.latency_ms = elapsed
            return deterministic

        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5

        return LLMChoice(
            index=index,
            confidence=confidence,
            rationale=str(parsed.get("rationale", ""))[:600] or "(model returned no rationale)",
            model=self.client.model,
            used_llm=True,
            raw=content[:400],
            latency_ms=elapsed,
        )

    def narrate(self, system: str, user: str, fallback: str) -> str:
        """Free-text commentary. Cosmetic only -- never parsed for decisions."""
        if not self.client.enabled:
            return fallback
        content, error = self.client.complete(system, user, max_tokens=320, temperature=0.35)
        return content.strip() if content and not error else fallback


__all__ = ["FeatherlessClient", "LLMChoice", "ReasoningEngine", "SELECTION_SYSTEM"]
