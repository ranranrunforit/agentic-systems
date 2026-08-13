"""Vetted corpus store and retrieval.

Maps to: grounding/vetted-sources.md.

Two properties the tests exercise:
  - Validity: an expired or withdrawn document is excluded from retrieval (FC-10).
  - Isolation: the tenant predicate is applied AT the index, not after (T7/I-2). A
    post-filter would still have retrieved another tenant's spans first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .audit import sha256
from .models import Span, SourceClass


@dataclass
class Document:
    doc_id: str
    tenant: str
    title: str
    source_class: SourceClass
    version: str
    valid_until: str
    review_status: str  # current | superseded | withdrawn
    spans: list[dict[str, Any]] = field(default_factory=list)


class CorpusStore:
    def __init__(self, docs: list[Document]) -> None:
        self._docs = docs
        self.available = True  # tests flip this to force FC-2

    def add(self, doc: Document) -> None:
        self._docs.append(doc)

    def withdraw(self, doc_id: str) -> None:
        for d in self._docs:
            if d.doc_id == doc_id:
                d.review_status = "withdrawn"

    def citing_outputs(self, ledger, doc_id: str) -> list[dict[str, Any]]:
        """Reverse citation index: which past outputs cited a now-withdrawn doc?

        grounding/vetted-sources.md §6. Without this, a withdrawal silently leaves
        prior outputs grounded on retracted guidance.
        """
        hits = []
        for e in ledger.query(action="grounding.result"):
            if any(c.get("doc") == doc_id for c in e.get("citations", [])):
                hits.append(e)
        return hits

    def retrieve(self, *, tenant: str, text: str, allowed_classes: set[SourceClass],
                 today: str = "2026-08-13") -> list[Span]:
        if not self.available:
            raise RetrievalUnavailable("vetted corpus unreachable")

        terms = _tokens(text)
        out: list[Span] = []
        for doc in self._docs:
            # Index-level partition. Not a post-filter.
            if doc.tenant != tenant:
                continue
            if doc.source_class not in allowed_classes:
                continue
            if doc.review_status != "current" or doc.valid_until < today:
                continue  # FC-10
            for span in doc.spans:
                if terms & _tokens(span["text"]):
                    out.append(Span(
                        doc_id=doc.doc_id, version=doc.version,
                        offsets=span.get("offsets", "0:0"), text=span["text"],
                        source_class=doc.source_class,
                        subject_ref=span.get("subject_ref"),
                        asserts_absence=span.get("asserts_absence", False),
                        content_hash=sha256(span["text"]),
                    ))
        return out


class RetrievalUnavailable(RuntimeError):
    pass


def record_spans(record: dict[str, Any], regime=None) -> list[Span]:
    """S1 spans: the subject's own record, rendered by regime-supplied rules.

    Note what is NOT generated here: an empty list produces NO span. Silence in the
    record and an assertion of absence are different facts, and only an explicit
    documented-absence marker produces a span with `asserts_absence`. That rule is
    spine; WHICH markers exist is regime.
    """
    ref = record["patient"]["mrn"]
    rules = regime.s1_span_rules if regime else _DEFAULT_S1_RULES
    markers = regime.absence_markers if regime else _DEFAULT_ABSENCE_MARKERS
    spans: list[Span] = []

    def add(text: str, absence: bool = False) -> None:
        spans.append(Span(
            doc_id=f"RECORD:{ref}", version=record.get("version", "1"),
            offsets=f"{len(spans)}:0", text=text, source_class=SourceClass.S1,
            subject_ref=ref, asserts_absence=absence, content_hash=sha256(text),
        ))

    for path, label in rules:
        value = _resolve(record, path)
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                add(f"{label}: {_render(item)}")
        else:
            add(f"{label}: {value}")

    for flag, text in markers:
        if record.get(flag):
            add(text, absence=True)
    return spans


def _resolve(record: dict[str, Any], path: str) -> Any:
    node: Any = record
    for part in path.replace("[]", "").split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _render(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    if "text" in item:
        extra = item.get("date") or item.get("last_filled") or item.get("onset")
        return f"{item['text']}" + (f" on {extra}" if extra else "")
    if "name" in item and "value" in item:  # lab-shaped
        return f"{item['name']} {item['value']} {item.get('unit','')} on {item.get('date','')}".strip()
    return str(item)


_DEFAULT_S1_RULES = (("problem_list[]", "Problem"), ("medications[]", "Medication"),
                     ("labs[]", "Lab"), ("allergies[]", "Allergy"))
_DEFAULT_ABSENCE_MARKERS = (
    ("allergy_status_documented", "No known drug allergies documented at intake"),)


def _tokens(text: str) -> set[str]:
    return {t.strip(".,:;()%").lower() for t in str(text).split() if len(t) > 2}
