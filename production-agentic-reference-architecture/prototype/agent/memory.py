"""Memory and context engineering (FR-2, ADR-003).

Three tiers, each with an explicit write / read / eviction policy. They are
separate classes on purpose: conflating them is what blows the context budget.

  Working (short-term)   per-run scratch: plan, partial findings, stage status.
                         write: every stage appends. read: synthesizer + operator.
                         eviction: dropped at run end / checkpoint TTL.
  Long-term (persistent) source allowlist, format preferences, prior-report
                         dedupe keys. write: explicit audited calls only, never
                         from model output. read: planner + synthesizer + fetch
                         allowlist check. eviction: TTL + manual curation.
  Retrieved (external)   fetched documents and their extractive summaries with
                         citation metadata. write: workers, per fetch.
                         read: context assembler. eviction: per run; only top-k
                         by relevance are allowed into the synthesis context.

`ContextAssembler` enforces the declared 60/20/20 split of the model window
(evidence / plan+question / headroom). The synthesizer never sees a raw document —
only ranked extractive summaries. That single rule is the dominant cost lever and
the main defence against context rot.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import estimate_tokens

# --- Working memory ---------------------------------------------------------------


@dataclass
class WorkingMemory:
    run_id: str
    question: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    stage_status: dict[str, str] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def append_finding(self, subquestion: str, payload: dict[str, Any]) -> None:
        self.findings.append({"subquestion": subquestion, **payload})

    def note(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, "ts": time.time(), **data})

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "plan": self.plan,
            "stage_status": self.stage_status,
            "findings": self.findings,
            "events": self.events,
        }

    @classmethod
    def restore(cls, data: dict[str, Any]) -> "WorkingMemory":
        wm = cls(run_id=data["run_id"], question=data.get("question", ""))
        wm.plan = data.get("plan", {})
        wm.stage_status = data.get("stage_status", {})
        wm.findings = data.get("findings", [])
        wm.events = data.get("events", [])
        return wm

    def evict(self) -> None:
        """Called at run completion; working memory is not durable state."""
        self.findings.clear()
        self.events.clear()


# --- Long-term memory -------------------------------------------------------------

DEFAULT_LONG_TERM: dict[str, Any] = {
    "source_allowlist": [
        "research.example.org",
        "docs.example.com",
        "standards.example.gov",
        "blog.example.net",
    ],
    "export_destination_allowlist": ["file://reports/", "https://reports.example.com/"],
    "preferences": {"max_claims_per_subquestion": 2, "citation_style": "bracketed"},
    "report_dedupe_keys": {},
    "ttl_days": 90,
}


class LongTermMemory:
    """Curated, audited, slow-changing state. Never written from model output."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(json.dumps(DEFAULT_LONG_TERM))
        if path.exists():
            self.data.update(json.loads(path.read_text(encoding="utf-8")))
        self.audit: list[dict[str, Any]] = []

    # read paths
    def allowlisted_source(self, host: str) -> bool:
        return host in self.data["source_allowlist"]

    def allowlisted_destination(self, destination: str) -> bool:
        return any(destination.startswith(p) for p in self.data["export_destination_allowlist"])

    def preferences(self) -> dict[str, Any]:
        return dict(self.data["preferences"])

    def seen_report(self, key: str) -> bool:
        return key in self.data["report_dedupe_keys"]

    # the only write path: explicit, attributed, audited (governance §audit-log)
    def write(self, section: str, key: str, value: Any, *, actor: str, reason: str) -> None:
        if section not in self.data or not isinstance(self.data[section], dict):
            raise KeyError(f"long-term memory section not writable: {section}")
        self.data[section][key] = value
        self.audit.append(
            {"ts": time.time(), "actor": actor, "section": section, "key": key, "reason": reason}
        )
        self.flush()

    def evict_expired(self, now: float | None = None) -> int:
        """TTL sweep over dedupe keys; the allowlist is manually curated only."""
        now = now or time.time()
        ttl = float(self.data["ttl_days"]) * 86400
        keys = self.data["report_dedupe_keys"]
        stale = [k for k, ts in keys.items() if now - float(ts) > ttl]
        for k in stale:
            del keys[k]
        if stale:
            self.flush()
        return len(stale)

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")


