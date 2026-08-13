"""Knowledge-base connector (runs on a remote worker, same contract).

Read-only. Its output is declared `untrusted` in the manifest, so anything the
host receives from here is labelled and cannot silently drive a privileged
action downstream.
"""

import re
from urllib.parse import quote  # stdlib string helper; no network module involved

BASE = "https://kb.example.internal"
RESOURCE = "knowledge_base"


def handle(ctx, payload):
    action = payload.get("action")
    params = payload.get("params") or {}

    if action == "read":
        article_id = str(params.get("article_id", ""))
        if not re.match(r"^KB-\d{1,6}$", article_id):
            raise ValueError(f"invalid article_id {article_id!r}")
        status, body = ctx.http(
            "GET", f"{BASE}/api/articles/{article_id}", resource=RESOURCE, action="read"
        )
    elif action == "search":
        query = re.sub(r"[^a-zA-Z0-9 _-]", "", str(params.get("query", "")))[:120]
        status, body = ctx.http(
            "GET",
            f"{BASE}/api/search?q={quote(query)}",
            resource=RESOURCE,
            action="search",
        )
    else:
        raise ValueError(f"unsupported action {action!r} for knowledge_base")

    ctx.log(f"{action} -> {status}")
    return {"status": status, "data": body}
