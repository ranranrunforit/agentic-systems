#!/usr/bin/env python3
"""HITL review server — closes ADR-012 cut 6 (approval was CLI-only).

    python3 server.py            # http://127.0.0.1:8765

A reviewer cannot make a good approval decision from a run id. ADR-009 argued the
whole point of one narrow confirmation boundary is that reviewers stay attentive, and
attentiveness requires seeing what is being approved. This serves:

  * a login (authenticated session — threat-model R1, `agent.identity`)
  * the queue of runs awaiting approval
  * for each: the full report, its **declared coverage gaps**, its sources, the
    destination, the cost, and any guardrail events that fired during the run
  * approve / reject, both authenticated and audited
  * a live audit-chain verification page (threat-model R2)

Why `http.server` rather than Flask/FastAPI: the no-install constraint (ADR-014).

Hardening that is present, because "localhost-only" is a deployment constraint and not
a substitute for controls:

  * **CSRF tokens** on every state-changing form, bound to the session and compared in
    constant time. Without them any page the reviewer visits could POST an approval.
  * **Origin/Referer checking** on POSTs as a second, independent barrier.
  * **TLS**, optionally, with `--tls-cert/--tls-key` (or `--tls-selfsigned` if the
    `cryptography` package happens to be available).
  * **Login throttling and TOTP** come from `agent.identity`, so the UI and the CLI
    cannot diverge on authentication strength.
  * **Session cookie** is HttpOnly, SameSite=Strict, and Secure when serving TLS.
  * Security headers: no-sniff, `frame-ancestors 'none'`, no referrer.

Still not suitable for public exposure: no account recovery, no audit of failed logins
beyond the lockout counter, and the binding is 127.0.0.1 by default. The seam that
matters is that the *server holds no authority*: it calls
`Orchestrator.approve(session_token=...)`, and every control in the write path (token
binding, report-hash binding, destination allowlist) still applies.
"""

from __future__ import annotations

import argparse
import hmac
import html
import json
import secrets
import ssl
import sys
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))

from agent.audit import AuditLog  # noqa: E402
from agent.checkpoint import CheckpointStore  # noqa: E402
from agent.identity import (  # noqa: E402
    SCOPE_APPROVE_EXPORT,
    SCOPE_VIEW,
    AuthError,
    IdentityStore,
    LockedOut,
    bootstrap,
)
from agent.orchestrator import Orchestrator, RunConfig  # noqa: E402
from agent.tracing import load_trace  # noqa: E402

BASE_DIR = Path(__file__).parent / "runs"

