"""FR-6 evidence: the same contract, policy and grants on a second host binding.

    python3 -m unittest runtime.tests.test_portability -v

If these pass, "portable" is a measured claim rather than an assertion: the
manifests, the ABAC policy, the approved grants, the gate decisions and the audit
vocabulary are identical across two hosts whose runtimes share no code.
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from portability.bindings.graph_host_binding import GraphHost  # noqa: E402
from runtime.backends import issue_tracker, reset_all  # noqa: E402
from runtime.host import Host, ScriptedConfirmation  # noqa: E402


class TestSecondHostBinding(unittest.TestCase):
    def setUp(self):
        reset_all()
        self.graph = GraphHost.bootstrap()

    def test_same_manifests_load_unchanged(self):
        graph_rows = {r["ref"]: r["permissions"] for r in self.graph.registry.inspect()}
        reset_all()
        native_rows = {r["ref"]: r["permissions"] for r in Host.bootstrap().registry.inspect()}
        self.assertEqual(graph_rows, native_rows)

    def test_integrations_work_through_the_graph_runtime(self):
        result = self.graph.invoke("issue-tracker",
                                   {"action": "read", "params": {"ticket_id": "T-1042"}},
                                   actor="t", tenant="acme")
        self.assertEqual(result.value["data"]["id"], "T-1042")

    def test_gate_decisions_are_identical_across_hosts(self):
        def decisions(host):
            reset_all()
            result = host.run_agent("triage-agent", {"ticket_id": "T-1043"},
                                    actor="t", tenant="acme")
            return [(o.proposal["resource"], o.proposal["action"], o.allowed)
                    for o in result.outcomes]

        graph = decisions(self.graph)
        native = decisions(Host.bootstrap())
        self.assertEqual(graph, native)
        self.assertTrue(any(a == "close" and not ok for _, a, ok in graph))

    def test_injection_is_contained_on_the_second_host_too(self):
        state = self.graph.run_graph("triage-agent", {"ticket_id": "T-1043"})
        self.assertEqual(state["taint"], "untrusted")
        self.assertEqual(issue_tracker.state()["T-1043"]["status"], "open")
        self.assertTrue(state["blocked"])

    def test_confirmation_gate_behaves_the_same(self):
        graph = GraphHost.bootstrap(
            confirmation=ScriptedConfirmation({"issue_tracker:close:T-1042": True})
        )
        outcome = graph.perform("issue_tracker", "close",
                                {"ticket_id": "T-1042", "project": "support-billing",
                                 "reason": "duplicate"},
                                actor="dana@support", tenant="acme", origin="human")
        self.assertTrue(outcome.allowed, outcome.reasons)
        self.assertEqual(issue_tracker.state()["T-1042"]["status"], "closed")

    def test_kill_switch_exists_on_the_second_host(self):
        self.graph.kill("knowledge-base", reason="poisoned article", actor="security-oncall")
        self.assertIsNone(self.graph.registry.provider_of("knowledge_base.search"))

    def test_audit_vocabulary_is_shared(self):
        self.graph.invoke("classify-ticket",
                          {"action": "classify", "params": {"subject": "x", "body": "login"}},
                          actor="t", tenant="acme")
        events = {r.event for r in self.graph.audit.records}
        self.assertTrue({"host.boot", "registry.loaded", "host.invoke", "sandbox.executed"} <= events)
        self.assertTrue(self.graph.audit.verify())

    def test_isolation_difference_is_visible_not_hidden(self):
        """The honest part: the graph binding reports its own runtime label."""
        self.graph.invoke("classify-ticket",
                          {"action": "classify", "params": {"subject": "x", "body": "y"}},
                          actor="t", tenant="acme")
        runtimes = {r.payload.get("runtime") for r in self.graph.audit.find("sandbox.executed")}
        self.assertEqual(runtimes, {"graph-node"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