# --- Retrieved memory -------------------------------------------------------------


@dataclass
class Evidence:
    citation: str
    url: str
    title: str
    summary: str
    subquestion: str
    relevance: float
    sanitized: bool = False


class RetrievedMemory:
    """Per-run evidence store. Also the fetch dedupe cache (cost lever #1)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}  # url -> raw doc (never sent to synth)
        self.evidence: list[Evidence] = []
        self._citations: dict[str, str] = {}  # url -> citation id (stable per source)

    def cached(self, url: str) -> dict[str, Any] | None:
        return self.docs.get(url)

    def put_doc(self, url: str, doc: dict[str, Any]) -> None:
        self.docs[url] = doc

    def add_evidence(self, *, url: str, **kw: Any) -> Evidence:
        """One citation id per source, even when two workers cite the same source."""
        citation = self._citations.setdefault(url, f"S{len(self._citations) + 1}")
        ev = Evidence(citation=citation, url=url, **kw)
        self.evidence.append(ev)
        return ev

    def restore(self, docs: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
        self.docs = dict(docs)
        self.evidence = [Evidence(**e) for e in evidence]
        self._citations = {e.url: e.citation for e in self.evidence}

    def snapshot(self) -> dict[str, Any]:
        return {
            "docs": self.docs,
            "evidence": [e.__dict__ for e in self.evidence],
        }


# --- Context assembly -------------------------------------------------------------


@dataclass
class ContextBudget:
    window_tokens: int = 200_000
    evidence_share: float = 0.60
    plan_share: float = 0.20
    # remaining 0.20 is headroom: output + guardrail re-reads + retry margin

    #: Cost lever L3: cap evidence items per sub-question rather than only globally.
    #: Synthesis input is the dominant cost driver (77%), and a global cap spends it
    #: unevenly — one well-covered sub-question can crowd out the others *and* pay for
    #: near-duplicate summaries of the same point. Capping per sub-question buys
    #: breadth per token. `None` disables the cap.
    max_evidence_per_subquestion: int | None = None

    def evidence_tokens(self) -> int:
        return int(self.window_tokens * self.evidence_share)

    def plan_tokens(self) -> int:
        return int(self.window_tokens * self.plan_share)


class ContextAssembler:
    """Builds the synthesis payload under a declared token budget."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def assemble(
        self,
        *,
        question: str,
        plan: dict[str, Any],
        evidence: list[Evidence],
        failed_subquestions: list[str],
        preferences: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ranked = sorted(evidence, key=lambda e: -e.relevance)

        # L3: per-sub-question cap, applied before the token budget so the budget is
        # spent on breadth rather than on the best-covered sub-question.
        per_sq_cap = self.budget.max_evidence_per_subquestion
        dropped_by_cap = 0
        if per_sq_cap:
            seen: dict[str, int] = {}
            capped: list[Evidence] = []
            for e in ranked:
                count = seen.get(e.subquestion, 0)
                if count >= per_sq_cap:
                    dropped_by_cap += 1
                    continue
                seen[e.subquestion] = count + 1
                capped.append(e)
            ranked = capped

        cap = self.budget.evidence_tokens()
        used, kept, dropped = 0, [], 0
        for e in ranked:
            cost = estimate_tokens(e.summary) + 24  # + citation/title overhead
            if used + cost > cap:
                dropped += 1
                continue
            used += cost
            kept.append(
                {
                    "citation": e.citation,
                    "url": e.url,
                    "title": e.title,
                    "summary": e.summary,
                    "subquestion": e.subquestion,
                }
            )
        payload = {
            "question": question,
            "subquestions": plan.get("subquestions", []),
            "evidence": kept,
            "failed_subquestions": failed_subquestions,
            "preferences": preferences,
        }
        stats = {
            "evidence_tokens_used": used,
            "evidence_token_cap": cap,
            "evidence_items_kept": len(kept),
            "evidence_items_dropped": dropped,
            "evidence_items_dropped_by_subquestion_cap": dropped_by_cap,
            "max_evidence_per_subquestion": per_sq_cap or 0,
            "plan_token_cap": self.budget.plan_tokens(),
            "context_utilisation": round(used / cap, 4) if cap else 0.0,
        }
        return payload, stats
