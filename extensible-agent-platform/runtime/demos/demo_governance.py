"""Demo 4 — governance: permission diffing, kill-switch, rotation (FR-4).

    python3 -m runtime.demos.demo_governance
"""

import os

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _util import ROOT, audit_tail, bullet, step, title, verdict  # noqa: F401
from runtime.backends import reset_all
from runtime.host import Grant, Host, contract
from runtime.host.errors import HostError

FIXTURE = os.path.join(ROOT, "runtime", "tests", "fixtures", "classify-ticket-v1.3.0")
INTEGRATIONS = os.path.join(ROOT, "integrations")


def main() -> int:
    title("DEMO 4 — GOVERNANCE LIFECYCLE: DIFF, RE-APPROVE, KILL, ROTATE")
    reset_all()
    host = Host.bootstrap()
    ok = True

    step(1, "classify-ticket 1.3.0 quietly asks for issue_tracker:read,close")
    old = host.registry.get("classify-ticket")
    new = contract.load_manifest(os.path.join(FIXTURE, "extension.yaml"))
    diff = contract.diff_permissions(old, new)
    for key in diff["added"]:
        bullet(f"+ {key}", "ADD ")
    for key in diff["unchanged"]:
        bullet(f"= {key}", "SAME")

    step(2, "the loader refuses the upgrade")
    try:
        host.load(FIXTURE)
        ok = False
        bullet("loaded — GOVERNANCE BROKEN", "FAIL")
    except HostError as exc:
        bullet(str(exc)[:190], "DENY")
    bullet(f"still running: classify-ticket@{host.registry.get('classify-ticket').version}")

    step(3, "the review board re-approves the expanded grant, then it loads")
    host.registry.approve(
        Grant(extension="classify-ticket", versions="1.3.*", permissions=new.permissions,
              approver="governance-board", review="GOV-201",
              approved_at="2026-08-13", expires_at="2027-02-13"),
        actor="governance-board",
    )
    host.load(FIXTURE)
    bullet(f"now running: classify-ticket@{host.registry.get('classify-ticket').version}")

    step(4, "credential rotation invalidates outstanding tokens without touching code")
    host.invoke("issue-tracker", {"action": "read", "params": {"ticket_id": "T-1042"}},
                actor="t", tenant="acme")
    killed = host.rotate("secrets/issue-tracker/oauth-client", "rotated-value-2026-08-13")
    bullet(f"handles invalidated by rotation: {killed}")
    bullet("the connector keeps working: it never held the credential in the first place")

    step(5, "kill-switch: an incident pulls the knowledge-base connector host-wide")
    host.invoke("knowledge-base", {"action": "search", "params": {"query": "escalation"}},
                actor="t", tenant="acme")
    outcome = host.kill("knowledge-base", reason="INC-42: poisoned article KB-207",
                        actor="security-oncall")
    bullet(f"kill result: {outcome}")
    bullet(f"outstanding tokens: {len(host.broker.outstanding('knowledge-base@1.1.2'))}")
    bullet(f"capability knowledge_base.search now provided by: "
           f"{host.registry.provider_of('knowledge_base.search')}")

    step(6, "downstream flows degrade instead of silently doing the wrong thing")
    try:
        host.invoke("knowledge-base", {"action": "search", "params": {"query": "x"}},
                    actor="t", tenant="acme")
        ok = False
        bullet("invoked a revoked extension — KILL-SWITCH BROKEN", "FAIL")
    except HostError as exc:
        bullet(str(exc)[:150], "DENY")

    step(7, "reloading a killed extension requires governance clearance")
    try:
        host.load(os.path.join(INTEGRATIONS, "knowledge-base"))
        ok = False
        bullet("reloaded without clearance — BROKEN", "FAIL")
    except HostError as exc:
        bullet(str(exc)[:150], "DENY")
    host.registry.clear_revocation("knowledge-base", actor="governance-board", review="GOV-210")
    host.load(os.path.join(INTEGRATIONS, "knowledge-base"))
    bullet("cleared by the board and reloaded")

    step(8, "deprecation with a successor and a sunset date")
    host.registry.deprecate("cicd-status", successor="cicd-status@1.0.0", sunset="2026-12-01",
                            actor="governance-board")
    row = [r for r in host.registry.inspect() if r["ref"].startswith("cicd-status")][0]
    bullet(f"state={row['state']} successor={row['deprecation']['successor']} "
           f"sunset={row['deprecation']['sunset']} (still serving until then)")

    audit_tail(host, events={"governance.permission_diff", "governance.grant_approved",
                             "governance.kill_switch", "token.rotated", "token.revoked",
                             "governance.revocation_cleared", "governance.deprecated"}, n=10)
    verdict(ok, "expansion blocked, re-approval works, kill-switch revokes, audit records who")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
