"""Approver identity and authorisation — closes threat-model residual risk R1.

R1 was the one launch-blocker named in the self-assessment: the approve path took an
`--approver <name>` string and believed it. Ownership, non-repudiation and audit are
all hollow without identity, so this module makes the approver an *authenticated
principal* rather than an argument.

Design, and the reasoning for each choice:

* **Passwords are never stored.** Only PBKDF2-HMAC-SHA256 with a per-principal salt
  and 240k iterations. A stolen principal file does not yield credentials.
* **Sessions, not per-call passwords.** Authentication mints a short-lived bearer
  session; the approval gate consumes a session, never a secret. This is what lets
  the review UI hold a login without holding a password.
* **Authorisation is separate from authentication.** Being a known principal is not
  permission to approve — the `approve:export` scope is checked separately, so a
  read-only reviewer account is expressible.
* **Constant-time comparison** for every secret comparison, so token checking does
  not leak by timing.
* **The audit record carries the authenticated principal id**, not a display name,
  so two people with the same name are distinguishable forever.

* **TOTP second factor** (RFC 6238, stdlib HMAC-SHA1) is supported per principal.
  Approving an external publication on a single password is thin, and a shared password
  repudiates; a second factor makes "someone else used my account" a much harder claim.
  It is opt-in per principal so a reviewer can enrol without forcing a migration.
* **Login attempts are rate-limited per principal** with exponential backoff. Without
  it, PBKDF2 raises the cost of guessing but does not bound the number of guesses.

This is deliberately a local credential store, which is right for a single-team
green-field system and wrong for an enterprise: the production move is OIDC/SSO, and
`Principal` plus `verify_session` is the seam where that swap happens — the approval
gate and the audit log do not change.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ITERATIONS = 240_000
SESSION_TTL_S = 8 * 3600
SCOPE_APPROVE_EXPORT = "approve:export"
SCOPE_VIEW = "view:runs"

#: Login throttling. After this many consecutive failures a principal is locked out for
#: `LOCKOUT_BASE_S * 2**(failures - threshold)`, capped. PBKDF2 makes each guess
#: expensive; this bounds how many guesses are possible at all.
MAX_FAILURES_BEFORE_LOCKOUT = 5
LOCKOUT_BASE_S = 2.0
LOCKOUT_CAP_S = 900.0

TOTP_STEP_S = 30
TOTP_DIGITS = 6
#: One step either side of now, so a clock a few seconds out does not lock a reviewer
#: out of an irreversible action. Wider windows trade security for convenience.
TOTP_DRIFT_STEPS = 1


class AuthError(Exception):
    """Authentication or authorisation failure. Never carries which of the two."""


class LockedOut(AuthError):
    """Too many failed attempts. Carries the retry delay, which is not a secret."""

    def __init__(self, retry_after_s: float) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(f"too many failed attempts; retry in {retry_after_s:.0f}s")


# --- TOTP (RFC 6238) --------------------------------------------------------------
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _b32decode(secret: str) -> bytes:
    """Tolerant base32 decode — accepts lowercase and spaces from a hand-typed secret."""
    import base64

    cleaned = re.sub(r"[^A-Za-z2-7]", "", secret).upper()
    cleaned += "=" * ((8 - len(cleaned) % 8) % 8)
    return base64.b32decode(cleaned)


def generate_totp_secret() -> str:
    return "".join(secrets.choice(_B32) for _ in range(32))


def totp_at(secret: str, counter: int) -> str:
    key = _b32decode(secret)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFF_FFFF
    return str(code % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def totp_now(secret: str, at: float | None = None) -> str:
    return totp_at(secret, int((at or time.time()) // TOTP_STEP_S))


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(rf"\d{{{TOTP_DIGITS}}}", code):
        return False
    counter = int((at or time.time()) // TOTP_STEP_S)
    for drift in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS + 1):
        if hmac.compare_digest(totp_at(secret, counter + drift), code):
            return True
    return False


def provisioning_uri(principal_id: str, secret: str, issuer: str = "deep-research-agent") -> str:
    """otpauth:// URI for an authenticator app."""
    from urllib.parse import quote

    label = quote(f"{issuer}:{principal_id}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_S}"
    )


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


