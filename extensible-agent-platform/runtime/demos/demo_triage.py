"""Demo 1 — the happy path: what the platform is actually for.

    python3 -m runtime.demos.demo_triage

An operator asks the triage agent to handle a billing ticket. The agent reads the
ticket, calls a tool, searches the knowledge base, checks CI, and proposes two
actions. Both are in scope, untainted by injection signals, and execute.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _util import ROOT, audit_tail, bullet, step, title, verdict  # noqa: F401
from runtime.backends import issue_tracker, reset_all
from runtime.host import Host


def main() -> int:
    title("DEMO 1 — SUPPORT-TICKET TRIAGE THROUGH THE EXTENSION CONTRACT")
    reset_all()
    host = Host.bootstrap()

    step(1, "loaded extensions (all four kinds, one contract)")
    print(host.registry.render())

    step(2, "run the agent on T-1042 (duplicate charge, tenant acme)")
    result = host.run_agent("triage-agent", {"ticket_id": "T-1042"},
                            actor="alice@support", tenant="acme")
    for key in ("label", "priority", "confidence", "summary", "sources"):
        bullet(f"{key}: {result.value.get(key)}")

    step(3, "proposed actions and what the gate did with them")
    for outcome in result.outcomes:
        mark = "ALLOW" if outcome.allowed else "DENY "
        bullet(f"{outcome.proposal['resource']}:{outcome.proposal['action']} "
               f"(impact {outcome.impact})", mark)
        bullet(f"  {'; '.join(outcome.reasons)[:150]}", " ")

    step(4, "state of the world afterwards")
    ticket = issue_tracker.state()["T-1042"]
    bullet(f"labels:   {ticket['labels']}")
    bullet(f"status:   {ticket['status']}")
    bullet(f"comments: {[c['body'][:70] for c in ticket['comments']]}")

    audit_tail(host, events={"egress.call", "gate.allowed", "hook.pre_action"}, n=10)
    ok = "billing" in ticket["labels"] and ticket["status"] == "open" and len(result.executed()) == 2
    verdict(ok, "triage labelled and commented; nothing high-impact happened unattended")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
