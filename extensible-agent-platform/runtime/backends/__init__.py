"""Simulated external systems, reachable only via the host egress proxy.

Swapping these for real HTTP clients is the only change needed to point the
platform at production SaaS: the extension manifests, the gate, the broker and
the audit trail are unchanged. That property is the point of the exercise.
"""

from . import cicd, issue_tracker, knowledge_base

ROUTES = {
    issue_tracker.DOMAIN: issue_tracker,
    knowledge_base.DOMAIN: knowledge_base,
    cicd.DOMAIN: cicd,
}


def reset_all() -> None:
    issue_tracker.reset()


__all__ = ["ROUTES", "reset_all", "issue_tracker", "knowledge_base", "cicd"]
