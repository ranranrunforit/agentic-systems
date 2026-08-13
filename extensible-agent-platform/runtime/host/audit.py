"""Append-only, hash-chained audit log (NFR-4: attributability).

Every gate decision, token mint, egress call, sandbox execution and governance
action lands here. Records are chained (`prev` -> `hash`) so a deleted or edited
entry breaks verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

GENESIS = "0" * 64


@dataclass
class AuditRecord:
    seq: int
    ts: float
    event: str
    actor: str
    extension: str
    payload: dict[str, Any]
    prev: str
    hash: str = ""

    def digest(self) -> str:
        body = json.dumps(
            {
                "seq": self.seq,
                "ts": round(self.ts, 6),
                "event": self.event,
                "actor": self.actor,
                "extension": self.extension,
                "payload": self.payload,
                "prev": self.prev,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))


@dataclass
class AuditLog:
    path: str | None = None
    records: list[AuditRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self,
        event: str,
        *,
        actor: str = "system",
        extension: str = "-",
        **payload: Any,
    ) -> AuditRecord:
        with self._lock:
            prev = self.records[-1].hash if self.records else GENESIS
            rec = AuditRecord(
                seq=len(self.records) + 1,
                ts=time.time(),
                event=event,
                actor=actor,
                extension=extension,
                payload=payload,
                prev=prev,
            )
            rec.hash = rec.digest()
            self.records.append(rec)
            if self.path:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(rec.to_json() + "\n")
            return rec

    # -- inspection -------------------------------------------------------- #

    def verify(self) -> bool:
        prev = GENESIS
        for rec in self.records:
            if rec.prev != prev or rec.hash != rec.digest():
                return False
            prev = rec.hash
        return True

    def find(self, event: str | None = None, extension: str | None = None) -> list[AuditRecord]:
        return [
            r
            for r in self.records
            if (event is None or r.event == event)
            and (extension is None or r.extension.startswith(extension))
        ]

    def tail(self, n: int = 10) -> Iterable[AuditRecord]:
        return self.records[-n:]

    def render(self, n: int = 20) -> str:
        rows = []
        for r in self.tail(n):
            detail = " ".join(f"{k}={_short(v)}" for k, v in r.payload.items())
            rows.append(f"#{r.seq:<3} {r.event:<26} {r.extension:<28} {r.actor:<18} {detail}")
        return "\n".join(rows)


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 1] + "…"
