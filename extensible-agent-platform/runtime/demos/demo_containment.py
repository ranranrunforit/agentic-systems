"""Demo 3 — a misbehaving extension is contained (NFR-2).

    python3 -m runtime.demos.demo_containment

Loads the red-team fixture, which tries nine different escapes.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _util import ROOT, audit_tail, bullet, step, title, verdict  # noqa: F401
import os

from runtime.backends import reset_all
from runtime.host import Host, contract

FIXTURE = os.path.join(ROOT, "runtime", "tests", "fixtures", "rogue-extension")


def main() -> int:
    title("DEMO 3 — CONTAINMENT OF A MISBEHAVING EXTENSION")
    reset_all()
    host = Host.bootstrap()

    step(1, "load the rogue extension (declares one capability, zero permissions)")
    rogue = contract.load_manifest(os.path.join(FIXTURE, "extension.yaml"))
    host.registry.load(rogue, actor="red-team")
    bullet(f"{rogue.ref} runtime={rogue.runtime.type} network={rogue.runtime.network} "
           f"permissions={len(rogue.permissions)}")

    step(2, "it attempts nine escapes")
    results = host.invoke("rogue-extension", {"attack": "all"},
                          actor="red-team", tenant="acme").value["results"]
    contained = True
    for attack, outcome in results.items():
        blocked = "SUCCEEDED" not in str(outcome)
        contained = contained and blocked
        bullet(f"{attack:<28} {str(outcome)[:110]}", "OK  " if blocked else "LEAK")

    audit_tail(host, events={"gate.denied", "egress.denied"}, n=6)
    verdict(contained, "no network, no filesystem, no secrets, no undeclared authority")
    print("\n    Reminder from security/isolation.md: in-process import and open() guards")
    print("    are defence in depth for this reference host. The production boundary is a")
    print("    kernel/VM sandbox (gVisor, Firecracker, seccomp+netns) or a WASM runtime.")
    return 0 if contained else 1


if __name__ == "__main__":
    raise SystemExit(main())
