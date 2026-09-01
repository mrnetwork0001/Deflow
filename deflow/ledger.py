"""Append-only, hash-chained decision ledger.

Every decision the desk makes -- each analyst view, each proposal, each audit,
each gate verdict, each order, each exit -- is appended here as one JSON line.

Each record carries the SHA-256 of the record before it. Editing or deleting
any historical entry breaks the chain from that point forward, and `verify()`
reports the exact index where it broke. That is the difference between a log
and an audit trail: a log tells you what a system says it did, an audit trail
lets a third party check whether the story was edited afterwards.

For a trading competition judged on P&L, this is the artefact that makes the
claimed results checkable rather than assertable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from .config import DATA_DIR

try:  # POSIX only; Windows falls back to thread-level locking alone.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("deflow.ledger")

# How far back to read when recovering the chain head. One record is well under
# 8 KB, so this always spans the final line.
_TAIL_BYTES = 1 << 16

GENESIS_HASH = "0" * 64


def _canonical(payload: Dict[str, Any]) -> str:
    """Deterministic serialisation, so the same record always hashes the same."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def hash_record(prev_hash: str, body: Dict[str, Any]) -> str:
    return hashlib.sha256(f"{prev_hash}{_canonical(body)}".encode()).hexdigest()


@dataclass
class ChainStatus:
    valid: bool
    entries: int
    head: str
    broken_at: Optional[int] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "entries": self.entries,
            "head": self.head,
            "broken_at": self.broken_at,
            "detail": self.detail,
        }


class DecisionLedger:
    """Thread-safe append-only JSONL ledger with a SHA-256 chain."""

    def __init__(self, filename: str = "ledger.jsonl") -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = DATA_DIR / filename
        self._lock = threading.Lock()
        self._head = GENESIS_HASH
        self._count = 0
        self._recover_head()

    def _recover_head(self) -> None:
        """Resume the chain from an existing file so restarts do not fork it."""
        if not self.path.exists():
            return
        try:
            with self.path.open("r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._head = record.get("hash", self._head)
                    self._count += 1
        except OSError as exc:
            log.warning("Could not read ledger at %s: %s", self.path, exc)

    # -- writing ------------------------------------------------------------

    @staticmethod
    def _tail_record(fh) -> Optional[Dict[str, Any]]:
        """Last complete record in an open file, or None if empty."""
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == 0:
            return None
        fh.seek(max(0, size - _TAIL_BYTES))
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None

    def append(self, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Append one event and return the written record.

        Locked at the *file* level, not just within the process. The chain is
        the artefact that makes this desk's P&L checkable, and a second writer
        breaks it: two Deflow instances sharing a data directory -- a stray
        background process, a `--once` run beside a live server, a deployment
        that scales to two replicas -- interleave their appends, and every
        record after the collision points at a predecessor that is no longer
        its neighbour.

        Holding an exclusive lock and re-deriving the head from the file
        underneath it makes concurrent writers chain onto each other instead of
        forking. The alternative -- an in-memory head -- is correct only while
        exactly one process is running, which is not a property a trading
        system should quietly assume.
        """
        with self._lock:
            try:
                with self.path.open("a+") as fh:
                    if fcntl is not None:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                    try:
                        tail = self._tail_record(fh)
                        if tail is not None:
                            self._head = tail.get("hash", self._head)
                            self._count = int(tail.get("seq", self._count - 1)) + 1

                        body = {
                            "seq": self._count,
                            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                            "event": event,
                            "payload": payload,
                            "prev_hash": self._head,
                        }
                        record = {**body, "hash": hash_record(self._head, body)}
                        fh.write(json.dumps(record, default=str) + "\n")
                        fh.flush()
                        os.fsync(fh.fileno())
                    finally:
                        if fcntl is not None:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                log.error("Ledger write failed: %s", exc)
                return {"seq": self._count, "event": event, "payload": payload, "error": str(exc)}

            self._head = record["hash"]
            self._count += 1
            return record

    # -- reading ------------------------------------------------------------

    def __len__(self) -> int:
        return self._count

    @property
    def head(self) -> str:
        return self._head

    def read(self) -> Iterator[Dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def tail(self, n: int = 50, event: Optional[str] = None) -> List[Dict[str, Any]]:
        records = [r for r in self.read() if event is None or r.get("event") == event]
        return records[-n:]

    def events_of(self, event: str) -> List[Dict[str, Any]]:
        return [r for r in self.read() if r.get("event") == event]

    # -- verification -------------------------------------------------------

    def verify(self) -> ChainStatus:
        """Recompute every hash and report the first break, if any."""
        prev = GENESIS_HASH
        index = 0
        for index, record in enumerate(self.read()):
            body = {k: record[k] for k in ("seq", "at", "event", "payload", "prev_hash") if k in record}
            if record.get("prev_hash") != prev:
                return ChainStatus(
                    False, index, prev, index,
                    f"Entry {index} points at {str(record.get('prev_hash'))[:12]}…, "
                    f"but the previous entry hashed to {prev[:12]}…",
                )
            expected = hash_record(prev, body)
            if record.get("hash") != expected:
                return ChainStatus(
                    False, index, prev, index,
                    f"Entry {index} content does not match its recorded hash - it was modified after writing.",
                )
            prev = record["hash"]
        count = index + 1 if self.path.exists() and index or self._count else self._count
        return ChainStatus(True, count, prev, None, "Chain intact - every entry hashes to its successor.")


__all__ = ["ChainStatus", "DecisionLedger", "GENESIS_HASH", "hash_record"]
