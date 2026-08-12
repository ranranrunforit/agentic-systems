#!/usr/bin/env python3
"""CLI for the orchestration spike.

    python run.py demo                                  # scripted end-to-end tour
    python run.py run "<question>" [--export file://reports/out.md]
    python run.py approve <run_id> --principal reviewer --password <pw>
    python run.py reject  <run_id> --principal reviewer --password <pw>
    python run.py principals add <id> --password <pw>    # manage approvers
    python run.py audit <run_id>                          # verify the audit chain
    python run.py serve                                   # HITL review web UI
    python run.py resume  <run_id>                       # after a crash
    python run.py list                                   # durable run states
    python run.py trace   <run_id>                       # on-call trace tree
    python run.py tools                                  # typed tool registry

See RUNNING.md. Dependency-free: standard library only.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent import TOOL_REGISTRY_SPEC, Orchestrator, RunConfig  # noqa: E402
from agent.audit import AuditLog  # noqa: E402
from agent.checkpoint import CheckpointStore  # noqa: E402
from agent.identity import (  # noqa: E402
    SCOPE_APPROVE_EXPORT,
    SCOPE_VIEW,
    AuthError,
    bootstrap,
)
from agent.tracing import Tracer, load_trace  # noqa: E402

DEFAULT_BASE = Path(__file__).parent / "runs"


def _cfg(args: argparse.Namespace, **over) -> RunConfig:
    return RunConfig(
        question=over.pop("question", getattr(args, "question", "")),
        run_id=over.pop("run_id", getattr(args, "run_id", None)),
        base_dir=Path(getattr(args, "base_dir", DEFAULT_BASE)),
        max_fanout=getattr(args, "max_fanout", 3),
        workers_top_k=getattr(args, "top_k", 1),
        per_task_cost_ceiling_usd=getattr(args, "cost_ceiling", 0.05),
        export_destination=getattr(args, "export", None),
        fail_urls=set(getattr(args, "fail_url", []) or []),
        crash_after_workers=getattr(args, "crash_after_workers", None),
        model_backend=getattr(args, "model_backend", "deterministic"),
        latency_speed=getattr(args, "latency_speed", 1.0),
        routing={"plan": "small", "summarize": "small", "guard": "small", "synthesize": "small"}
        if getattr(args, "all_small", False)
        else None,
        simulate_compromised_model=getattr(args, "simulate_compromised_model", False),
        retrieval=getattr(args, "retrieval", "fixture"),
        search_endpoint=getattr(args, "search_endpoint", None),
        allow_local_http=getattr(args, "allow_local_http", False),
        max_evidence_per_subquestion=getattr(args, "evidence_per_subquestion", 2),
        **over,
    )


def _print_result(orch: Orchestrator, result) -> None:
    print("\n" + "=" * 78)
    print(f"run_id     : {result.run_id}")
    print(f"status     : {result.status}" + (f"  ({', '.join(result.reasons)})" if result.reasons else ""))
    print(f"cost       : ${result.cost_usd:.5f} cumulative"
          f"  (this session ${result.stats['session_cost_usd']:.5f}; ceiling ${result.stats['cost_ceiling_usd']:.5f})")
    print(f"tokens     : in={result.input_tokens} out={result.output_tokens}")
    print(f"latency    : {result.latency_ms:.0f} ms")
    print(f"fan-out    : {result.stats['fanout_width']} workers, {result.stats['paid_fetches']} paid fetch(es)")
    ground = next(
        (s for s in orch.tracer.spans if s.name == "guardrail.groundedness"), None
    )
    if ground:
        checked = ground.attributes.get("groundedness.claims_checked", 0)
        bad = ground.attributes.get("groundedness.claims_unsupported", 0)
        print(f"grounded   : {checked - bad}/{checked} claims verified against the source they cite")
    print(f"budget est : {result.stats.get('cost_estimate_source', 'seed_constants')}")
    if result.failed_subquestions:
        print(f"degraded   : {len(result.failed_subquestions)} sub-question(s) without evidence")
    if result.coverage_gaps:
        print(f"gaps       : {result.coverage_gaps}")
    for g in result.guardrail_events:
        if g["reasons"]:
            print(f"guardrail  : {g['control']} allowed={g['allowed']} {g['reasons']}")
    print("=" * 78)
    print("\n--- trace tree " + "-" * 63)
    print(orch.tracer.render_tree())
    if result.report_markdown:
        print("\n--- report " + "-" * 67)
        print(result.report_markdown)


def cmd_run(args: argparse.Namespace) -> int:
    orch = Orchestrator(_cfg(args))
    result = orch.run()
    _print_result(orch, result)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    store = CheckpointStore(Path(args.base_dir) / "durable.sqlite3")
    run = store.get_run(args.run_id)
    if run is None:
        print(f"no such run: {args.run_id}", file=sys.stderr)
        return 2
    print(f"[resume] {args.run_id} status={run['status']} stages={list(store.stages(args.run_id))}")
    orch = Orchestrator(_cfg(args, question=run["question"], run_id=args.run_id))
    result = orch.run()
    _print_result(orch, result)
    return 0


def _authenticate(args: argparse.Namespace) -> str | None:
    """Exchange credentials for a session token (threat-model R1).

    The password may come from --password or the AGENT_APPROVER_PASSWORD env var;
    the env var is preferred because a password in argv is visible in `ps`.
    """
    base = Path(args.base_dir)
    identity, seeded = bootstrap(base / "principals.json")
    if seeded:
        print(f"\n  Seeded principal 'reviewer' with password: {seeded}")
        print("  (shown once — capture it, or delete principals.json to reseed)\n")
    password = args.password or os.environ.get("AGENT_APPROVER_PASSWORD", "")
    if not password:
        password = getpass.getpass(f"password for {args.principal}: ")
    try:
        return identity.authenticate(args.principal, password).token
    except AuthError as exc:
        print(f"authentication failed: {exc}", file=sys.stderr)
        return None


def _gate(args: argparse.Namespace, action: str) -> int:
    store = CheckpointStore(Path(args.base_dir) / "durable.sqlite3")
    run = store.get_run(args.run_id)
    if run is None:
        print(f"no such run: {args.run_id}", file=sys.stderr)
        return 2
    token = _authenticate(args)
    if token is None:
        return 3
    orch = Orchestrator(_cfg(args, question=run["question"], run_id=args.run_id))
    result = orch.approve(session_token=token) if action == "approve" else orch.reject(session_token=token)
    _print_result(orch, result)
    return 0 if result.status in ("exported", "rejected") else 1


def cmd_approve(args: argparse.Namespace) -> int:
    return _gate(args, "approve")


def cmd_reject(args: argparse.Namespace) -> int:
    return _gate(args, "reject")


def cmd_principals(args: argparse.Namespace) -> int:
    base = Path(args.base_dir)
    identity, _ = bootstrap(base / "principals.json")
    if args.action == "list":
        for p in identity.list_principals():
            print(f"{p.principal_id:20} {p.display_name:24} {','.join(p.scopes)}")
        return 0
    password = args.password or os.environ.get("AGENT_APPROVER_PASSWORD") or getpass.getpass("new password: ")
    scopes = [SCOPE_VIEW] + ([SCOPE_APPROVE_EXPORT] if not args.view_only else [])
    try:
        p = identity.create_principal(args.principal_id, password, display_name=args.display_name, scopes=scopes)
    except AuthError as exc:
        print(f"could not create principal: {exc}", file=sys.stderr)
        return 2
    print(f"created {p.principal_id} with scopes {','.join(p.scopes)}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Verify the tamper-evident audit chain for a run (threat-model R2)."""
    log = AuditLog(Path(args.base_dir) / args.run_id / "audit.jsonl")
    v = log.verify()
    for rec in log.read():
        print(
            f"  seq {rec['seq']:<3} {rec.get('action')} → {rec.get('destination')}\n"
            f"      approved_by={rec.get('approved_by')} authenticated={rec.get('authenticated')}\n"
            f"      hash={rec['hash'][:16]} prev={rec['prev_hash'][:16]}"
        )
    print(f"\n  {v.records} record(s); chain {'INTACT' if v.ok else 'BROKEN'}")
    for problem in v.problems:
        print(f"    ! {problem}")
    return 0 if v.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import server

    return server.main(["--base-dir", str(args.base_dir), "--port", str(args.port)])


