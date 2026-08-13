"""`ext` — the extension developer CLI (FR-7).

    python3 -m runtime.cli.ext scaffold my-thing --kind tool
    python3 -m runtime.cli.ext validate integrations/issue-tracker
    python3 -m runtime.cli.ext permissions integrations/triage-agent
    python3 -m runtime.cli.ext test integrations/classify-ticket --input '{"action":"classify","params":{"subject":"double charge","body":"charged twice"}}'
    python3 -m runtime.cli.ext run triage-agent --input '{"ticket_id":"T-1042"}' --execute
    python3 -m runtime.cli.ext list
    python3 -m runtime.cli.ext audit -n 20
    python3 -m runtime.cli.ext kill knowledge-base --reason "poisoned article"

Everything here is deliberately local and offline: an author can go from idea to a
passing contract test without touching a shared environment, which is the whole
point of the adoption plan in adoption-dx/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from runtime.host import contract  # noqa: E402
from runtime.host.errors import HostError  # noqa: E402
from runtime.host.gate import CliConfirmation, ScriptedConfirmation  # noqa: E402
from runtime.host.host import DEFAULT_GRANTS, Host  # noqa: E402
from runtime.host.registry import Registry  # noqa: E402
from runtime.host import yamlio  # noqa: E402

OK, BAD, WARN = "  ok  ", " fail ", " warn "


# --------------------------------------------------------------------------- #
# scaffold
# --------------------------------------------------------------------------- #

MANIFEST_TEMPLATE = """apiVersion: ext/v1
kind: {kind}

metadata:
  name: {name}
  version: 0.1.0
  owner: {owner}
  description: >-
    TODO one or two lines: what does this extension do, and for whom?

runtime:
  type: {runtime}
  entrypoint: handler.py:handle
  timeout_ms: 5000
  network: {network}
{extra_runtime}
capabilities:
  provides:
    - {capability}
  requires: []
{events}
permissions:{permissions}

trust:
  output_class: {output_class}

io:
  input:
    action: string
    params: object
  output:
    result: object

lifecycle:
  on_load: validate_schema
  on_revoke: flush_tokens
  pre_action: authorization_gate
  post_action: audit_emit
"""

HANDLER_TEMPLATE = '''"""{name} — {kind} extension.

Rules of the road (see adoption-dx/README.md):
  * you get no network, no environment variables and no filesystem writes;
  * reach the outside world with ctx.http(...), which the host authorizes and
    credentials for you — you never see a token;
  * call another extension with ctx.call("resource.action", params);
  * never *do* anything privileged: ctx.propose(...) and let the gate decide.
"""


def handle(ctx, payload):
    params = payload.get("params") or {{}}
    ctx.log(f"{name} received {{sorted(params)}}")
    # TODO implement
    return {{"result": {{}}}}
'''

TEST_TEMPLATE = '''"""Local contract test for {name}. Run: python3 -m runtime.cli.ext test {path}"""

SAMPLE_INPUT = {{"action": "TODO", "params": {{}}}}


def check(output):
    """Return a list of problems; empty means pass."""
    problems = []
    if not isinstance(output, dict):
        problems.append("handler must return a dict matching io.output")
    return problems
'''

KIND_DEFAULTS = {
    "tool": dict(
        runtime="local-subprocess",
        network="deny",
        capability="TODO_resource.TODO_action",
        output_class="trusted",
        permissions=" []",
        events="",
        extra_runtime="",
    ),
    "agent": dict(
        runtime="local-subprocess",
        network="deny",
        capability="TODO_domain.TODO_task",
        output_class="untrusted",
        permissions="""
  - resource: TODO_resource
    actions: [read]
    scope:
      tenant: "${caller.tenant}"
    impact: low""",
        events="",
        extra_runtime="",
    ),
    "hook": dict(
        runtime="local-inproc",
        network="deny",
        capability="hook.TODO_name",
        output_class="trusted",
        permissions=" []",
        events="\nevents:\n  - pre_action\n",
        extra_runtime="",
    ),
    "connector": dict(
        runtime="local-subprocess",
        network="broker-only",
        capability="TODO_resource.read",
        output_class="untrusted",
        permissions="""
  - resource: TODO_resource
    actions: [read]
    scope:
      tenant: "${caller.tenant}"
    impact: low""",
        events="",
        extra_runtime="""
egress:
  allow:
    - "TODO.example.internal"