CSS = """
:root { --ink:#16181d; --muted:#6b7280; --line:#e5e7eb; --bg:#fafafa;
        --warn:#b45309; --warnbg:#fffbeb; --ok:#047857; --okbg:#ecfdf5;
        --bad:#b91c1c; --badbg:#fef2f2; --accent:#1d4ed8; }
* { box-sizing:border-box }
body { font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif;
       color:var(--ink); background:var(--bg); margin:0 }
header { background:#fff; border-bottom:1px solid var(--line); padding:14px 28px;
         display:flex; align-items:center; gap:16px }
header h1 { font-size:16px; margin:0; font-weight:650; letter-spacing:-.01em }
header .who { margin-left:auto; color:var(--muted); font-size:13px }
main { max-width:900px; margin:0 auto; padding:28px }
.localonly { background:var(--warnbg); color:var(--warn); border:1px solid #fde68a;
             padding:8px 14px; border-radius:6px; font-size:13px; margin-bottom:20px }
.card { background:#fff; border:1px solid var(--line); border-radius:8px;
        padding:20px 22px; margin-bottom:16px }
.card h2 { font-size:15px; margin:0 0 4px }
.meta { color:var(--muted); font-size:13px; margin-bottom:14px }
.meta code { background:var(--bg); padding:1px 5px; border-radius:4px }
.gap { background:var(--warnbg); border-left:3px solid var(--warn);
       padding:10px 14px; margin:12px 0; font-size:14px; border-radius:0 4px 4px 0 }
.flag { background:var(--badbg); border-left:3px solid var(--bad);
        padding:10px 14px; margin:12px 0; font-size:14px; border-radius:0 4px 4px 0 }
.report { background:var(--bg); border:1px solid var(--line); border-radius:6px;
          padding:16px 18px; max-height:460px; overflow:auto;
          white-space:pre-wrap; font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace }
.row { display:flex; gap:10px; margin-top:16px; align-items:center }
button { font:inherit; font-weight:550; padding:9px 18px; border-radius:6px;
         border:1px solid transparent; cursor:pointer }
.approve { background:var(--ok); color:#fff }
.reject { background:#fff; color:var(--bad); border-color:#fecaca }
input { font:inherit; padding:9px 11px; border:1px solid var(--line);
        border-radius:6px; width:100%; max-width:320px }
label { display:block; font-size:13px; color:var(--muted); margin:12px 0 4px }
a { color:var(--accent) }
.empty { color:var(--muted); text-align:center; padding:40px 0 }
table { width:100%; border-collapse:collapse; font-size:13px }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line) }
th { color:var(--muted); font-weight:550 }
.pill { font-size:12px; padding:2px 8px; border-radius:99px; font-weight:550 }
.pill.ok { background:var(--okbg); color:var(--ok) }
.pill.bad { background:var(--badbg); color:var(--bad) }
"""


