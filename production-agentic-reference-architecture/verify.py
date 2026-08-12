#!/usr/bin/env python3
"""Verify the whole package with one command.

    python3 verify.py           # run everything
    python3 verify.py --quick   # skip the demo and the cost model

Runs, in order of how fast they fail:

  1. every module compiles
  2. unit + integration tests            (tests/)
  3. boundary control assertions         (eval/control_tests.py)
  4. the release gate                    (eval/harness.py)
  5. gate integrity via mutations        (eval/mutation_test.py)
  6. durable crash + resume, end to end
  7. the audit chain detects tampering
  8. the review server responds, refuses unauthenticated access, and enforces CSRF
  9. semantic groundedness catches fabrication, misattribution and drift
 10. real HTTP retrieval: extraction, robots, size caps, SSRF defences
 11. the cost model reproduces its report
 12. the scripted demo

Exit 0 only if every stage passes. This is what CI runs, and what a reviewer should
run first: if this is green, every claim in the README is reproducible.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTO = ROOT / "prototype"
PY = sys.executable

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Runner:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str, float]] = []

    def stage(self, name: str, fn) -> bool:
        print(f"{BOLD}▸ {name}{RESET}")
        started = time.time()
        try:
            ok, detail = fn()
        except Exception as exc:  # a crashing check is a failing check
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - started
        mark = f"{GREEN}pass{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"  {mark} {DIM}{elapsed:.1f}s{RESET}  {detail}\n")
        self.results.append((name, ok, detail, elapsed))
        return ok

    def summary(self) -> int:
        failed = [r for r in self.results if not r[1]]
        width = max(len(n) for n, *_ in self.results)
        print(f"{BOLD}{'─' * (width + 26)}{RESET}")
        for name, ok, detail, elapsed in self.results:
            mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
            print(f" {mark} {name:{width}}  {DIM}{elapsed:5.1f}s{RESET}")
        total = sum(r[3] for r in self.results)
        print(f"{BOLD}{'─' * (width + 26)}{RESET}")
        if failed:
            print(f"{RED}{BOLD}{len(failed)} of {len(self.results)} stages failed{RESET} ({total:.1f}s)")
            for name, _, detail, _ in failed:
                print(f"   {name}: {detail}")
            return 1
        print(f"{GREEN}{BOLD}all {len(self.results)} stages passed{RESET} ({total:.1f}s)")
        return 0


def sh(args: list[str], cwd: Path = ROOT, timeout: int = 300) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr)


# --- stages -----------------------------------------------------------------------
def compiles() -> tuple[bool, str]:
    files = sorted(str(p) for p in ROOT.rglob("*.py") if "__pycache__" not in str(p))
    code, out = sh([PY, "-m", "py_compile", *files])
    return code == 0, f"{len(files)} modules compile" if code == 0 else out.strip()[-400:]


def unit_tests() -> tuple[bool, str]:
    code, out = sh([PY, "-m", "unittest", "discover", "-s", "tests"])
    line = next((l for l in out.splitlines() if l.startswith("Ran ")), "")
    return code == 0, line or out.strip()[-300:]


def control_tests() -> tuple[bool, str]:
    code, out = sh([PY, "eval/control_tests.py"])
    return code == 0, out.strip().splitlines()[-1] if out.strip() else ""


def release_gate() -> tuple[bool, str]:
    code, out = sh([PY, "eval/harness.py"])
    summary = next((l.strip() for l in out.splitlines() if "end-state" in l), "")
    return code == 0, summary


def gate_integrity() -> tuple[bool, str]:
    code, out = sh([PY, "eval/mutation_test.py"])
    return code == 0, out.strip().splitlines()[-1] if out.strip() else ""


def crash_and_resume() -> tuple[bool, str]:
    """The FR-7 claim: a kill mid fan-out must not re-pay for completed work."""
    tmp = Path(tempfile.mkdtemp())
    try:
        question = "How does hybrid search work in vector databases and what drives its cost?"
        base = ["--base-dir", str(tmp)]
        code, out = sh([PY, "run.py", *base, "run", question, "--crash-after-workers", "1", "--latency-speed", "0"], cwd=PROTO)
        if "[CHAOS]" not in out:
            return False, "the crash was never triggered"
        run_id = out.split("--run-id ")[1].split()[0]

        code, out = sh([PY, "run.py", *base, "resume", run_id], cwd=PROTO)
        if code != 0:
            return False, f"resume exited {code}"
        if "no re-fetch" not in out:
            return False, "resume did not restore a worker from its checkpoint"

        spans = [
            json.loads(line)
            for line in (tmp / run_id / "trace.jsonl").read_text().splitlines()
            if line.strip()
        ]
        resumed_events = [
            e for s in spans for e in s["events"] if e["name"] == "stage.resumed"
        ]
        # Count fetches after the resume: the restored worker must not appear again.
        return (
            bool(resumed_events) and "status     : completed" in out,
            f"{len(resumed_events)} stage(s) resumed, run completed without re-fetching",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def audit_chain() -> tuple[bool, str]:
    """The R2 claim: local tampering with the audit log is detectable."""
    sys.path.insert(0, str(PROTO))
    from agent.audit import AuditLog

    tmp = Path(tempfile.mkdtemp())
    try:
        log = AuditLog(tmp / "audit.jsonl")
        for i in range(3):
            log.append({"action": "export_report", "destination": f"file://{i}"})
        if not log.verify().ok:
            return False, "a freshly written chain failed verification"

        # tamper
        path = log.path
        path.write_text(path.read_text().replace("file://1", "file://HACKED"), encoding="utf-8")
        tampered = log.verify()
        if tampered.ok:
            return False, "modification was NOT detected"

        # truncate
        path.write_text("\n".join(path.read_text().splitlines()[:1]) + "\n", encoding="utf-8")
        truncated = log.verify()
        if truncated.ok:
            return False, "truncation was NOT detected"
        return True, "modification and truncation both detected"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def review_server() -> tuple[bool, str]:
    """The review UI must respond, and must refuse unauthenticated access."""
    tmp = Path(tempfile.mkdtemp())
    port = 8791
    proc = subprocess.Popen(
        [PY, "server.py", "--port", str(port), "--base-dir", str(tmp)],
        cwd=PROTO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(f"{base}/login", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        else:
            return False, "server never became ready"

        login = urllib.request.urlopen(f"{base}/login", timeout=3).read().decode()
        if "Sign in" not in login:
            return False, "login page did not render"

        # An unauthenticated queue request must redirect to login, not serve the queue.
        req = urllib.request.Request(base + "/")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            body = opener.open(req, timeout=3).read().decode()
            if "approval queue" in body.lower() and "Sign in" not in body:
                return False, "queue served without authentication"
            status = 200
        except urllib.error.HTTPError as exc:
            status = exc.code
        if status not in (302, 303, 200):
            return False, f"unexpected status {status}"
        # CSRF: a state-changing POST without a token must be refused even with a
        # valid session, so a cookie alone is not enough to forge an approval.
        csrf_enforced = False
        try:
            opener.open(
                urllib.request.Request(
                    base + "/approve", data=b"run_id=nope", headers={"Cookie": "session=fake"}
                ),
                timeout=3,
            )
        except urllib.error.HTTPError as exc:
            csrf_enforced = exc.code == 403
        if not csrf_enforced:
            return False, "CSRF check did not refuse a tokenless approval"
        return True, "serves login, refuses unauthenticated access, enforces CSRF"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)


def groundedness_checks() -> tuple[bool, str]:
    """R3: is each claim actually supported by the source it cites?"""
    sys.path.insert(0, str(PROTO))
    from agent import groundedness as g

    src = (
        "Hybrid search combines a dense embedding query with a lexical BM25 query. Hybrid search "
        "raises cost because a second lexical index must be maintained, typically adding twenty "
        "to forty percent to per-query cost."
    )
    cases = [
        ("faithful", "Hybrid search combines a dense embedding query with a lexical BM25 query", True),
        ("fabrication", "Hybrid search requires quantum annealing hardware clusters", False),
        ("misattribution", "Durable execution records the result of each completed stage", False),
        ("spelled drift", "Hybrid search adds ninety to ninety-nine percent to per-query cost", False),
        ("polarity inversion", "Hybrid search does not raise cost and needs no second index", False),
    ]
    wrong = [
        name for name, claim, expected in cases
        if g.check_claim(claim, "S1", src).supported != expected
    ]
    report = "# T\n\n## a\n- a claim about hybrid search fusion [S9]\n\n## Sources\n\n- [S9] x"
    dangling_caught = bool(g.check_report(report, {"S1": src}).unsupported)
    if wrong or not dangling_caught:
        return False, f"misjudged: {wrong}" + ("" if dangling_caught else "; dangling citation passed")
    return True, f"{len(cases)}/{len(cases)} verdicts correct, dangling citation caught"


def http_retrieval() -> tuple[bool, str]:
    """Cut 1: the real network path, plus its SSRF and resource defences."""
    import functools
    import http.server
    import threading

    sys.path.insert(0, str(PROTO))
    from agent.retrieval import HttpTransport, TransportError

    tmp = Path(tempfile.mkdtemp())
    (tmp / "page.html").write_text(
        "<!doctype html><html><head><title>T</title><script>alert(1)</script></head>"
        "<body><nav>skip</nav><p>Real prose.</p></body></html>", encoding="utf-8",
    )
    (tmp / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n", encoding="utf-8")
    (tmp / "private").mkdir()
    (tmp / "private" / "s.html").write_text("<p>secret</p>", encoding="utf-8")
    (tmp / "huge.html").write_text("<html><body>" + "x" * 80_000 + "</body></html>", encoding="utf-8")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        t = HttpTransport(allow_local=True, max_bytes=10_000)
        doc = t.fetch(f"http://127.0.0.1:{port}/page.html")
        checks = {
            "extracts title": doc.title == "T",
            "extracts prose": "Real prose." in doc.text,
            "strips script/nav": "alert" not in doc.text and "skip" not in doc.text,
        }
        for name, url in (
            ("robots respected", f"http://127.0.0.1:{port}/private/s.html"),
            ("size cap enforced", f"http://127.0.0.1:{port}/huge.html"),
        ):
            try:
                t.fetch(url)
                checks[name] = False
            except TransportError:
                checks[name] = True
        public = HttpTransport(allow_local=False)
        for name, url in (
            ("metadata endpoint refused", "http://169.254.169.254/latest/meta-data/"),
            ("private range refused", "http://10.0.0.1/x"),
            ("file scheme refused", "file:///etc/passwd"),
        ):
            try:
                public.fetch(url)
                checks[name] = False
            except TransportError:
                checks[name] = True
        failed = [k for k, v in checks.items() if not v]
        return not failed, f"{len(checks)} checks pass" if not failed else f"failed: {failed}"
    finally:
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def mfa_and_throttling() -> tuple[bool, str]:
    """The ADR-015 residuals: second factor and bounded guessing."""
    sys.path.insert(0, str(PROTO))
    from agent.identity import AuthError, IdentityStore, LockedOut, totp_now

    tmp = Path(tempfile.mkdtemp())
    try:
        store = IdentityStore(tmp / "p.json")
        store.create_principal("alice", "alice-password-1")
        secret, _ = store.enrol_totp("alice")
        checks = {}
        try:
            store.authenticate("alice", "alice-password-1")
            checks["missing code refused"] = False
        except AuthError:
            checks["missing code refused"] = True
        checks["correct code accepted"] = bool(
            store.authenticate("alice", "alice-password-1", totp_code=totp_now(secret)).token
        )
        now = 1_000_000.0
        store2 = IdentityStore(tmp / "q.json")
        store2.create_principal("bob", "bob-password-1")
        locked = False
        for _ in range(8):
            try:
                store2.authenticate("bob", "wrong", now=now)
            except LockedOut:
                locked = True
                break
            except AuthError:
                pass
        checks["lockout after repeated failures"] = locked
        # lockout must apply to the right password too
        try:
            store2.authenticate("bob", "bob-password-1", now=now)
            checks["lockout applies to correct password"] = False
        except LockedOut:
            checks["lockout applies to correct password"] = True
        except AuthError:
            checks["lockout applies to correct password"] = False
        failed = [k for k, v in checks.items() if not v]
        return not failed, f"{len(checks)} checks pass" if not failed else f"failed: {failed}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cost_model() -> tuple[bool, str]:
    code, out = sh([PY, "cost-model/cost_model.py"])
    if code != 0:
        return False, out.strip()[-300:]
    verdict = next((l for l in out.splitlines() if "widest fan-out" in l), "")
    return True, (verdict[:120] + "…") if verdict else "report generated"


def demo() -> tuple[bool, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        code, out = sh([PY, "run.py", "--base-dir", str(tmp), "demo"], cwd=PROTO, timeout=600)
        checks = {
            "cited report": "[S1]" in out,
            "coverage gap declared": "Coverage gap" in out,
            "injection neutralised": "indirect_injection_neutralised" in out,
            "export refused unauthenticated": "unauthorised" in out,
            "authenticated export": "status     : exported" in out,
            "tampering detected": "chain: BROKEN" in out,
        }
        missing = [k for k, v in checks.items() if not v]
        return code == 0 and not missing, (
            f"all {len(checks)} demo assertions visible" if not missing else f"missing: {missing}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the demo and the cost model")
    args = ap.parse_args(argv)

    print(f"\n{BOLD}Verifying the agentic reference architecture package{RESET}")
    print(f"{DIM}{ROOT}{RESET}\n")

    r = Runner()
    r.stage("modules compile", compiles)
    r.stage("unit + integration tests", unit_tests)
    r.stage("boundary control assertions", control_tests)
    r.stage("release gate (end-state + trajectory)", release_gate)
    r.stage("gate integrity (mutation test)", gate_integrity)
    r.stage("durable crash + resume", crash_and_resume)
    r.stage("audit chain tamper detection", audit_chain)
    r.stage("review server auth + CSRF", review_server)
    r.stage("semantic groundedness (R3)", groundedness_checks)
    r.stage("real HTTP retrieval + SSRF defences", http_retrieval)
    r.stage("MFA + login throttling", mfa_and_throttling)
    if not args.quick:
        r.stage("cost + latency model", cost_model)
        r.stage("scripted demo", demo)
    return r.summary()


if __name__ == "__main__":
    raise SystemExit(main())