delegated_auth:
  provider: TODO-provider
  flow: authorization_code_pkce
  subject: end_user
  scopes: [TODO.read]
  secret_ref: secrets/TODO/oauth-client
""",
    ),
}


def cmd_scaffold(args) -> int:
    defaults = KIND_DEFAULTS[args.kind]
    target = os.path.join(args.out, args.name)
    if os.path.exists(target):
        print(f"{BAD} {target} already exists")
        return 1
    os.makedirs(target)
    with open(os.path.join(target, "extension.yaml"), "w", encoding="utf-8") as fh:
        fh.write(MANIFEST_TEMPLATE.format(kind=args.kind, name=args.name, owner=args.owner, **defaults))
    with open(os.path.join(target, "handler.py"), "w", encoding="utf-8") as fh:
        fh.write(HANDLER_TEMPLATE.format(name=args.name, kind=args.kind))
    with open(os.path.join(target, "local_test.py"), "w", encoding="utf-8") as fh:
        fh.write(TEST_TEMPLATE.format(name=args.name, path=target))
    with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(
            f"# {args.name}\n\n"
            f"A `{args.kind}` extension. Next steps:\n\n"
            f"1. fill in the TODOs in `extension.yaml` (capabilities, permissions, io)\n"
            f"2. implement `handler.py`\n"
            f"3. `python3 -m runtime.cli.ext validate {target}`\n"
            f"4. `python3 -m runtime.cli.ext test {target}`\n"
            f"5. open a proposal (governance/templates/extension-proposal.md)\n"
        )
    print(f"{OK} scaffolded {args.kind} at {target}")
    print("       next: ext validate → ext test → proposal → review → publish")
    return 0


# --------------------------------------------------------------------------- #
# validate / permissions
# --------------------------------------------------------------------------- #


def cmd_validate(args) -> int:
    path = os.path.join(args.path, "extension.yaml")
    try:
        ext = contract.load_manifest(path)
    except HostError as exc:
        print(f"{BAD} {exc}")
        return 1
    print(f"{OK} {ext.kind} {ext.ref} owned by {ext.owner}")
    print(f"       runtime      {ext.runtime.type} network={ext.runtime.network}")
    print(f"       provides     {', '.join(ext.provides)}")
    print(f"       requires     {', '.join(ext.requires) or '-'}")
    print(f"       egress       {', '.join(ext.egress_allow) or 'none'}")
    print(f"       output class {ext.output_class}")
    for perm in ext.permissions:
        impacts = sorted({perm.effective_impact(a) for a in perm.actions})
        print(f"       permission   {perm.key()}  impact={','.join(impacts)}")
    if not os.path.exists(os.path.join(args.path, "handler.py")) and ext.runtime.type != "remote-rpc":
        print(f"{WARN} no handler.py next to the manifest")
    return 0


def cmd_permissions(args) -> int:
    ext = contract.load_manifest(os.path.join(args.path, "extension.yaml"))
    registry = Registry(audit=_null_audit())
    registry.load_grants(args.grants)
    grant = registry.grant_for(ext)
    requested = ext.permission_keys()
    if grant is None:
        print(f"{BAD} no approved grant covers {ext.ref}")
        for key in sorted(requested):
            print(f"       + {key}   (needs approval)")
        return 1
    approved = grant.keys()
    print(f"       grant {grant.review} approved by {grant.approver} for versions {grant.versions}")
    for key in sorted(requested | approved):
        if key in requested and key in approved:
            print(f"{OK} = {key}")
        elif key in requested:
            print(f"{BAD} + {key}   EXPANSION — re-approval required")
        else:
            print(f"{WARN} - {key}   approved but no longer requested (candidate for revocation)")
    return 0 if requested <= approved else 1


# --------------------------------------------------------------------------- #
# test / run / inspect
# --------------------------------------------------------------------------- #


def cmd_test(args) -> int:
    rc = cmd_validate(args)
    if rc:
        return rc
    ext = contract.load_manifest(os.path.join(args.path, "extension.yaml"))
    host = Host.bootstrap(integrations_dir=None)
    try:
        host.load(args.path)
    except HostError as exc:
        print(f"{BAD} load refused: {exc}")
        return 1
    print(f"{OK} loaded into an isolated host (grants from {os.path.basename(args.grants)})")

    payload = json.loads(args.input) if args.input else _sample_input(args.path)
    if payload is None:
        print(f"{WARN} no --input and no SAMPLE_INPUT in local_test.py; skipping smoke run")
        return 0
    try:
        result = host.invoke(ext.name, payload, actor="local-dev", tenant=args.tenant)
    except HostError as exc:
        print(f"{BAD} smoke run failed: {exc}")
        return 1
    print(f"{OK} smoke run returned: {json.dumps(result.value, default=str)[:400]}")
    if result.proposals:
        print(f"       {len(result.proposals)} proposal(s) returned unexecuted (correct)")
    for record in host.audit.find("gate.denied"):
        print(f"{WARN} gate denied {record.payload.get('resource')}:{record.payload.get('action')}")
    print(f"{OK} audit chain valid: {host.audit.verify()}")
    return 0


def cmd_run(args) -> int:
    confirmation = CliConfirmation() if args.confirm else None
    if args.approve_all:
        confirmation = ScriptedConfirmation({}, default=True)
    host = Host.bootstrap(confirmation=confirmation)
    payload = json.loads(args.input) if args.input else {}
    ext = host.registry.get(args.name)
    if ext.kind == "agent":
        result = host.run_agent(
            args.name, payload, actor=args.actor, tenant=args.tenant, execute=args.execute
        )
        print(json.dumps(result.value, indent=2, default=str))
        print("\nproposals:")
        for outcome in result.outcomes:
            mark = OK if outcome.allowed else BAD
            print(f"{mark} {outcome.proposal['resource']}:{outcome.proposal['action']} "
                  f"({outcome.impact}) {'; '.join(outcome.reasons)[:120]}")
    else:
        result = host.invoke(args.name, payload, actor=args.actor, tenant=args.tenant)
        print(json.dumps(result.value, indent=2, default=str))
    print(f"\ntaint: {result.taint.label} sources={result.taint.sources}")
    return 0


def cmd_list(args) -> int:
    host = Host.bootstrap()
    print(host.registry.render())
    return 0


def cmd_audit(args) -> int:
    host = Host.bootstrap()
    if args.name:
        host.run_agent(args.name, json.loads(args.input or "{}"), execute=False)
    print(host.audit.render(args.n))
    print(f"\nchain valid: {host.audit.verify()}  records: {len(host.audit.records)}")
    return 0


def cmd_kill(args) -> int:
    host = Host.bootstrap()
    outcome = host.kill(args.name, reason=args.reason, actor=args.actor)
    print(f"{OK} kill-switch: {json.dumps(outcome)}")
    print(host.registry.render())
    return 0


# --------------------------------------------------------------------------- #


def _sample_input(path: str):
    local = os.path.join(path, "local_test.py")
    if not os.path.exists(local):
        return None
    namespace: dict = {}
    with open(local, "r", encoding="utf-8") as fh:
        exec(compile(fh.read(), local, "exec"), namespace)  # noqa: S102 - author's own test file
    return namespace.get("SAMPLE_INPUT")


def _null_audit():
    from runtime.host.audit import AuditLog

    return AuditLog()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ext", description="extension developer CLI")
    parser.add_argument("--grants", default=DEFAULT_GRANTS, help="approved grants file")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scaffold", help="generate a new extension skeleton")
    p.add_argument("name")
    p.add_argument("--kind", choices=sorted(KIND_DEFAULTS), default="tool")
    p.add_argument("--owner", default="team-TODO")
    p.add_argument("--out", default="integrations")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("validate", help="validate a manifest against ext/v1")
    p.add_argument("path")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("permissions", help="diff requested vs approved permissions")
    p.add_argument("path")
    p.set_defaults(func=cmd_permissions)

    p = sub.add_parser("test", help="validate, load in an isolated host, smoke run")
    p.add_argument("path")
    p.add_argument("--input", default="")
    p.add_argument("--tenant", default="acme")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("run", help="run a loaded extension")
    p.add_argument("name")
    p.add_argument("--input", default="{}")
    p.add_argument("--actor", default="local-dev")
    p.add_argument("--tenant", default="acme")
    p.add_argument("--execute", action="store_true", help="execute allowed proposals")
    p.add_argument("--confirm", action="store_true", help="prompt for confirmations")
    p.add_argument("--approve-all", action="store_true", help="DEMO ONLY: auto-confirm")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="inspect loaded extensions, versions, permissions")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("audit", help="show the audit trail")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--name", default="", help="optionally run an agent first")
    p.add_argument("--input", default="")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("kill", help="kill-switch an extension")
    p.add_argument("name")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="security-oncall")
    p.set_defaults(func=cmd_kill)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
