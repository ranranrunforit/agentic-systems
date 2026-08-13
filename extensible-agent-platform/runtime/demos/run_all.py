"""Run every demo in order. `make demo` calls this.

    python3 -m runtime.demos.run_all
"""

import importlib
import sys

DEMOS = [
    "runtime.demos.demo_triage",
    "runtime.demos.demo_injection",
    "runtime.demos.demo_containment",
    "runtime.demos.demo_governance",
    "runtime.demos.demo_portability",
]


def main() -> int:
    failures = []
    for name in DEMOS:
        module = importlib.import_module(name)
        if module.main():
            failures.append(name)
    print("\n" + "=" * 78)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"ALL {len(DEMOS)} DEMOS PASSED")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