@dataclass
class Principal:
    principal_id: str
    display_name: str
    scopes: list[str] = field(default_factory=lambda: [SCOPE_VIEW])
    mfa_enrolled: bool = False

    def may(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass
class Session:
    token: str
    principal_id: str
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class IdentityStore:
    """Principals on disk, sessions in memory (they die with the process, by design)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {"principals": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        self._sessions: dict[str, Session] = {}
        #: principal_id -> (consecutive failures, last failure time)
        self._failures: dict[str, tuple[int, float]] = {}

    # --- principal management -----------------------------------------------------
    def create_principal(
        self, principal_id: str, password: str, *, display_name: str | None = None, scopes: list[str] | None = None
    ) -> Principal:
        if not principal_id or len(password) < 8:
            raise AuthError("principal id required and password must be at least 8 characters")
        salt = secrets.token_hex(16)
        self.data["principals"][principal_id] = {
            "display_name": display_name or principal_id,
            "salt": salt,
            "password_hash": _hash_password(password, salt),
            "scopes": scopes or [SCOPE_VIEW, SCOPE_APPROVE_EXPORT],
            "created": time.time(),
        }
        self._flush()
        return self.principal(principal_id)

    def principal(self, principal_id: str) -> Principal:
        rec = self.data["principals"].get(principal_id)
        if rec is None:
            raise AuthError("unknown principal")
        return Principal(
            principal_id,
            rec["display_name"],
            list(rec["scopes"]),
            mfa_enrolled=bool(rec.get("totp_secret")),
        )

    def list_principals(self) -> list[Principal]:
        return [self.principal(pid) for pid in sorted(self.data["principals"])]

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    # --- authentication -----------------------------------------------------------
    def _lockout_remaining(self, principal_id: str, now: float) -> float:
        failures, last = self._failures.get(principal_id, (0, 0.0))
        if failures < MAX_FAILURES_BEFORE_LOCKOUT:
            return 0.0
        delay = min(LOCKOUT_CAP_S, LOCKOUT_BASE_S * 2 ** (failures - MAX_FAILURES_BEFORE_LOCKOUT))
        return max(0.0, last + delay - now)

    def _record_failure(self, principal_id: str, now: float) -> None:
        failures, _ = self._failures.get(principal_id, (0, 0.0))
        self._failures[principal_id] = (failures + 1, now)

    def authenticate(
        self, principal_id: str, password: str, *, totp_code: str | None = None, now: float | None = None
    ) -> Session:
        now = now or time.time()
        remaining = self._lockout_remaining(principal_id, now)
        if remaining > 0:
            # Throttle before touching credentials, so a locked-out principal costs an
            # attacker time whether or not the password is right.
            raise LockedOut(remaining)

        rec = self.data["principals"].get(principal_id)
        if rec is None:
            # Hash anyway so a missing principal and a wrong password take the same
            # time — otherwise this endpoint enumerates valid principals.
            _hash_password(password, secrets.token_hex(16))
            self._record_failure(principal_id, now)
            raise AuthError("authentication failed")

        candidate = _hash_password(password, rec["salt"])
        ok = hmac.compare_digest(candidate, rec["password_hash"])

        secret = rec.get("totp_secret")
        if secret:
            # Evaluated even when the password is already wrong, so a valid password
            # with a missing code is indistinguishable in timing from the reverse.
            ok = verify_totp(secret, totp_code or "", at=now) and ok
        if not ok:
            self._record_failure(principal_id, now)
            raise AuthError("authentication failed")

        self._failures.pop(principal_id, None)
        session = Session(secrets.token_urlsafe(32), principal_id, now + SESSION_TTL_S)
        self._sessions[session.token] = session
        return session

    # --- MFA enrolment ------------------------------------------------------------
    def enrol_totp(self, principal_id: str) -> tuple[str, str]:
        """Generate and store a TOTP secret. Returns (secret, provisioning_uri)."""
        rec = self.data["principals"].get(principal_id)
        if rec is None:
            raise AuthError("unknown principal")
        secret = generate_totp_secret()
        rec["totp_secret"] = secret
        self._flush()
        return secret, provisioning_uri(principal_id, secret)

    def unenrol_totp(self, principal_id: str) -> None:
        rec = self.data["principals"].get(principal_id)
        if rec is None:
            raise AuthError("unknown principal")
        rec.pop("totp_secret", None)
        self._flush()

    def verify_session(self, token: str | None, *, scope: str) -> Principal:
        """Returns the authorised principal, or raises. The only entry point callers need."""
        if not token:
            raise AuthError("authentication required")
        session = None
        for candidate in self._sessions.values():  # constant-time-ish lookup
            if hmac.compare_digest(candidate.token, token):
                session = candidate
                break
        if session is None or session.expired:
            self._sessions.pop(token, None)
            raise AuthError("session invalid or expired")
        principal = self.principal(session.principal_id)
        if not principal.may(scope):
            raise AuthError(f"principal lacks required scope: {scope}")
        return principal

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)

    def revoke_all(self, principal_id: str) -> int:
        stale = [t for t, s in self._sessions.items() if s.principal_id == principal_id]
        for t in stale:
            del self._sessions[t]
        return len(stale)


def bootstrap(path: Path) -> tuple[IdentityStore, str | None]:
    """Create the store, seeding a first reviewer if none exists.

    A generated password is printed once and never stored in plaintext. Seeding a
    default *known* password would be worse than the string-name approval it
    replaces, so the credential must be captured at bootstrap or reset.
    """
    store = IdentityStore(path)
    if store.data["principals"]:
        return store, None
    password = secrets.token_urlsafe(18)
    store.create_principal(
        "reviewer",
        password,
        display_name="Default reviewer",
        scopes=[SCOPE_VIEW, SCOPE_APPROVE_EXPORT],
    )
    return store, password
