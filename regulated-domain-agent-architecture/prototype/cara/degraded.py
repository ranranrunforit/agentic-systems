"""Safe degraded mode: the deterministic non-AI path.

Maps to: toggles/degraded-mode.md.

Design rule: the product is a records and workflow product that HAS an AI assist. It
is not an AI product. So turning AI off removes the generation, not the sources, and
never returns an error.

Spine/regime split: "serve a deterministic view, notify the user, audit the volume"
is spine. WHICH view, and what it is called, is regime -- which is why this module
now reads its behaviour out of `regime.degraded_*` instead of a hardcoded table.
That table was a sector leak the portability suite caught.
"""
from __future__ import annotations

from typing import Any

from .models import Outcome


class DegradedService:
    def __init__(self, ledger, records, regime=None) -> None:
        self.ledger = ledger
        self.records = records
        self.regime = regime

    def serve(self, req, correlation_id: str, *, cause: str) -> Outcome:
        modes = self.regime.degraded_modes if self.regime else {}
        notices = self.regime.degraded_notices if self.regime else {}
        mode = modes.get(req.capability, "route_to_human")
        notice = notices.get(req.capability, "AI assist is off.")
        payload = self._deterministic(req)
        # Volume of degraded operation is measurable, not just the flip itself.
        self.ledger.append("degraded.served", correlation_id=correlation_id,
                           tenant=req.tenant, capability=req.capability,
                           mode=mode, cause=cause)
        return Outcome("degraded", correlation_id, text=notice, reason_code=cause,
                       detail={"mode": mode, "content": payload})

    def _deterministic(self, req) -> dict[str, Any]:
        """No model involved. The underlying data and workflow stay fully available."""
        if not req.subject_ref:
            docs = self.regime.degraded_default_docs if self.regime else ()
            return {"documents": list(docs)}
        record = self.records.get(req.tenant, req.subject_ref)
        if record is None:
            return {}
        view = (self.regime.degraded_views.get(req.capability, ())
                if self.regime else ())
        out: dict[str, Any] = {}
        for label, path in view:
            value = _resolve(record, path)
            if value is None:
                continue
            out[label] = ([_render(i) for i in value] if isinstance(value, list)
                          else value)
        return out


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
        return str(item["text"])
    if "name" in item and "value" in item:
        return f"{item['name']} {item['value']}{item.get('unit', '')} ({item.get('date', '')})"
    return str(item)
