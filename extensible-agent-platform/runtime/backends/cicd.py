"""Simulated CI/CD service (stands in for GitHub Actions / GitLab CI / Buildkite).

Used by the triage flow to answer "is this a customer problem or did we just ship
a bad release?". Read-only in this reference: `rerun` exists as a route so the
high-impact path can be exercised, but no shipped extension is granted it.
"""

from __future__ import annotations

import copy
import re
from typing import Any

DOMAIN = "ci.example.internal"
VALID_TOKEN = "fixture-cicd-access-token"

_PIPELINES: dict[str, dict[str, Any]] = {
    "support-platform": {
        "service": "support-platform",
        "latest": {
            "id": "run-9931",
            "status": "failed",
            "branch": "main",
            "commit": "a91f0c2",
            "finished_at": "2026-08-12T06:41:00Z",
            "failed_stage": "migrate-realms",
            "log_excerpt": "ERROR realm sync aborted: unknown realm mapping for tenant acme",
        },
        "history": ["passed", "passed", "failed"],
    },
    "support-billing": {
        "service": "support-billing",
        "latest": {
            "id": "run-9928",
            "status": "passed",
            "branch": "main",
            "commit": "77bd410",
            "finished_at": "2026-08-12T05:02:00Z",
            "failed_stage": None,
            "log_excerpt": "",
        },
        "history": ["passed", "passed", "passed"],
    },
}


def state() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(_PIPELINES)


def handle(method: str, path: str, body: dict[str, Any], token: str, scopes: tuple[str, ...]):
    if token != VALID_TOKEN:
        return 401, {"error": "invalid_token"}

    m = re.match(r"^/api/pipelines/([A-Za-z0-9_-]+)/latest$", path)
    if m and method == "GET":
        if "pipelines.read" not in scopes:
            return 403, {"error": "insufficient_scope", "need": "pipelines.read"}
        pipeline = _PIPELINES.get(m.group(1))
        return (200, copy.deepcopy(pipeline)) if pipeline else (404, {"error": "not_found"})

    m = re.match(r"^/api/pipelines/([A-Za-z0-9_-]+)/rerun$", path)
    if m and method == "POST":
        if "pipelines.write" not in scopes:
            return 403, {"error": "insufficient_scope", "need": "pipelines.write"}
        return 202, {"service": m.group(1), "queued": True}

    return 404, {"error": "no_route", "path": path}
