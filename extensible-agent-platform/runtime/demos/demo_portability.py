"""Demo 5 — the same contract on a second host (FR-6, stretch goal).

    python3 -m runtime.demos.demo_portability
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from _util import ROOT, bullet, step, title, verdict  # noqa: F401
from portability.bindings.graph_host_binding import GraphHost
from portability.bindings.measure_glue import main as measure
from runtime.backends import issue_tracker, reset_all
from runtime.host import Host


def main() -> int:
    title("DEMO 5 — ONE CONTRACT, TWO HOSTS")

    def decisions(host):
        reset_all()
        result = host.run_agent("triage-agent", {"ticket_id": "T-1043"}, actor="t", tenant="acme")
        return [(o.proposal["resource"], o.proposal["action"], o.allowed) for o in result.outcomes]

    step(1, "host binding #1 — subprocess/remote-rpc reference host")
    native = decisions(Host.bootstrap())
    for row in native:
        bullet(f"{row[0]}:{row[1]:<8} allowed={row[2]}")
    native_state = issue_tracker.state()["T-1043"]["status"]

    step(2, "host binding #2 — graph-platform host, same manifests and policy")
    graph = decisions(GraphHost.bootstrap())
    for row in graph:
        bullet(f"{row[0]}:{row[1]:<8} allowed={row[2]}")
    graph_state = issue_tracker.state()["T-1043"]["status"]

    step(3, "how much code was host-specific")
    measure()

    ok = native == graph and native_state == graph_state == "open"
    verdict(ok, "identical gate decisions and identical outcomes on both hosts")
    print("\n    What binding #2 gives up (portability/lock-in-analysis.md):")
    bullet("process isolation and the import blocker become the platform's job")
    bullet("three runtime.type values collapse into one node type")
    bullet("host-managed autoscaling and checkpointing arrive in exchange")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