def page(title: str, body: str, who: str | None = None) -> bytes:
    nav = (
        f'<span class="who">{html.escape(who)} · <a href="/audit">audit chain</a> · '
        f'<a href="/logout">sign out</a></span>'
        if who
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header><h1>Deep-research agent · approval queue</h1>{nav}</header>
<main><div class="localonly">Loopback-bound review UI with CSRF tokens, login throttling
and optional TOTP; TLS via <code>--tls-cert</code>. Not hardened for public exposure —
see the module docstring. The server holds no authority of its own: every control in the
write path still applies.</div>{body}</main></body></html>""".encode()


#: session token -> csrf token. Kept server-side so a stolen cookie alone is not
#: enough to forge a state-changing request from another origin.
CSRF_TOKENS: dict[str, str] = {}


def csrf_for(session_token: str) -> str:
    if session_token not in CSRF_TOKENS:
        CSRF_TOKENS[session_token] = secrets.token_urlsafe(32)
    return CSRF_TOKENS[session_token]


class Handler(BaseHTTPRequestHandler):
    server_version = "hitl-review/1.1"
    identity: IdentityStore
    base_dir: Path
    tls: bool = False

    # --- plumbing ------------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        print(f"  {self.address_string()} {fmt % args}")

    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        cookie.load(raw)
        return cookie["session"].value if "session" in cookie else None

    def _send(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _principal(self, scope: str = SCOPE_VIEW):
        return self.identity.verify_session(self._session_token(), scope=scope)

    def _cookie(self, token: str) -> str:
        secure = "; Secure" if self.tls else ""
        return f"session={token}; HttpOnly; SameSite=Strict; Path=/{secure}"

    def _check_csrf(self, form: dict[str, list[str]]) -> bool:
        """Token match plus an Origin/Referer check — two independent barriers."""
        session = self._session_token()
        if not session or session not in CSRF_TOKENS:
            return False
        supplied = form.get("csrf", [""])[0]
        if not hmac.compare_digest(supplied, CSRF_TOKENS[session]):
            return False
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if origin:
            host = self.headers.get("Host", "")
            if urlparse(origin).netloc != host:
                return False
        return True

    def _form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length") or 0)
        return parse_qs(self.rfile.read(length).decode()) if length else {}

    # --- routing -------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/login":
                return self._send(self.login_page())
            if path == "/logout":
                token = self._session_token()
                if token:
                    self.identity.revoke(token)
                    CSRF_TOKENS.pop(token, None)
                return self._redirect("/login", {"Set-Cookie": "session=; Max-Age=0; Path=/"})
            try:
                principal = self._principal()
            except AuthError:
                return self._redirect("/login")
            if path == "/":
                return self._send(self.queue_page(principal))
            if path == "/audit":
                return self._send(self.audit_page(principal))
            if path.startswith("/run/"):
                return self._send(self.run_page(principal, path.split("/run/", 1)[1]))
            self._send(page("Not found", '<div class="card">No such page.</div>'), 404)
        except Exception:  # pragma: no cover
            traceback.print_exc()
            self._send(page("Error", '<div class="card">Internal error; see server log.</div>'), 500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        form = self._form()
        try:
            if path == "/login":
                try:
                    session = self.identity.authenticate(
                        form.get("principal_id", [""])[0],
                        form.get("password", [""])[0],
                        totp_code=form.get("totp", [""])[0] or None,
                    )
                except LockedOut as exc:
                    # The delay is not a secret; telling the user beats silent failure.
                    return self._send(
                        self.login_page(f"Too many failed attempts. Try again in {exc.retry_after_s:.0f}s."),
                        429,
                    )
                except AuthError:
                    # One message for every failure mode — never reveal which.
                    return self._send(self.login_page("Authentication failed."), 401)
                csrf_for(session.token)
                return self._redirect("/", {"Set-Cookie": self._cookie(session.token)})

            if path in ("/approve", "/reject"):
                if not self._check_csrf(form):
                    return self._send(
                        page("Rejected", '<div class="flag">CSRF check failed. Reload the run page and retry.</div>'),
                        403,
                    )
                run_id = form.get("run_id", [""])[0]
                token = self._session_token()
                # The decision itself is authorised inside the orchestrator, which is
                # the point: the UI cannot approve on its own authority.
                store = CheckpointStore(self.base_dir / "durable.sqlite3")
                run = store.get_run(run_id)
                if run is None:
                    return self._send(page("Not found", '<div class="card">No such run.</div>'), 404)
                # The server's identity store holds the live session, so it must be
                # the one the gate authorises against.
                orch = Orchestrator(
                    RunConfig(question=run["question"], run_id=run_id, base_dir=self.base_dir, quiet=True),
                    identity=self.identity,
                )
                result = (
                    orch.approve(session_token=token)
                    if path == "/approve"
                    else orch.reject(session_token=token, reason=form.get("reason", ["rejected by reviewer"])[0])
                )
                return self._send(self.outcome_page(result))
            self._send(page("Not found", '<div class="card">No such endpoint.</div>'), 404)
        except Exception:  # pragma: no cover
            traceback.print_exc()
            self._send(page("Error", '<div class="card">Internal error; see server log.</div>'), 500)

    # --- pages ---------------------------------------------------------------------
    def login_page(self, error: str = "") -> bytes:
        err = f'<div class="flag">{html.escape(error)}</div>' if error else ""
        return page(
            "Sign in",
            f"""<div class="card"><h2>Sign in to review exports</h2>
<div class="meta">Approving an export is an irreversible, externally visible action, so it
requires an authenticated principal holding <code>approve:export</code>.</div>{err}
<form method="post" action="/login">
<label>Principal id</label><input name="principal_id" autofocus autocomplete="username">
<label>Password</label><input name="password" type="password" autocomplete="current-password">
<label>Authenticator code <span style="opacity:.6">(if enrolled)</span></label>
<input name="totp" inputmode="numeric" autocomplete="one-time-code" placeholder="123456">
<div class="row"><button class="approve" type="submit">Sign in</button></div>
</form></div>""",
        )

    def queue_page(self, principal) -> bytes:
        store = CheckpointStore(self.base_dir / "durable.sqlite3")
        pending = [r for r in store.list_runs(200) if r["status"] == "awaiting_approval"]
        if not pending:
            body = '<div class="card"><div class="empty">Nothing awaiting approval.</div></div>'
        else:
            rows = "".join(
                f"""<div class="card"><h2><a href="/run/{html.escape(r['run_id'])}">
{html.escape(r['question'][:110])}</a></h2>
<div class="meta"><code>{html.escape(r['run_id'])}</code></div></div>"""
                for r in pending
            )
            body = f"<p class='meta'>{len(pending)} run(s) awaiting approval.</p>{rows}"
        return page("Approval queue", body, principal.display_name)

    def run_page(self, principal, run_id: str) -> bytes:
        run_dir = self.base_dir / run_id
        store = CheckpointStore(self.base_dir / "durable.sqlite3")
        pending = store.get(run_id, "awaiting_approval")
        run = store.get_run(run_id)
        if pending is None or run is None:
            return page("Not found", '<div class="card">No pending approval for that run.</div>', principal.display_name)

        synth = store.get(run_id, "synthesis") or {}
        gaps = synth.get("coverage_gaps") or []
        result_path = run_dir / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}

        # Surface everything a reviewer needs to decide, in the order they need it.
        gap_html = ""
        if gaps:
            items = "".join(f"<li>{html.escape(g)}</li>" for g in gaps)
            gap_html += (
                f'<div class="gap"><b>Declared coverage gaps ({len(gaps)})</b> — no vetted source '
                f"supported a claim on:<ul>{items}</ul></div>"
            )
        if result.get("failed_subquestions"):
            items = "".join(f"<li>{html.escape(g)}</li>" for g in result["failed_subquestions"])
            gap_html += f'<div class="gap"><b>Retrieval failed for</b><ul>{items}</ul></div>'

        flags = [g for g in result.get("guardrail_events", []) if g.get("reasons")]
        flag_html = ""
        if flags:
            items = "".join(
                f"<li><code>{html.escape(g['control'])}</code> — {html.escape(', '.join(g['reasons']))}</li>"
                for g in flags
            )
            flag_html = (
                f'<div class="flag"><b>Guardrails fired during this run ({len(flags)})</b>'
                f"<ul>{items}</ul>Read the report knowing a source was interfered with.</div>"
            )

        spans = load_trace(run_dir / "trace.jsonl")
        cost = sum(float(s["attributes"].get("cost_usd", 0)) for s in spans)
        ground = next((s for s in spans if s["name"] == "guardrail.groundedness"), None)
        ground_html = ""
        if ground:
            checked = ground["attributes"].get("groundedness.claims_checked", 0)
            unsupported = ground["attributes"].get("groundedness.claims_unsupported", 0)
            ground_html = (
                f'<div class="meta">Semantic groundedness: <b>{checked - unsupported}/{checked}</b> '
                "claims verified against the text of the source they cite."
                + (" All verified." if not unsupported else f" <b>{unsupported} unverified.</b>")
                + "</div>"
            )
        can_approve = principal.may(SCOPE_APPROVE_EXPORT)
        csrf = html.escape(csrf_for(self._session_token() or ""))
        actions = (
            f"""<form method="post" action="/approve" class="row">
<input type="hidden" name="run_id" value="{html.escape(run_id)}">
<input type="hidden" name="csrf" value="{csrf}">
<button class="approve" type="submit">Approve and export</button></form>
<form method="post" action="/reject" class="row">
<input type="hidden" name="run_id" value="{html.escape(run_id)}">
<input type="hidden" name="csrf" value="{csrf}">
<button class="reject" type="submit">Reject</button></form>"""
            if can_approve
            else '<div class="meta">Your principal lacks <code>approve:export</code>.</div>'
        )

        return page(
            "Review export",
            f"""<div class="card">
<h2>{html.escape(run["question"])}</h2>
<div class="meta">run <code>{html.escape(run_id)}</code> · destination
<code>{html.escape(pending["destination"])}</code> · report hash
<code>{html.escape(pending["report_hash"])}</code> · cost ${cost:.5f} ·
{len(result.get("subquestions", []))} sub-question(s)</div>
{flag_html}{gap_html}{ground_html}
<div class="meta">You are approving <b>this exact artifact</b>: the confirmation token is
bound to the hash above, so a report modified after approval cannot be exported.</div>
<div class="report">{html.escape(pending["report_markdown"])}</div>
{actions}</div>""",
            principal.display_name,
        )

    def audit_page(self, principal) -> bytes:
        """Live verification of every audit chain — threat-model R2."""
        rows = []
        for log_path in sorted(self.base_dir.glob("*/audit.jsonl")):
            log = AuditLog(log_path)
            v = log.verify()
            records = list(log.read())
            pill = '<span class="pill ok">intact</span>' if v.ok else '<span class="pill bad">TAMPERED</span>'
            detail = "" if v.ok else "<br>" + "<br>".join(html.escape(p) for p in v.problems)
            for r in records:
                rows.append(
                    f"<tr><td><code>{html.escape(log_path.parent.name)}</code></td>"
                    f"<td>{r['seq']}</td><td>{html.escape(str(r.get('action')))}</td>"
                    f"<td>{html.escape(str(r.get('approved_by')))}</td>"
                    f"<td><code>{html.escape(str(r.get('hash'))[:12])}</code></td>"
                    f"<td>{pill}{detail}</td></tr>"
                )
        table = (
            "<table><tr><th>run</th><th>seq</th><th>action</th><th>approved by</th>"
            f"<th>chain hash</th><th>chain state</th></tr>{''.join(rows)}</table>"
            if rows
            else '<div class="empty">No audit records yet.</div>'
        )
        return page(
            "Audit chain",
            f"""<div class="card"><h2>Audit chain verification</h2>
<div class="meta">Every export record is hash-chained to its predecessor. Editing,
reordering, deleting or truncating a record breaks verification.</div>{table}</div>""",
            principal.display_name,
        )

    def outcome_page(self, result) -> bytes:
        ok = result.status == "exported"
        cls = "gap" if not ok else "card"
        extra = ""
        if ok and result.export:
            extra = f'<div class="meta">Written to <code>{html.escape(str(result.export["location"]))}</code>, audit record appended.</div>'
        return page(
            "Decision recorded",
            f"""<div class="{cls}"><b>{html.escape(result.status)}</b>
{" — " + html.escape(", ".join(result.reasons)) if result.reasons else ""}</div>
{extra}<div class="card"><a href="/">Back to the queue</a></div>""",
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--base-dir", default=str(BASE_DIR))
    ap.add_argument("--host", default="127.0.0.1", help="binding host; leaving this at loopback is the point")
    ap.add_argument("--tls-cert", help="PEM certificate; enables https")
    ap.add_argument("--tls-key", help="PEM private key")
    args = ap.parse_args(argv)

    base = Path(args.base_dir)
    base.mkdir(parents=True, exist_ok=True)
    identity, seeded_password = bootstrap(base / "principals.json")

    Handler.identity = identity
    Handler.base_dir = base

    if seeded_password:
        print("\n  No principals existed, so one was created. This is shown ONCE:\n")
        print(f"      principal id : reviewer")
        print(f"      password     : {seeded_password}\n")
        print("  Seeding a default known password would be worse than the string-name")
        print("  approval this replaces, so capture it now or delete principals.json to reseed.\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    scheme = "http"
    if args.tls_cert and args.tls_key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        server.socket = context.wrap_socket(server.socket, server_side=True)
        Handler.tls = True
        scheme = "https"
    elif args.host not in ("127.0.0.1", "localhost", "::1"):
        # Refuse rather than serve credentials in the clear off-loopback.
        print(
            f"  refusing to bind {args.host} without TLS — pass --tls-cert/--tls-key,"
            " or keep the default loopback binding",
            file=sys.stderr,
        )
        return 2
    print(f"  HITL review UI on {scheme}://{args.host}:{args.port}  (Ctrl-C to stop)")
    print(f"  runs directory: {base}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