def cmd_list(args: argparse.Namespace) -> int:
    store = CheckpointStore(Path(args.base_dir) / "durable.sqlite3")
    rows = store.list_runs()
    if not rows:
        print("(no runs yet)")
        return 0
    print(f"{'run_id':34} {'status':20} question")
    for r in rows:
        print(f"{r['run_id']:34} {r['status']:20} {r['question'][:60]}")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    path = Path(args.base_dir) / args.run_id / "trace.jsonl"
    spans = load_trace(path)
    if not spans:
        print(f"no trace at {path}", file=sys.stderr)
        return 2
    tracer = Tracer(trace_id=spans[0]["trace_id"])
    from agent.tracing import Span

    for s in spans:
        span = Span(
            trace_id=s["trace_id"], span_id=s["span_id"], parent_id=s["parent_id"], name=s["name"],
            kind=s["kind"], start_ms=s["start_ms"], end_ms=s["end_ms"], status=s["status"],
            attributes=s["attributes"], events=s["events"],
        )
        tracer.spans.append(span)
    print(tracer.render_tree())
    print(f"\ntotal cost ${tracer.total_cost_usd():.5f}; tokens in/out {tracer.total_tokens()}")
    return 0


def cmd_tools(_args: argparse.Namespace) -> int:
    print(json.dumps(TOOL_REGISTRY_SPEC, indent=2))
    return 0


