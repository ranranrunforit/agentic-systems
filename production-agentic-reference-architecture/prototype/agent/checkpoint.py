"""Durable execution (FR-7, ADR-008).

SQLite is the whole durable-workflow engine here — chosen over Temporal/Restate so
the spike has no infrastructure dependency, while keeping the property that matters:
**every unit of paid work is committed before the next one starts**, so a restart
resumes instead of replaying.

Checkpoint boundaries are the stages that cost money or time:
  `plan`, `worker:<i>` (one per retrieval worker), `synthesis`, `guardrail:output`,
  and the `awaiting_approval` pause. A human-in-the-loop pause is just another
  durable state — a run may sit in it for hours.

Isolation note: one write transaction per checkpoint plus `synchronous=FULL` means a
`kill -9` between stages loses at most the in-flight stage. The rollback journal mode
is TRUNCATE rather than WAL because WAL needs a shared-memory mmap, which some
network/FUSE filesystems refuse; use WAL when the database lives on local disk.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

JOURNAL_MODE = os.environ.get("AGENT_SQLITE_JOURNAL", "TRUNCATE")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  question    TEXT NOT NULL,
  status      TEXT NOT NULL,
  trace_id    TEXT,
  created_ts  REAL NOT NULL,
  updated_ts  REAL NOT NULL,
  meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS checkpoints (
  run_id  TEXT NOT NULL,
  stage   TEXT NOT NULL,
  ts      REAL NOT NULL,
  data    TEXT NOT NULL,
  PRIMARY KEY (run_id, stage)
);
CREATE TABLE IF NOT EXISTS approvals (
  run_id      TEXT NOT NULL,
  token       TEXT NOT NULL,
  report_hash TEXT NOT NULL,
  approver    TEXT NOT NULL,
  decision    TEXT NOT NULL,
  ts          REAL NOT NULL,
  PRIMARY KEY (run_id, token)
);
"""


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path), timeout=10.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"PRAGMA journal_mode={JOURNAL_MODE}")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- runs -------------------------------------------------------------------
    def create_run(self, run_id: str, question: str, trace_id: str, **meta: Any) -> None:
        now = time.time()
        self.db.execute(
            "INSERT OR IGNORE INTO runs (run_id, question, status, trace_id, created_ts, updated_ts, meta)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, question, "running", trace_id, now, now, json.dumps(meta)),
        )
        self.db.commit()

    def set_status(self, run_id: str, status: str, **meta: Any) -> None:
        row = self.get_run(run_id)
        merged = {**(row.get("meta") if row else {}), **meta}
        self.db.execute(
            "UPDATE runs SET status=?, updated_ts=?, meta=? WHERE run_id=?",
            (status, time.time(), json.dumps(merged), run_id),
        )
        self.db.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["meta"] = json.loads(d["meta"])
        return d

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT run_id, question, status, updated_ts FROM runs ORDER BY updated_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- checkpoints ------------------------------------------------------------
    def put(self, run_id: str, stage: str, data: Any) -> None:
        """Commit one completed stage. Idempotent: re-running a stage overwrites it."""
        self.db.execute(
            "INSERT INTO checkpoints (run_id, stage, ts, data) VALUES (?,?,?,?)"
            " ON CONFLICT(run_id, stage) DO UPDATE SET ts=excluded.ts, data=excluded.data",
            (run_id, stage, time.time(), json.dumps(data, ensure_ascii=False)),
        )
        self.db.commit()

    def get(self, run_id: str, stage: str) -> Any | None:
        row = self.db.execute(
            "SELECT data FROM checkpoints WHERE run_id=? AND stage=?", (run_id, stage)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def stages(self, run_id: str) -> dict[str, Any]:
        rows = self.db.execute(
            "SELECT stage, data, ts FROM checkpoints WHERE run_id=? ORDER BY ts", (run_id,)
        ).fetchall()
        return {r["stage"]: json.loads(r["data"]) for r in rows}

    # --- approvals (HITL) -------------------------------------------------------
    def put_approval(
        self, run_id: str, token: str, report_hash: str, approver: str, decision: str
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO approvals (run_id, token, report_hash, approver, decision, ts)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, token, report_hash, approver, decision, time.time()),
        )
        self.db.commit()

    def get_approval(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM approvals WHERE run_id=? AND decision='approved' ORDER BY ts DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.db.close()
