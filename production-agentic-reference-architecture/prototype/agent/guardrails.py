"""Two-sided guardrails (FR-6, ADR-007).

Three screens, deliberately placed at the three trust boundaries:

  1. `screen_input`  — user turn: direct prompt injection, scope, PII.
  2. `screen_retrieved` — tool output: *indirect* injection. Tool output is DATA.
     Instruction-like spans are neutralised before they can enter a model context.
  3. `screen_output` — model output: groundedness (every claim cited), PII
     egress, and residual instruction leakage.

The action-confirmation boundary is separate from and downstream of all three: even
a report that passes every screen cannot be exported without the HITL token
(`tools.ExportReportTool`). Pattern matching is a volume reducer, not the control —
the control is architectural, per the threat model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

INJECTION_PATTERNS = [
    r"(?i)ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+instructions",
    r"(?i)disregard\s+(?:the\s+)?(?:previous|prior|above|system)\b",
    r"(?i)\b(?:system|important)\s+(?:note|prompt|override)\b\s*:",
    r"(?i)you\s+are\s+now\s+(?:a|an|the)\b",
    r"(?i)export\s+(?:the\s+)?(?:full\s+)?(?:report|everything|all\s+data)\s+to\s+\S+",
    r"(?i)confirm\s+the\s+export\s+yourself",
    r"(?i)reveal\s+(?:your\s+)?(?:system\s+prompt|instructions)",
]

# Out-of-scope: this agent researches and reports. It does not operate other systems.
OUT_OF_SCOPE_PATTERNS = [
    r"(?i)\b(?:delete|drop|truncate)\s+(?:the\s+)?(?:database|table|repo|account)",
    r"(?i)\b(?:transfer|wire|refund)\s+(?:\$|\d)",
    r"(?i)\b(?:send|email|dm|message)\s+(?:\w+\s+){0,4}?to\s+[\w.+-]+@",
    r"(?i)\b(?:send|post|publish)\s+(?:an?\s+)?(?:email|dm|slack|message)\b",
    r"(?i)\b(?:deploy|restart|scale)\s+(?:the\s+)?(?:service|cluster|production)\b",
]

PII_PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.]{2,}",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "card": r"\b(?:\d[ -]?){13,16}\b",
    "phone": r"\b\+?\d{1,2}[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}\b",
}

REDACTION = "[redacted: instruction-like content in retrieved source]"


@dataclass
class GuardResult:
    allowed: bool
    control: str
    reasons: list[str] = field(default_factory=list)
    detections: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.allowed


def _find(patterns: list[str], text: str, kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in patterns:
        for m in re.finditer(p, text):
            out.append({"kind": kind, "pattern": p, "span": [m.start(), m.end()], "match": m.group(0)[:120]})
    return out


def _find_pii(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, p in PII_PATTERNS.items():
        for m in re.finditer(p, text):
            out.append({"kind": f"pii.{label}", "span": [m.start(), m.end()], "match": "<redacted>"})
    return out


# --- 1. input screen ---------------------------------------------------------------


def screen_input(question: str, *, max_len: int = 2000) -> GuardResult:
    reasons: list[str] = []
    detections: list[dict[str, Any]] = []

    if not (8 <= len(question) <= max_len):
        reasons.append("length_out_of_bounds")

    inj = _find(INJECTION_PATTERNS, question, "injection")
    if inj:
        reasons.append("prompt_injection")
        detections += inj

    oos = _find(OUT_OF_SCOPE_PATTERNS, question, "out_of_scope")
    if oos:
        reasons.append("out_of_scope_action")
        detections += oos

    pii = _find_pii(question)
    if pii:
        # Conservative: block rather than redact. A research question does not need
        # personal identifiers, and redaction risks silently changing the question.
        reasons.append("pii_in_request")
        detections += pii

    return GuardResult(
        allowed=not reasons,
        control="input_guardrail",
        reasons=reasons,
        detections=detections,
        text=question,
    )


# --- 2. retrieved-content screen (indirect injection) ------------------------------


def screen_retrieved(text: str, *, url: str = "") -> GuardResult:
    detections = _find(INJECTION_PATTERNS, text, "indirect_injection")
    sanitized = text
    for d in sorted(detections, key=lambda d: -d["span"][0]):
        s, e = d["span"]
        sanitized = sanitized[:s] + REDACTION + sanitized[e:]
    return GuardResult(
        allowed=True,  # never drop a source silently; neutralise and flag instead
        control="retrieved_content_guardrail",
        reasons=["indirect_injection_neutralised"] if detections else [],
        detections=detections,
        text=sanitized,
        metrics={"url": url, "spans_redacted": len(detections)},
    )


# --- 3. output screen --------------------------------------------------------------

_CLAIM_LINE = re.compile(r"^\s*[-*]\s+(?!\[S)(.+)$")
_CITED = re.compile(r"\[(?:S\d+|SYSTEM)\]\s*$")


def screen_output(report_markdown: str, *, allow_uncited: int = 0) -> GuardResult:
    reasons: list[str] = []
    detections: list[dict[str, Any]] = []

    body, _, _sources = report_markdown.partition("## Sources")
    claims = [m.group(1).strip() for line in body.splitlines() if (m := _CLAIM_LINE.match(line))]
    uncited = [c for c in claims if not _CITED.search(c)]
    if len(uncited) > allow_uncited:
        reasons.append("ungrounded_claims")
        detections += [{"kind": "ungrounded_claim", "match": c[:120]} for c in uncited[:5]]

    pii = _find_pii(body)
    if pii:
        reasons.append("pii_egress")
        detections += pii

    residual = _find(INJECTION_PATTERNS, report_markdown, "instruction_leak")
    if residual:
        reasons.append("instruction_leak")
        detections += residual

    return GuardResult(
        allowed=not reasons,
        control="output_guardrail",
        reasons=reasons,
        detections=detections,
        text=report_markdown,
        metrics={
            "claims": len(claims),
            "uncited_claims": len(uncited),
            "citation_rate": round(1 - len(uncited) / len(claims), 4) if claims else 1.0,
        },
    )
