"""Typed tool contracts — validation at EVERY boundary (FR-3, ADR-004).

Production intent is Pydantic v2 / JSON-Schema. The spike ships a stdlib-only
equivalent so a reviewer can run it with zero installs (ADR-012 scope cut).
Semantics kept identical to the Pydantic sketch in the design docs:

  * unknown fields are rejected (no silent pass-through of model-authored keys)
  * types are checked, not coerced from arbitrary objects
  * range/length constraints are enforced at parse time
  * `confirmed_by` on the write tool is *structurally* unforgeable by the model:
    the orchestrator strips it from model-authored payloads before parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar
from urllib.parse import urlparse


#: https is required at the tool boundary. The single exception is http to a loopback
#: address, and only when the host has explicitly enabled it (`--allow-local-http`).
#: The exception exists because an https-only rule with no escape hatch means the real
#: HTTP transport can never be exercised by a test, and untested network code is a worse
#: risk than a loopback-scoped allowance. It is off by default and cannot be set from
#: model output.
ALLOW_INSECURE_LOOPBACK = False

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class ValidationError(ValueError):
    """Raised at a tool boundary when an input payload violates its contract."""

    def __init__(self, model: str, field: str, message: str) -> None:
        self.model, self.field, self.message = model, field, message
        super().__init__(f"{model}.{field}: {message}")


@dataclass
class Contract:
    """Base for tool input contracts. Subclasses validate in __post_init__."""

    #: fields the model is never allowed to author (privilege-escalation guard)
    MODEL_FORBIDDEN: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def parse(cls, payload: Any) -> "Contract":
        if not isinstance(payload, dict):
            raise ValidationError(cls.__name__, "<root>", "payload must be an object")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValidationError(cls.__name__, ",".join(unknown), "unknown field(s) rejected")
        return cls(**payload)  # type: ignore[arg-type]

    @classmethod
    def parse_model_authored(cls, payload: Any) -> "Contract":
        """Parse a payload that came from model output.

        Strips privileged fields *before* validation so a prompt-injected
        source can never populate them (threat: tool misuse / excessive agency).
        """
        if isinstance(payload, dict):
            payload = {k: v for k, v in payload.items() if k not in cls.MODEL_FORBIDDEN}
        return cls.parse(payload)

    # --- small validation helpers -------------------------------------------------
    def _str(self, name: str, *, min_len: int = 0, max_len: int = 10_000) -> str:
        v = getattr(self, name)
        if not isinstance(v, str):
            raise ValidationError(type(self).__name__, name, "expected string")
        if not (min_len <= len(v) <= max_len):
            raise ValidationError(
                type(self).__name__, name, f"length {len(v)} outside [{min_len},{max_len}]"
            )
        return v

    def _int(self, name: str, *, ge: int, le: int) -> int:
        v = getattr(self, name)
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValidationError(type(self).__name__, name, "expected integer")
        if not (ge <= v <= le):
            raise ValidationError(type(self).__name__, name, f"value {v} outside [{ge},{le}]")
        return v


@dataclass
class SearchIn(Contract):
    """READ — discover candidate sources for one sub-question."""

    query: str
    max_results: int = 5  # caps fan-out cost (cost lever #1)

    def __post_init__(self) -> None:
        self._str("query", min_len=3, max_len=400)
        self._int("max_results", ge=1, le=20)


@dataclass
class FetchIn(Contract):
    """READ — retrieve one source document."""

    url: str

    def __post_init__(self) -> None:
        v = self._str("url", min_len=8, max_len=2048)
        host = (urlparse(v).hostname or "").lower()
        if not v.startswith("https://"):
            insecure_ok = (
                ALLOW_INSECURE_LOOPBACK
                and v.startswith("http://")
                and host in _LOOPBACK_HOSTS
            )
            if not insecure_ok:
                raise ValidationError("FetchIn", "url", "non-https source rejected")
        if not host or ".." in v:
            raise ValidationError("FetchIn", "url", "malformed url")
        # full allowlist check happens in the host (tools.fetch), against
        # long-term memory's curated source allowlist.


@dataclass
class SummarizeIn(Contract):
    """READ (model-backed) — extractive summary of one fetched document."""

    document_id: str
    focus: str

    def __post_init__(self) -> None:
        self._str("document_id", min_len=1, max_len=128)
        self._str("focus", min_len=1, max_len=200)


@dataclass
class ExportReportIn(Contract):
    """WRITE — the one privileged, externally-visible, irreversible action.

    `confirmed_by` is set ONLY by the human-in-the-loop approval gate. It is in
    MODEL_FORBIDDEN, so `parse_model_authored` deletes it if a model (or an
    injected source speaking through a model) tries to supply it.
    """

    destination: str
    report_markdown: str
    confirmed_by: str = ""

    MODEL_FORBIDDEN: ClassVar[tuple[str, ...]] = ("confirmed_by",)

    def __post_init__(self) -> None:
        self._str("destination", min_len=3, max_len=256)
        self._str("report_markdown", min_len=1, max_len=200_000)
        self._str("confirmed_by", max_len=128)
