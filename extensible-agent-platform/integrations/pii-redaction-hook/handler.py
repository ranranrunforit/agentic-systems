"""Pre-action hook: redact PII, veto credential leaks.

Hooks are the platform's answer to "we need a rule that applies to every
extension, forever". Because a hook is an extension, it goes through the same
governance lifecycle as everything else — but because it runs on the host side
of the gate, its veto is authoritative.

Order of operations for any privileged action:

    proposal -> pre_action hooks (here) -> gate -> broker -> sandbox -> audit
"""

import re

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"\b(?:\+?\d[\d ()-]{7,}\d)\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
CREDENTIALS = [
    re.compile(r"\b(?:fixture-|sk-|ghp_|xoxb-)[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\btkn_[0-9a-f]{8,}\b"),
    re.compile(r"\b(access[_ -]?token|api[_ -]?key|client[_ -]?secret)\b\s*[:=]", re.I),
    re.compile(r"\b(?:credential|secret) store\b", re.I),
]
TEXT_FIELDS = ("body", "reason", "summary", "comment")


def handle(ctx, payload):
    params = dict(payload.get("params") or {})
    redactions, notes = 0, []

    for field in TEXT_FIELDS:
        value = params.get(field)
        if not isinstance(value, str):
            continue
        for pattern in CREDENTIALS:
            if pattern.search(value):
                ctx.log(f"credential-shaped string in params.{field}")
                return {
                    "block": True,
                    "reason": (
                        f"params.{field} contains a credential-shaped string; refusing to "
                        "let it leave the host"
                    ),
                    "notes": "credential-guard",
                }
        redacted, n1 = EMAIL.subn("[redacted-email]", value)
        redacted, n2 = PHONE.subn("[redacted-phone]", redacted)
        redacted, n3 = CARD.subn("[redacted-card]", redacted)
        if n1 + n2 + n3:
            params[field] = redacted
            redactions += n1 + n2 + n3
            notes.append(f"{field}:{n1 + n2 + n3}")

    return {
        "params": params,
        "block": False,
        "reason": "",
        "notes": f"redacted {redactions} ({', '.join(notes)})" if redactions else "clean",
    }
