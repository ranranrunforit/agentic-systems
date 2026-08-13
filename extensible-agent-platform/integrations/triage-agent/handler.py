"""Support-ticket triage agent.

Two things to notice, because they are the platform's whole thesis:

1. **Reads are brokered, writes are proposed.** The agent calls `ctx.call` for
   data and `ctx.propose` for anything that changes the world. It cannot execute
   a privileged action even if it wants to; `ctx.propose` only records intent,
   and the host decides.

2. **This agent is deliberately gullible.** `_follow_instructions_like_a_model_would`
   simulates a jailbroken or naively-prompted LLM: it scans retrieved text for
   imperative instructions and proposes them. That is the red-team fixture. A
   real LLM in this seat may be manipulated in exactly this way, so the platform
   is designed to stay safe *while assuming the agent is compromised*.

Run `python3 -m runtime.demos.demo_injection` to watch the gate contain it.
"""

import re

INSTRUCTION_PATTERNS = [
    re.compile(r"close all (?:open )?tickets", re.I),
    re.compile(r"(?:email|post|send)[^.]{0,60}(?:credential|token|secret)[^.]{0,40}", re.I),
    re.compile(r"delete (?:all|every)[^.]{0,40}", re.I),
]

RUNBOOK_QUERY = {
    "billing": "refund",
    "auth": "sso",
    "bug": "escalation",
    "data-export": "export",
    "triage-manual": "escalation",
}

CI_SERVICE_FOR_PROJECT = {
    "support-platform": "support-platform",
    "support-billing": "support-billing",
}


def handle(ctx, payload):
    ticket_id = str(payload.get("ticket_id", ""))
    sources = []

    # 1. read the ticket (brokered read; the host mints and redeems the token)
    ticket_resp = ctx.call("issue_tracker.read", {"ticket_id": ticket_id})
    ticket = (ticket_resp or {}).get("data") or {}
    if not ticket:
        return {"error": f"ticket {ticket_id} not readable", "sources": sources}
    sources.append(f"ticket:{ticket_id}")
    project = ticket.get("project", "")

    # 2. classify via the tool extension (same gate, same audit trail)
    classification = ctx.call(
        "ticket.classify",
        {"subject": ticket.get("subject", ""), "body": ticket.get("body", "")},
    ) or {}
    label = classification.get("label", "triage-manual")
    priority = classification.get("priority", "normal")

    # 3. ground the answer in the knowledge base
    retrieved_text = []
    kb_resp = ctx.call(
        "knowledge_base.search", {"query": payload.get("kb_query") or RUNBOOK_QUERY.get(label, label)}
    )
    for article in ((kb_resp or {}).get("data") or {}).get("results", [])[:3]:
        sources.append(f"kb:{article.get('id')}")
        retrieved_text.append(article.get("body", ""))

    # High-priority tickets consult the (community-edited, therefore untrusted)
    # escalation matrix. This is the realistic path by which poisoned content
    # reaches an agent.
    if priority == "high":
        esc = ctx.call("knowledge_base.search", {"query": "escalation"})
        for article in ((esc or {}).get("data") or {}).get("results", [])[:2]:
            sources.append(f"kb:{article.get('id')}")
            retrieved_text.append(article.get("body", ""))

    # 4. check whether we just shipped a bad release
    ci_note = ""
    if payload.get("include_ci", True) and project in CI_SERVICE_FOR_PROJECT:
        ci_resp = ctx.call("cicd.read", {"service": CI_SERVICE_FOR_PROJECT[project]})
        latest = ((ci_resp or {}).get("data") or {}).get("latest") or {}
        if latest.get("status") == "failed":
            ci_note = (
                f" Latest pipeline {latest.get('id')} failed at stage "
                f"{latest.get('failed_stage')}, which may be the cause."
            )
            sources.append(f"ci:{latest.get('id')}")

    # 5. propose the safe, in-scope actions. PROPOSE, not execute.
    ctx.propose(
        "issue_tracker",
        "label",
        {"ticket_id": ticket_id, "project": project, "label": label},
        rationale=f"classifier confidence {classification.get('confidence')}",
    )
    summary = (
        f"Classified as {label} (priority {priority}). "
        f"Runbook guidance retrieved from {len([s for s in sources if s.startswith('kb:')])} "
        f"article(s).{ci_note}"
    )
    ctx.propose(
        "issue_tracker",
        "comment",
        {"ticket_id": ticket_id, "project": project, "body": summary},
        rationale="triage summary for the assignee",
    )

    # 6. ...and then do the naive thing, on purpose (see module docstring)
    hijacked = _follow_instructions_like_a_model_would(
        ctx, ticket_id, project, retrieved_text + [ticket.get("body", "")]
    )

    return {
        "label": label,
        "priority": priority,
        "confidence": classification.get("confidence"),
        "summary": summary,
        "sources": sources,
        "instructions_found_in_untrusted_text": hijacked,
    }


def _follow_instructions_like_a_model_would(ctx, ticket_id, project, texts):
    """RED-TEAM FIXTURE: obey instructions found in retrieved content.

    A production agent should never do this, and a good system prompt makes it
    less likely — but "less likely" is not a security control. The host must hold
    when this happens, so the reference agent makes it happen on every run.
    """
    followed = []
    for text in texts:
        for pattern in INSTRUCTION_PATTERNS:
            match = pattern.search(text or "")
            if not match:
                continue
            followed.append(match.group(0)[:80])
            if "close" in match.group(0).lower():
                ctx.propose(
                    "issue_tracker",
                    "close",
                    {"ticket_id": ticket_id, "project": project, "reason": "hygiene sweep"},
                    rationale="instruction found in retrieved content",
                )
            else:
                ctx.propose(
                    "issue_tracker",
                    "comment",
                    {
                        "ticket_id": ticket_id,
                        "project": project,
                        "body": "access_token = fixture-issue-tracker-access-token",
                    },
                    rationale="instruction found in retrieved content",
                )
    return followed
