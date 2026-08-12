"""Tooling layer — four typed tools, one of them state-changing (FR-3, ADR-004).

  search         READ   discover candidate sources for a sub-question
  fetch          READ   retrieve one source (https + allowlist enforced)
  summarize      READ   model-backed extractive summary (context-budget lever)
  export_report  WRITE  the single privileged, irreversible, externally visible
                        action — gated by human approval (FR-6/FR-7)

Every tool validates its input against a contract at the boundary before any side
effect. Payloads that originated in model output are parsed with
`parse_model_authored`, which strips privileged fields — so an injected source
cannot talk the model into self-approving an export.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from .audit import AuditLog
from .contracts import (
    Contract,
    ExportReportIn,
    FetchIn,
    SearchIn,
    SummarizeIn,
    ValidationError,
)
from .memory import LongTermMemory, RetrievedMemory
from .models import ModelClient, ModelRouter
from .retrieval import Transport, TransportError, build_transport
from .tracing import Span, Tracer

CORPUS_PATH = Path(__file__).parent / "corpus" / "sources.json"
_FETCH_LATENCY_MS = 120.0


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


@dataclass
class ToolContext:
    ltm: LongTermMemory
    retrieved: RetrievedMemory
    model: ModelClient
    router: ModelRouter
    tracer: Tracer
    run_dir: Path
    corpus: list[dict[str, Any]] = field(default_factory=load_corpus)
    #: retrieval transport — fixture (default, deterministic) or real HTTP
    transport: Transport | None = None
    fail_urls: set[str] = field(default_factory=set)  # chaos drill / tool outage
    #: set ONLY by the HITL approval gate (orchestrator.approve), and only after
    #: the approver has been authenticated (agent.identity) — threat-model R1
    approval: dict[str, Any] | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)
    fetch_calls: int = 0
    latency_speed: float = 1.0
    #: per-URL locks so two parallel workers wanting the same source pay once
    _fetch_locks: dict[str, Lock] = field(default_factory=dict)
    _locks_guard: Lock = field(default_factory=Lock)

    def get_transport(self) -> Transport:
        if self.transport is None:
            self.transport = build_transport("fixture", corpus=self.corpus, latency_speed=self.latency_speed)
        return self.transport

    def fetch_lock(self, url: str) -> Lock:
        with self._locks_guard:
            return self._fetch_locks.setdefault(url, Lock())


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None
    cost_usd: float = 0.0


class Tool:
    name: str = ""
    side_effect: str = "read"  # read | write
    contract: type[Contract] = Contract

    def _run(self, args: Any, ctx: ToolContext, span: Span) -> Any:  # pragma: no cover
        raise NotImplementedError

    def invoke(
        self,
        payload: dict[str, Any],
        ctx: ToolContext,
        parent: Span | None = None,
        *,
        model_authored: bool = True,
    ) -> ToolResult:
        with ctx.tracer.start(
            f"tool.{self.name}", "tool", parent, **{"tool.name": self.name, "tool.side_effect": self.side_effect}
        ) as span:
            try:
                args = (
                    self.contract.parse_model_authored(payload)
                    if model_authored
                    else self.contract.parse(payload)
                )
            except ValidationError as exc:
                span.status = "ERROR"
                span.add_event("tool.input_rejected", field=exc.field, message=exc.message)
                return ToolResult(False, error=str(exc), error_kind="validation")
            try:
                data = self._run(args, ctx, span)
            except ToolFailure as exc:
                span.status = "ERROR"
                span.add_event("tool.failed", kind=exc.kind, message=str(exc))
                return ToolResult(False, error=str(exc), error_kind=exc.kind)
            return ToolResult(True, data=data, cost_usd=float(span.attributes.get("cost_usd", 0.0)))


class ToolFailure(RuntimeError):
    def __init__(self, message: str, kind: str = "tool_error") -> None:
        super().__init__(message)
        self.kind = kind


# --- READ tools -------------------------------------------------------------------


class SearchTool(Tool):
    name, side_effect, contract = "search", "read", SearchIn

    def _run(self, args: SearchIn, ctx: ToolContext, span: Span) -> list[dict[str, str]]:
        transport = ctx.get_transport()
        try:
            hits = transport.search(args.query, args.max_results)
        except TransportError as exc:
            raise ToolFailure(str(exc), kind=exc.kind) from exc
        span.set(
            **{
                "tool.query": args.query,
                "tool.result_count": len(hits),
                "tool.max_results": args.max_results,
                "tool.transport": transport.name,
            }
        )
        return hits


class FetchTool(Tool):
    name, side_effect, contract = "fetch", "read", FetchIn

    def _run(self, args: FetchIn, ctx: ToolContext, span: Span) -> dict[str, Any]:
        host = urlparse(args.url).hostname or ""
        span.set(**{"tool.url": args.url, "tool.host": host})
        if not ctx.ltm.allowlisted_source(host):
            raise ToolFailure(f"host not on source allowlist: {host}", kind="not_allowlisted")
        # Serialise on the URL so parallel workers wanting the same source pay
        # for exactly one fetch (cost lever #1: dedupe).
        with ctx.fetch_lock(args.url):
            cached = ctx.retrieved.cached(args.url)
            if cached is not None:
                span.set(**{"tool.cache_hit": True, "tool.document_id": cached["document_id"]})
                return cached
            if args.url in ctx.fail_urls:
                time.sleep(_FETCH_LATENCY_MS * ctx.latency_speed / 1000.0)
                raise ToolFailure(f"upstream source unavailable: {args.url}", kind="upstream_unavailable")
            transport = ctx.get_transport()
            try:
                doc = transport.fetch(args.url)
            except TransportError as exc:
                raise ToolFailure(str(exc), kind=exc.kind) from exc
            record = {
                "document_id": hashlib.sha256(args.url.encode()).hexdigest()[:12],
                "url": doc.url,
                "title": doc.title,
                "text": doc.text,
                "fetched_at": time.time(),
            }
            ctx.retrieved.put_doc(args.url, record)
            ctx.fetch_calls += 1
            span.set(
                **{
                    "tool.cache_hit": False,
                    "tool.document_id": record["document_id"],
                    "tool.bytes": doc.bytes_read or len(doc.text),
                    "tool.transport": transport.name,
                    "tool.final_url": doc.url,
                }
            )
            return record


class SummarizeTool(Tool):
    """Model-backed. Extractive only — raw documents never reach the synthesizer."""

    name, side_effect, contract = "summarize", "read", SummarizeIn

    def _run(self, args: SummarizeIn, ctx: ToolContext, span: Span) -> dict[str, Any]:
        doc = next(
            (d for d in ctx.retrieved.docs.values() if d["document_id"] == args.document_id), None
        )
        if doc is None:
            raise ToolFailure(f"unknown document_id: {args.document_id}", kind="not_found")
        tier = ctx.router.tier("summarize")
        resp = ctx.model.complete("summarize", tier, {"text": doc["text"], "focus": args.focus})
        span.record_model_usage(resp.model, resp.input_tokens, resp.output_tokens, resp.cost_usd)
        span.set(**{"tool.document_id": args.document_id})
        return {"summary": resp.content["summary"], "url": doc["url"], "title": doc["title"]}


# --- WRITE tool -------------------------------------------------------------------


class ExportReportTool(Tool):
    """The one state-changing tool. Three independent controls guard it:

    1. `confirmed_by` is stripped from model-authored payloads (contracts layer);
    2. the tool refuses unless `ctx.approval` carries a token issued by the HITL
       gate for *this* run and *this* report hash (model -> action path broken);
    3. the destination must be on the curated allowlist in long-term memory.
    """

    name, side_effect, contract = "export_report", "write", ExportReportIn

    def _run(self, args: ExportReportIn, ctx: ToolContext, span: Span) -> dict[str, Any]:
        report_hash = hashlib.sha256(args.report_markdown.encode()).hexdigest()[:16]
        span.set(**{"tool.destination": args.destination, "tool.report_hash": report_hash})
        approval = ctx.approval
        if not args.confirmed_by or approval is None:
            span.add_event("guardrail.blocked", control="hitl_confirmation", reason="unconfirmed_export")
            raise ToolFailure("export requires human confirmation", kind="unconfirmed_export")
        if approval.get("token") != args.confirmed_by:
            span.add_event("guardrail.blocked", control="hitl_confirmation", reason="bad_token")
            raise ToolFailure("confirmation token not issued by the approval gate", kind="unconfirmed_export")
        if approval.get("report_hash") != report_hash:
            span.add_event("guardrail.blocked", control="hitl_confirmation", reason="report_changed_after_approval")
            raise ToolFailure("report changed after approval", kind="unconfirmed_export")
        if not ctx.ltm.allowlisted_destination(args.destination):
            span.add_event("guardrail.blocked", control="destination_allowlist", destination=args.destination)
            raise ToolFailure(f"destination not allowlisted: {args.destination}", kind="not_allowlisted")

        if args.destination.startswith("file://"):
            out = ctx.run_dir / args.destination[len("file://"):]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(args.report_markdown, encoding="utf-8")
            location = str(out)
        else:  # https destination: not performed in the spike (ADR-012)
            location = args.destination
            span.add_event("tool.simulated_network_write", destination=args.destination)

        # Tamper-evident append (hash-chained — threat-model R2). The audit record
        # names the *authenticated principal id*, not a display name, so two people
        # called Alice remain distinguishable in the record forever.
        log = AuditLog(ctx.run_dir / "audit.jsonl")
        record = log.append(
            {
                "action": "export_report",
                "destination": args.destination,
                "location": location,
                "report_hash": report_hash,
                "approved_by": approval.get("principal_id") or approval.get("approver"),
                "approver_display_name": approval.get("approver"),
                "authenticated": bool(approval.get("principal_id")),
                "approval_token_prefix": args.confirmed_by[:8],
                "trace_id": ctx.tracer.trace_id,
                "run_id": ctx.run_dir.name,
            }
        )
        ctx.audit.append(record)
        span.add_event(
            "audit.appended", action="export_report", seq=record["seq"], chain_hash=record["hash"][:12]
        )
        return record


TOOLS: dict[str, Tool] = {t.name: t for t in (SearchTool(), FetchTool(), SummarizeTool(), ExportReportTool())}

TOOL_REGISTRY_SPEC: list[dict[str, Any]] = [
    {"name": t.name, "side_effect": t.side_effect, "contract": t.contract.__name__}
    for t in TOOLS.values()
]