DEMO_QUESTION = (
    "What are the reliability trade-offs of orchestrator-workers topologies "
    "versus single-agent ReAct loops?"
)


def cmd_demo(args: argparse.Namespace) -> int:
    """Scripted tour: happy path, degraded path, injection probe, HITL export."""
    base = Path(args.base_dir)

    def header(n: str) -> None:
        print("\n\n" + "#" * 78 + f"\n# {n}\n" + "#" * 78)

    header("1/4  Happy path — plan, parallel fan-out, cited synthesis, read-only return")
    o1 = Orchestrator(RunConfig(question=DEMO_QUESTION, base_dir=base))
    _print_result(o1, o1.run())

    header("2/4  Degraded path — one source is down; coverage gap is declared, not hidden")
    o2 = Orchestrator(
        RunConfig(
            question=DEMO_QUESTION,
            base_dir=base,
            fail_urls={"https://research.example.org/react-single-agent-limits"},
        )
    )
    _print_result(o2, o2.run())

    header("3/4  Adversarial — injected source tells the agent to export to an attacker URL")
    o3 = Orchestrator(
        RunConfig(
            question="How do agent teams control inference cost, and what benchmarks exist for 2026?",
            base_dir=base,
            simulate_compromised_model=True,
        )
    )
    _print_result(o3, o3.run())

    header("4/4  HITL — authenticated approval, audited export, tamper-evident chain")
    o4 = Orchestrator(
        RunConfig(question=DEMO_QUESTION, base_dir=base, export_destination="file://reports/demo.md")
    )
    r4 = o4.run()
    _print_result(o4, r4)

    # Approval requires an authenticated principal (threat-model R1). The demo
    # provisions one so the path is exercised end to end rather than bypassed.
    from agent.identity import IdentityStore

    identity = IdentityStore(base / "principals.json")
    try:
        identity.principal("demo-reviewer")
    except AuthError:
        identity.create_principal("demo-reviewer", "demo-password-1234", display_name="Demo reviewer")

    print("\n-- an unauthenticated approval attempt is refused --")
    o_bad = Orchestrator(RunConfig(question=DEMO_QUESTION, run_id=r4.run_id, base_dir=base, quiet=True))
    bad = o_bad.approve(session_token="not-a-real-session")
    print(f"   status={bad.status}  reasons={bad.reasons}")

    print("\n-- authenticated approval --")
    token = identity.authenticate("demo-reviewer", "demo-password-1234").token
    o5 = Orchestrator(
        RunConfig(question=DEMO_QUESTION, run_id=r4.run_id, base_dir=base), identity=identity
    )
    r5 = o5.approve(session_token=token)
    _print_result(o5, r5)

    print("\n-- audit chain verification --")
    log = AuditLog(base / r4.run_id / "audit.jsonl")
    v = log.verify()
    for rec in log.read():
        print(
            f"   seq {rec['seq']} {rec['action']} approved_by={rec['approved_by']} "
            f"authenticated={rec['authenticated']} hash={rec['hash'][:12]}"
        )
    print(f"   chain: {'INTACT' if v.ok else 'BROKEN — ' + '; '.join(v.problems)}")

    print("\n-- now tamper with the record and re-verify --")
    path = base / r4.run_id / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"destination": "file://reports/demo.md"', '"destination": "file://reports/HACKED.md"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    v2 = AuditLog(path).verify()
    print(f"   chain: {'INTACT' if v2.ok else 'BROKEN'}")
    for problem in v2.problems:
        print(f"     ! {problem}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", default=str(DEFAULT_BASE), help="where runs/, checkpoints and traces live")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a research task")
    r.add_argument("question")
    r.add_argument("--run-id")
    r.add_argument("--export", help="export destination, e.g. file://reports/out.md (triggers HITL)")
    r.add_argument("--max-fanout", type=int, default=3, help="derived from the cost model; 8 is the hard cap")
    r.add_argument("--top-k", type=int, default=1, help="sources fetched per sub-question")
    r.add_argument("--cost-ceiling", type=float, default=0.05, help="per-task USD ceiling")
    r.add_argument("--fail-url", action="append", help="force a tool outage for this URL (chaos drill)")
    r.add_argument("--crash-after-workers", type=int, help="kill the process after N worker checkpoints")
    r.add_argument("--model-backend", default="deterministic", choices=["deterministic", "anthropic"])
    r.add_argument("--latency-speed", type=float, default=1.0, help="0 = no simulated latency")
    r.add_argument("--all-small", action="store_true", help="route synthesis to the small model too")
    r.add_argument("--simulate-compromised-model", action="store_true")
    r.add_argument(
        "--retrieval", default="fixture", choices=["fixture", "http"],
        help="fixture (default, deterministic, offline) or http (real network)",
    )
    r.add_argument("--search-endpoint", help="JSON search provider for --retrieval http")
    r.add_argument(
        "--allow-local-http", action="store_true",
        help="permit http to loopback (testing the real transport); off by default",
    )
    r.add_argument(
        "--evidence-per-subquestion", type=int, default=2,
        help="cost lever L3: summaries per sub-question reaching synthesis (default 2, derived in ADR-016)",
    )
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("resume", help="resume a crashed run from its last checkpoint")
    s.add_argument("run_id")
    s.add_argument("--export")
    s.set_defaults(func=cmd_resume)

    for name, fn, helptext in (
        ("approve", cmd_approve, "approve the one write action (requires an authenticated principal)"),
        ("reject", cmd_reject, "reject a pending export (also authenticated)"),
    ):
        g = sub.add_parser(name, help=helptext)
        g.add_argument("run_id")
        g.add_argument("--principal", default="reviewer", help="authenticated principal id")
        g.add_argument(
            "--password",
            help="prefer AGENT_APPROVER_PASSWORD or the interactive prompt; argv is visible in ps",
        )
        g.set_defaults(func=fn)

    pr = sub.add_parser("principals", help="manage approver principals")
    pr.add_argument("action", choices=["list", "add"])
    pr.add_argument("principal_id", nargs="?")
    pr.add_argument("--password")
    pr.add_argument("--display-name")
    pr.add_argument("--view-only", action="store_true", help="omit the approve:export scope")
    pr.set_defaults(func=cmd_principals)

    au = sub.add_parser("audit", help="verify a run's tamper-evident audit chain")
    au.add_argument("run_id")
    au.set_defaults(func=cmd_audit)

    sv = sub.add_parser("serve", help="HITL review web UI on localhost")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)

    sub.add_parser("list", help="list durable runs").set_defaults(func=cmd_list)

    t = sub.add_parser("trace", help="print the trace tree for a run")
    t.add_argument("run_id")
    t.set_defaults(func=cmd_trace)

    sub.add_parser("tools", help="print the typed tool registry").set_defaults(func=cmd_tools)
    sub.add_parser("demo", help="scripted end-to-end tour").set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
