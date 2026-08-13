"""Measure the host-specific glue (FR-6: "a bounded, documented amount").

Counts non-blank, non-comment lines in:
  * the portable core   — contract, policy, gate, broker, egress, registry, audit,
                          taint, secrets, plus the manifests and policy data
  * host binding #1     — the subprocess loader/sandbox driver
  * host binding #2     — the graph-node driver (portability/bindings/)

Run: python3 -m portability.bindings.measure_glue
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

PORTABLE = [
    "runtime/host/contract.py",
    "runtime/host/policy.py",
    "runtime/host/gate.py",
    "runtime/host/broker.py",
    "runtime/host/registry.py",
    "runtime/host/audit.py",
    "runtime/host/taint.py",
    "runtime/host/egress.py",
    "runtime/host/secrets.py",
    "runtime/host/errors.py",
    # host.py counts as portable because binding #2 *subclasses* it: the
    # orchestration (channel handler, taint session, lifecycle, kill-switch) moved
    # to the second host without edits. Only the runtime driver was re-written.
    "runtime/host/host.py",
    "security/policy/abac-policy.yaml",
    "governance/approved-grants.yaml",
]
EXTENSIONS = ["integrations"]
BINDING_1 = ["runtime/host/sandbox.py", "runtime/host/sandbox_runner.py"]
BINDING_2 = ["portability/bindings/graph_host_binding.py"]


def count(path: str) -> int:
    total = 0
    full = os.path.join(ROOT, path)
    files = []
    if os.path.isdir(full):
        for root, _, names in os.walk(full):
            files += [os.path.join(root, n) for n in names if n.endswith((".py", ".yaml"))]
    else:
        files = [full]
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    total += 1
    return total


def group(label: str, paths: list[str]) -> int:
    total = sum(count(p) for p in paths)
    print(f"\n{label}  ({total} lines)")
    for p in paths:
        print(f"    {count(p):>5}  {p}")
    return total


def main() -> int:
    print("=" * 74)
    print("HOST-SPECIFIC GLUE MEASUREMENT")
    print("=" * 74)
    portable = group("PORTABLE CORE — moves to any host unchanged", PORTABLE)
    exts = group("EXTENSIONS — contract + handler code, unchanged across hosts", EXTENSIONS)
    b1 = group("HOST BINDING #1 — subprocess/remote-rpc reference host", BINDING_1)
    b2 = group("HOST BINDING #2 — graph-platform host", BINDING_2)

    shared = portable + exts
    print("\n" + "-" * 74)
    print(f"portable (core + extensions)     {shared:>6} lines")
    print(f"binding #1 (subprocess host)     {b1:>6} lines   "
          f"({b1 / (shared + b1) * 100:.1f}% of that host's total)")
    print(f"binding #2 (graph host)          {b2:>6} lines   "
          f"({b2 / (shared + b2) * 100:.1f}% of that host's total)")
    print("-" * 74)
    print(
        "\nBinding #2 re-implements exactly one interface — the runtime driver\n"
        "(`execute(ext, payload, token_handle, on_egress) -> SandboxResult`) — plus\n"
        "bootstrap wiring and one entry point in the platform's idiom. Every manifest,\n"
        "every policy rule, every grant and the whole gate/broker/audit path is shared.\n"
        "\nWhat binding #2 loses is documented in portability/lock-in-analysis.md:\n"
        "process-level isolation and the import blocker become the platform's\n"
        "responsibility, and the three `runtime.type` values collapse into one node type."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
