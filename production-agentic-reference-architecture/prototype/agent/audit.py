"""Tamper-evident audit log — closes threat-model residual risk R2.

The previous implementation appended plain JSONL: an attacker with disk access could
rewrite or delete a record and nothing would notice. This module hash-chains every
record, so any edit, deletion or reordering is detectable:

    record.prev_hash = hash of the previous record
    record.hash      = sha256(canonical(record without hash) + prev_hash)

Verification walks the chain from genesis and recomputes. Two properties follow:

  * **Tampering** — editing record N changes its hash, so record N+1's `prev_hash`
    no longer matches. Rewriting the rest of the chain to compensate is possible
    locally, which is why `head_hash` is also mirrored to a separate file: the
    attacker must find and rewrite both consistently.
  * **Truncation** — deleting the tail is the one attack a local chain cannot
    self-detect, so the record count and head hash are pinned in `audit.head.json`
    and a shorter chain fails verification against it.

This is not a substitute for shipping records to append-only external storage
(that remains the production requirement), but it makes local tampering evident
rather than silent, which is what R2 asked for.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

GENESIS = "0" * 64


def _canonical(payload: dict[str, Any]) -> bytes:
    """Stable serialisation — key order must not affect the hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def record_hash(payload: dict[str, Any], prev_hash: str) -> str:
    body = {k: v for k, v in payload.items() if k not in ("hash", "prev_hash")}
    return hashlib.sha256(_canonical(body) + prev_hash.encode()).hexdigest()


@dataclass
class VerificationResult:
    ok: bool
    records: int
    head_hash: str
    problems: list[str]

    def __bool__(self) -> bool:
        return self.ok


class AuditLog:
    """Append-only hash-chained log. One instance per log file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.head_path = path.with_suffix(".head.json")
        self._lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    # --- write ------------------------------------------------------------------
    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Append one record and return it, including its chain fields.

        Written with an fsync before the head pointer is updated, so a crash
        between the two leaves a detectable inconsistency rather than a silent
        gap: the chain is one record longer than the head claims, which
        `verify()` reports as `head_pointer_stale` rather than as tampering.
        """
        with self._lock:
            prev_hash, count = self._head()
            record = {
                "seq": count,
                "ts": payload.pop("ts", time.time()),
                **payload,
                "prev_hash": prev_hash,
            }
            record["hash"] = record_hash(record, prev_hash)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            self.head_path.write_text(
                json.dumps({"head_hash": record["hash"], "records": count + 1}, indent=2),
                encoding="utf-8",
            )
            return record

    def _head(self) -> tuple[str, int]:
        last, count = GENESIS, 0
        for rec in self.read():
            last, count = rec["hash"], count + 1
        return last, count

    # --- read / verify ----------------------------------------------------------
    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def verify(self) -> VerificationResult:
        problems: list[str] = []
        prev = GENESIS
        count = 0
        for rec in self.read():
            expected_seq = count
            if rec.get("seq") != expected_seq:
                problems.append(f"record {count}: seq is {rec.get('seq')}, expected {expected_seq} (reordered or deleted)")
            if rec.get("prev_hash") != prev:
                problems.append(f"record {count}: prev_hash does not match the previous record (broken chain)")
            recomputed = record_hash(rec, rec.get("prev_hash", ""))
            if recomputed != rec.get("hash"):
                problems.append(f"record {count}: contents were modified after signing")
            prev = rec.get("hash", "")
            count += 1

        if self.head_path.exists():
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
            if head.get("records", 0) > count:
                problems.append(
                    f"head pointer expects {head['records']} records but only {count} present (truncated)"
                )
            elif head.get("records", 0) < count:
                problems.append("head_pointer_stale: chain is longer than the head pointer (crash during append?)")
            elif head.get("head_hash") != prev:
                problems.append("head hash does not match the chain tip (tail rewritten)")
        elif count:
            problems.append("head pointer file is missing")

        return VerificationResult(ok=not problems, records=count, head_hash=prev, problems=problems)
