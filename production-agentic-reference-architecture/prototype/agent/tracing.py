"""Distributed tracing (FR-5, ADR-006).

Spans follow the OpenTelemetry GenAI semantic conventions
(`gen_ai.request.model`, `gen_ai.usage.input_tokens`, ...) plus derived
`cost_usd` / `latency_ms`. The exporter here is a JSONL file so the spike runs
offline; if `opentelemetry-sdk` is installed and OTEL_EXPORTER_OTLP_ENDPOINT is
set, `Tracer` also mirrors every span to the real SDK. Same attribute names
either way, so the collector-side dashboards do not change (no-lock-in).

Parent/child linkage is explicit rather than contextvar-based because retrieval
workers run in a thread pool; passing the parent span keeps the trace tree
correct across threads.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

try:  # optional real-OTel mirror; never required
    from opentelemetry import trace as _otel_trace  # type: ignore

    _OTEL = _otel_trace.get_tracer("agentic-research-spike")
except Exception:  # pragma: no cover - offline default
    _OTEL = None


def _now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    kind: str  # orchestrator | worker | tool | model | guardrail | gate
    start_ms: float
    end_ms: float | None = None
    status: str = "UNSET"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    # -- span API ---------------------------------------------------------------
    def set(self, **attrs: Any) -> "Span":
        self.attributes.update(attrs)
        return self

    def add_event(self, name: str, **attrs: Any) -> "Span":
        self.events.append({"name": name, "ts_ms": _now_ms(), "attributes": attrs})
        return self

    def record_model_usage(
        self, model: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> "Span":
        return self.set(
            **{
                "gen_ai.request.model": model,
                "gen_ai.usage.input_tokens": input_tokens,
                "gen_ai.usage.output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "start_ms": round(self.start_ms, 3),
            "end_ms": round(self.end_ms or self.start_ms, 3),
            "latency_ms": round((self.end_ms or self.start_ms) - self.start_ms, 3),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class _SpanCtx:
    """Context manager that closes the span and stamps latency/status."""

    def __init__(self, tracer: "Tracer", span: Span) -> None:
        self._tracer, self.span = tracer, span

    def __enter__(self) -> Span:
        return self.span

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.span.end_ms = _now_ms()
        self.span.attributes["latency_ms"] = round(self.span.end_ms - self.span.start_ms, 3)
        if exc is not None and self.span.status == "UNSET":
            self.span.status = "ERROR"
            self.span.attributes.setdefault("error.type", type(exc).__name__)
            self.span.attributes.setdefault("error.message", str(exc)[:500])
        elif self.span.status == "UNSET":
            self.span.status = "OK"
        self._tracer._emit(self.span)
        return False  # never swallow exceptions


class Tracer:
    """Collects spans in memory and appends them to `trace.jsonl`."""

    def __init__(self, trace_id: str | None = None, sink: Path | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.sink = sink
        self.spans: list[Span] = []
        self._lock = Lock()
        if self.sink:
            self.sink.parent.mkdir(parents=True, exist_ok=True)

    def start(
        self, name: str, kind: str, parent: Span | None = None, **attrs: Any
    ) -> _SpanCtx:
        span = Span(
            trace_id=self.trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_id=parent.span_id if parent else None,
            name=name,
            kind=kind,
            start_ms=_now_ms(),
            attributes=dict(attrs),
        )
        return _SpanCtx(self, span)

    def _emit(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)
            if self.sink:
                with self.sink.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")
        if _OTEL is not None and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            with _OTEL.start_as_current_span(span.name) as s:  # pragma: no cover
                for k, v in span.attributes.items():
                    s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else str(v))

    # -- aggregates the orchestrator and cost model read ------------------------
    def total_cost_usd(self) -> float:
        return round(sum(float(s.attributes.get("cost_usd", 0.0)) for s in self.spans), 6)

    def total_tokens(self) -> tuple[int, int]:
        i = sum(int(s.attributes.get("gen_ai.usage.input_tokens", 0)) for s in self.spans)
        o = sum(int(s.attributes.get("gen_ai.usage.output_tokens", 0)) for s in self.spans)
        return i, o

    def render_tree(self) -> str:
        """Operability (NFR-5): 'what is this run doing and why', from traces alone."""
        by_parent: dict[str | None, list[Span]] = {}
        for s in sorted(self.spans, key=lambda s: s.start_ms):
            by_parent.setdefault(s.parent_id, []).append(s)
        out: list[str] = []

        def walk(parent: str | None, depth: int) -> None:
            for s in by_parent.get(parent, []):
                d = s.to_dict()
                bits = [f"{d['latency_ms']:.0f}ms", s.status]
                if "cost_usd" in s.attributes:
                    bits.append(f"${s.attributes['cost_usd']:.5f}")
                if "gen_ai.request.model" in s.attributes:
                    bits.append(str(s.attributes["gen_ai.request.model"]))
                tok = s.attributes.get("gen_ai.usage.input_tokens")
                if tok:
                    bits.append(f"in={tok}/out={s.attributes.get('gen_ai.usage.output_tokens', 0)}")
                note = s.attributes.get("note") or s.attributes.get("subquestion") or ""
                out.append(
                    f"{'  ' * depth}{'└─ ' if depth else ''}{s.name} [{s.kind}] "
                    f"({', '.join(str(b) for b in bits)})" + (f"  {note}" if note else "")
                )
                for ev in s.events:
                    out.append(f"{'  ' * (depth + 1)}   • {ev['name']} {json.dumps(ev['attributes'], ensure_ascii=False)}")
                walk(s.span_id, depth + 1)

        walk(None, 0)
        return "\n".join(out)


def load_trace(path: Path) -> list[dict[str, Any]]:
    """Read a trace back for eval / replay debugging."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def iter_spans(spans: list[dict[str, Any]], kind: str | None = None, name: str | None = None) -> Iterator[dict[str, Any]]:
    for s in spans:
        if (kind is None or s["kind"] == kind) and (name is None or s["name"] == name):
            yield s
