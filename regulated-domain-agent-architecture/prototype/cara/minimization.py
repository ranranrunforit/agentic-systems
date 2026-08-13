"""Minimization filter: the load-bearing data control.

Maps to: data-handling/minimization-and-residency.md, control C-02.

Minimum-necessary is a PROJECTION performed before prompt assembly, not a policy
instruction. Two properties follow, and both are tested:

  1. Injection cannot widen scope. The runtime holds a projection; a prompt saying
     "also include the SSN" cannot succeed because the SSN was never materialised.
  2. Minimum-necessary becomes evidence. The manifest is a per-request record of
     exactly which field paths crossed the boundary -- the artefact a reviewer asks
     for and almost never gets.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from .audit import sha256
from .models import DataClass, Manifest

#: Generic sentence-initial / connective words that are title-cased in ordinary
#: prose. Domain nouns do NOT belong here -- an earlier version listed a sector's
#: vocabulary, which quietly exempted it from redaction.
_COMMON_TITLECASE = {"discussed", "follow", "reviewed", "advised", "note", "visit",
                     "called", "this", "there", "however", "after", "before"}

REDACT_PATTERNS = ["555-", "@", "SSN", "TIN"]

#: Generic sentence-initial / connective words that are title-cased in ordinary
#: prose. Domain nouns do NOT belong here -- an earlier version listed a sector's
#: vocabulary, which quietly exempted that vocabulary from redaction.
_COMMON_TITLECASE = {"discussed", "follow", "reviewed", "advised", "note", "visit",
                     "called", "this", "there", "however", "after", "before"}


class RecordStore:
    """Region-pinned, per-tenant. The tenant predicate is applied AT the store."""

    def __init__(self, records: list[dict[str, Any]],
                 subject_key: str = "subject_ref") -> None:
        #: `subject_ref` is the spine's name for "the record's identifier". The
        #: healthcare fixture happens to nest it under a domain key; the store does
        #: not care what that key is called.
        self.subject_key = subject_key
        self._by_key = {(r["tenant"], _subject_ref(r, subject_key)): r for r in records}

    def get(self, tenant: str, ref: str) -> dict[str, Any] | None:
        return self._by_key.get((tenant, ref))

    def delete(self, tenant: str, ref: str) -> bool:
        return self._by_key.pop((tenant, ref), None) is not None


def age_band(dob: str) -> str:
    year = int(dob.split("-")[0])
    age = 2026 - year
    if age >= 90:
        return "90+"  # mirrors Safe Harbor's treatment of ages over 89
    return f"{age // 10 * 10}-{age // 10 * 10 + 9}"


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Best-effort NER-style redaction.

    NOT a de-identification mechanism. Redacted notes stay classified D2 and stay
    inside the region and the zero-retention contract. Claiming otherwise is how an
    architecture accidentally asserts a de-identification it cannot support.
    """
    counts: dict[str, int] = {}
    out = []
    for token in text.split():
        if any(p in token for p in REDACT_PATTERNS):
            counts["CONTACT"] = counts.get("CONTACT", 0) + 1
            out.append("[REDACTED]")
        elif token.istitle() and len(token) > 3 and token.lower() not in _COMMON_TITLECASE:
            counts["PERSON"] = counts.get("PERSON", 0) + 1
            out.append("[REDACTED]")
        else:
            out.append(token)
    return " ".join(out), counts


class MinimizationFilter:
    """The only path from Zone 3 (regulated data) to Zone 4 (the model boundary)."""

    def __init__(self, region: str = "region-a", regime=None) -> None:
        self.region = region
        self.regime = regime
        #: Spine: "project to the allow-list, exclude the never-crosses classes,
        #: emit a manifest". Regime: which classes those are.
        self.field_class = regime.field_class if regime else {}
        self.never_crosses = (regime.never_crosses if regime
                              else frozenset({DataClass.D3}))
        self.strictest = regime.strictest_class if regime else DataClass.D3
        self.transforms = regime.transforms if regime else {}

    def project(self, record: dict[str, Any], allowlist: list[str], *,
                correlation_id: str, tenant: str, capability: str,
                allowlist_version: str,
                subject_key: str = "subject_ref") -> tuple[dict[str, Any], Manifest]:
        payload: dict[str, Any] = {}
        included: list[dict[str, Any]] = []

        for path in allowlist:
            if self.field_class.get(path, self.strictest) in self.never_crosses:
                # Never crosses, even if someone allow-lists it by mistake. Under
                # finance this excludes D4 as well, and D4 should never have been
                # in the environment to begin with (scope avoidance, not access
                # control) -- so this is the second line of defence, not the first.
                continue
            value = self._read(record, path)
            if value is None:
                continue
            transform = self.transforms.get(path)
            entry: dict[str, Any] = {"path": path, "transform": transform}

            if transform == "T-AGEBAND-v1":
                payload["age_band"] = age_band(value)
                entry["emitted_as"] = "age_band"
            elif transform == "T-REDACT-v1":
                texts, redactions = [], {}
                for note in value:
                    red, c = redact(note["text"] if isinstance(note, dict) else str(note))
                    texts.append(red)
                    for k, v in c.items():
                        redactions[k] = redactions.get(k, 0) + v
                payload["free_text"] = texts
                entry["count"] = len(texts)
                entry["redactions"] = redactions
            else:
                payload[path.replace("[]", "").split(".")[-1]] = value
                if isinstance(value, list):
                    entry["count"] = len(value)
            included.append(entry)

        excluded = sorted(p for p, c in self.field_class.items()
                          if c in self.never_crosses)
        alias = "subj_" + secrets.token_hex(2)
        prompt_hash = sha256(json.dumps(payload, sort_keys=True, default=str))

        manifest = Manifest(
            correlation_id=correlation_id, tenant=tenant, capability=capability,
            allowlist_version=allowlist_version,
            subject_ref=_subject_ref(record, subject_key), subject_alias=alias,
            fields_included=included, fields_excluded_by_class=excluded,
            prompt_hash=prompt_hash,
            boundary={"endpoint": f"inference-{self.region}", "region": self.region,
                      "retention": "zero", "training": "prohibited"},
        )
        # The alias, not the MRN, goes to the model. The ledger keeps the real ref.
        payload["subject_alias"] = alias
        return payload, manifest

    @staticmethod
    def _read(record: dict[str, Any], path: str) -> Any:
        node: Any = record
        for part in path.replace("[]", "").split("."):
            if part == "text":
                return node
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node


def _subject_ref(record: dict[str, Any], subject_key: str = "subject_ref") -> str:
    """Resolve the record's subject reference by a CONFIGURED path.

    An earlier version guessed by trying a list of domain key names
    ("patient", "customer", "student", ...). That list was a sector inventory
    living in spine code; the store should not know what a domain calls its
    subject, only where to find the reference.
    """
    node: Any = record
    for part in subject_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"record has no subject reference at {subject_key!r}")
        node = node[part]
    return str(node)
