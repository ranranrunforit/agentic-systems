"""Shared presentation helpers for the demos. No platform logic lives here."""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

W = 78


def title(text: str) -> None:
    print("\n" + "=" * W)
    print(text)
    print("=" * W)


def step(n, text: str) -> None:
    print(f"\n[{n}] {text}")


def bullet(text: str, mark: str = "·") -> None:
    print(f"    {mark} {text}")


def verdict(ok: bool, text: str) -> None:
    print(f"\n    {'PASS' if ok else 'FAIL'}  {text}")


def audit_tail(host, n=12, events=None) -> None:
    print("\n    audit trail:")
    records = host.audit.records[-n:] if not events else [
        r for r in host.audit.records if r.event in events
    ][-n:]
    for r in records:
        detail = " ".join(f"{k}={_short(v)}" for k, v in list(r.payload.items())[:4])
        print(f"      #{r.seq:<3} {r.event:<26} {r.extension:<26} {r.actor:<16} {detail}")


def _short(value, limit=42):
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
