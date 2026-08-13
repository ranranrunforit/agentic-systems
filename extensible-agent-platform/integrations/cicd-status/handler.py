"""CI/CD status connector. Read-only adapter over one upstream route."""

import re

BASE = "https://ci.example.internal"
RESOURCE = "cicd"


def handle(ctx, payload):
    action = payload.get("action")
    params = payload.get("params") or {}
    if action != "read":
        raise ValueError(f"unsupported action {action!r} for cicd")

    service = str(params.get("service", ""))
    if not re.match(r"^[a-z][a-z0-9-]{1,40}$", service):
        raise ValueError(f"invalid service {service!r}")

    status, body = ctx.http(
        "GET", f"{BASE}/api/pipelines/{service}/latest", resource=RESOURCE, action="read"
    )
    ctx.log(f"pipeline {service} -> {status}")
    return {"status": status, "data": body}
