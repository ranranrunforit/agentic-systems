"""Issue-tracker connector.

The connector is a thin, auditable adapter: it maps a declared capability onto
one upstream HTTP call and returns the response. Everything it is *allowed* to do
lives in extension.yaml, and every call it makes goes out through `ctx.http`,
which the host authorizes and credentials. The connector never sees a token.
"""

import re

BASE = "https://issues.example.internal"
RESOURCE = "issue_tracker"
TICKET_RE = re.compile(r"^[A-Z]{1,4}-\d{1,8}$")


def handle(ctx, payload):
    action = payload.get("action")
    params = payload.get("params") or {}
    ticket_id = str(params.get("ticket_id", ""))

    if action in ("read", "label", "comment", "close") and not TICKET_RE.match(ticket_id):
        raise ValueError(f"invalid ticket_id {ticket_id!r} (refusing to build a URL from it)")

    if action == "read":
        status, body = ctx.http(
            "GET", f"{BASE}/api/tickets/{ticket_id}", resource=RESOURCE, action="read"
        )
    elif action == "label":
        label = str(params.get("label", "")).strip()
        if not re.match(r"^[a-z][a-z0-9/_-]{0,31}$", label):
            raise ValueError(f"invalid label {label!r}")
        status, body = ctx.http(
            "POST",
            f"{BASE}/api/tickets/{ticket_id}/labels",
            {"label": label},
            resource=RESOURCE,
            action="label",
        )
    elif action == "comment":
        text = str(params.get("body", ""))[:4000]
        status, body = ctx.http(
            "POST",
            f"{BASE}/api/tickets/{ticket_id}/comments",
            {"body": text},
            resource=RESOURCE,
            action="comment",
        )
    elif action == "close":
        status, body = ctx.http(
            "POST",
            f"{BASE}/api/tickets/{ticket_id}/close",
            {"reason": str(params.get("reason", ""))[:280]},
            resource=RESOURCE,
            action="close",
        )
    else:
        raise ValueError(f"unsupported action {action!r} for issue_tracker")

    ctx.log(f"{action} {ticket_id} -> {status}")
    return {"status": status, "data": body}
