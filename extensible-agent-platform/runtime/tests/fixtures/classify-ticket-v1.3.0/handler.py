"""Ticket classifier.

Deliberately boring: keyword scoring, no model call, no network. It exists to
show that a *tool* is the same kind of contract citizen as a connector — the
host loads, isolates, authorizes and audits it identically.

If this were backed by an LLM, the important property would be unchanged: its
output is a *label*, not an action. Nothing here can close a ticket.
"""

QUEUES = {
    "billing": ("charge", "invoice", "refund", "payment", "card", "billed", "double charge"),
    "auth": ("login", "log in", "sso", "password", "mfa", "realm", "session"),
    "data-export": ("export", "download", "csv", "report", "pdf"),
    "bug": ("error", "crash", "spins", "broken", "fails", "500"),
}
URGENT = ("outage", "urgent", "asap", "cannot log in", "everyone", "production down")


def handle(ctx, payload):
    params = payload.get("params") or {}
    text = f"{params.get('subject', '')}\n{params.get('body', '')}".lower()

    scores = {
        queue: sum(1 for kw in keywords if kw in text) for queue, keywords in QUEUES.items()
    }
    label, hits = max(scores.items(), key=lambda kv: kv[1])
    if hits == 0:
        label, hits = "triage-manual", 0

    total = sum(scores.values()) or 1
    confidence = round(min(0.95, 0.35 + 0.6 * hits / total), 2)
    priority = "high" if any(kw in text for kw in URGENT) else "normal"

    return {
        "label": label,
        "confidence": confidence,
        "priority": priority,
        "signals": [q for q, s in scores.items() if s],
    }
