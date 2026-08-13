"""Acceptance-criteria test suite.

    python3 -m unittest discover -s runtime/tests -v
    make test

Each test class maps to a requirement so a reviewer can trace the grade:

    TestContract          FR-1  one contract, four kinds, load/isolate/revoke
    TestAuthorization     FR-2  default-deny, ABAC, scope, two keys
    TestTokenLifecycle    FR-2  issue / scope / rotate / revoke, least privilege
    TestIsolation         FR-2  local + remote isolation, containment
    TestInjection         FR-3  trust boundary, taint, confirmation gate
    TestGovernance        FR-4  permission diff, kill-switch, deprecation
    TestIntegrations      FR-5  three integrations, all through the contract
    TestAuditability      NFR-4 attributable, inspectable, tamper-evident
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from runtime.backends import issue_tracker, reset_all  # noqa: E402
from runtime.host import (  # noqa: E402
    AlwaysApproveConfirmation,
    AuthorizationDenied,
    ContractError,
    Grant,
    Host,
    Intent,
    PermissionExpansionError,
    RevokedError,
    ScriptedConfirmation,
    contract,
)
from runtime.host.errors import EgressDenied, SandboxError  # noqa: E402
from runtime.host.taint import UNTRUSTED, TaintSet, scan  # noqa: E402

INTEGRATIONS = os.path.join(ROOT, "integrations")
FIXTURES = os.path.join(ROOT, "runtime", "tests", "fixtures")


def fresh_host(**kwargs) -> Host:
    reset_all()
    return Host.bootstrap(**kwargs)


# --------------------------------------------------------------------------- #


class TestContract(unittest.TestCase):
    """FR-1: one uniform contract covers agents, tools, hooks and connectors."""

    def test_all_four_kinds_parse_under_one_schema(self):
        kinds = {}
        for name in os.listdir(INTEGRATIONS):
            manifest = os.path.join(INTEGRATIONS, name, "extension.yaml")
            if os.path.exists(manifest):
                ext = contract.load_manifest(manifest)
                kinds.setdefault(ext.kind, []).append(ext.name)
        self.assertEqual(set(kinds), {"agent", "tool", "hook", "connector"})

    def test_unscoped_permission_is_rejected(self):
        bad = _minimal_manifest()
        bad["permissions"] = [{"resource": "issue_tracker", "actions": ["read"], "scope": {}}]
        with self.assertRaises(ContractError) as cm:
            contract.parse(bad)
        self.assertIn("unscoped", str(cm.exception))

    def test_high_impact_action_requires_justification(self):
        bad = _minimal_manifest()
        bad["permissions"] = [
            {"resource": "issue_tracker", "actions": ["close"], "scope": {"tenant": "acme"}}
        ]
        with self.assertRaises(ContractError) as cm:
            contract.parse(bad)
        self.assertIn("justification", str(cm.exception))

    def test_egress_without_delegated_auth_is_rejected(self):
        bad = _minimal_manifest()
        bad["runtime"]["network"] = "broker-only"
        bad["egress"] = {"allow": ["x.example.internal"]}
        bad["trust"] = {"output_class": "untrusted"}
        with self.assertRaises(ContractError) as cm:
            contract.parse(bad)
        self.assertIn("delegated_auth", str(cm.exception))

    def test_external_reach_cannot_claim_trusted_output(self):
        bad = _minimal_manifest()
        bad["runtime"]["network"] = "broker-only"
        bad["egress"] = {"allow": ["x.example.internal"]}
        bad["delegated_auth"] = {
            "provider": "x",
            "flow": "client_credentials",
            "scopes": ["a.read"],
            "secret_ref": "secrets/x",
        }
        bad["trust"] = {"output_class": "trusted"}
        with self.assertRaises(ContractError):
            contract.parse(bad)

    def test_load_isolate_revoke_round_trip(self):
        host = fresh_host()
        self.assertTrue(host.registry.loaded())
        host.kill("cicd-status", reason="test", actor="tester")
        self.assertIsNotNone(host.registry.liveness_problem("cicd-status"))
        with self.assertRaises(RevokedError):
            host.registry.get("cicd-status")


class TestAuthorization(unittest.TestCase):
    """FR-2: default-deny, ABAC, scope enforcement, and the two-key rule."""

    def setUp(self):
        self.host = fresh_host()

    def test_undeclared_action_is_denied_by_default(self):
        agent = self.host.registry.get("triage-agent")
        outcome = self.host.perform(
            "issue_tracker", "close", {"ticket_id": "T-1042", "project": "support-billing"},
            caller=agent, actor="t", tenant="acme", origin="model",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("never declared", " ".join(outcome.reasons))
        self.assertTrue(self.host.audit.find("gate.denied"))

    def test_action_nobody_provides_is_denied(self):
        outcome = self.host.perform("payments", "refund", {"id": "X"}, actor="t", tenant="acme")
        self.assertFalse(outcome.allowed)

    def test_out_of_scope_project_is_denied(self):
        outcome = self.host.perform(
            "issue_tracker", "label",
            {"ticket_id": "T-1042", "project": "internal-secret", "label": "billing"},
            actor="t", tenant="acme", origin="human",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("out of scope", " ".join(outcome.reasons))

    def test_policy_denies_write_for_read_only_tenant(self):
        outcome = self.host.perform(
            "issue_tracker", "label",
            {"ticket_id": "T-1044", "project": "support-billing", "label": "billing"},
            actor="t", tenant="globex", origin="human",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("R-901", " ".join(outcome.reasons))

    def test_manifest_grant_alone_is_not_enough(self):
        """Key 2: policy R-902 keeps cicd mutation unreachable even if declared."""
        connector = self.host.registry.get("cicd-status")
        intent = Intent(
            extension=connector, resource="cicd", action="rerun",
            params={"service": "support-platform"}, tenant="acme", actor="t", origin="human",
        )
        with self.assertRaises(AuthorizationDenied):
            self.host.gate.authorize(intent)

    def test_approved_grant_is_required_to_load(self):
        host = Host.bootstrap(integrations_dir=None, grants_path=os.devnull)
        with self.assertRaises(Exception):
            host.load(os.path.join(INTEGRATIONS, "issue-tracker"))

    def test_happy_path_is_allowed_and_executes(self):
        outcome = self.host.perform(
            "issue_tracker", "label",
            {"ticket_id": "T-1042", "project": "support-billing", "label": "billing"},
            actor="dana@support", tenant="acme", origin="human",
        )
        self.assertTrue(outcome.allowed, outcome.reasons)
        self.assertIn("billing", issue_tracker.state()["T-1042"]["labels"])


class TestTokenLifecycle(unittest.TestCase):
    """FR-2: issuance, scoping, rotation, revocation, least privilege."""

    def setUp(self):
        self.host = fresh_host()
        self.broker = self.host.broker

    def test_token_is_scoped_and_short_lived(self):
        grant = self.broker.mint(
            extension="issue-tracker@1.4.0", tenant="acme", resource="issue_tracker",
            actions=("read",), secret_ref="secrets/issue-tracker/oauth-client",
            intent_hash="deadbeef",
        )
        self.assertEqual(grant.upstream_scopes, ("tickets.read",))
        self.assertLessEqual(grant.expires_at - grant.issued_at, 30.0)
        with self.assertRaises(Exception):
            self.broker.redeem(
                grant.handle, extension="issue-tracker@1.4.0",
                resource="issue_tracker", action="close",
            )

    def test_token_cannot_be_replayed_by_another_extension(self):
        grant = self.broker.mint(
            extension="issue-tracker@1.4.0", tenant="acme", resource="issue_tracker",
            actions=("read",), secret_ref="secrets/issue-tracker/oauth-client",
            intent_hash="deadbeef",
        )
        with self.assertRaises(Exception):
            self.broker.redeem(
                grant.handle, extension="triage-agent@2.1.0",
                resource="issue_tracker", action="read",
            )

    def test_least_privilege_beyond_upstream_scopes_is_refused(self):
        with self.assertRaises(Exception):
            self.broker.mint(
                extension="knowledge-base@1.1.2", tenant="acme", resource="knowledge_base",
                actions=("read",), secret_ref="secrets/cicd/oauth-client", intent_hash="x",
            )

    def test_rotation_invalidates_outstanding_tokens(self):
        grant = self.broker.mint(
            extension="issue-tracker@1.4.0", tenant="acme", resource="issue_tracker",
            actions=("read",), secret_ref="secrets/issue-tracker/oauth-client", intent_hash="x",
        )
        killed = self.host.rotate("secrets/issue-tracker/oauth-client", "rotated-value")
        self.assertEqual(killed, 1)
        with self.assertRaises(Exception):
            self.broker.redeem(
                grant.handle, extension="issue-tracker@1.4.0",
                resource="issue_tracker", action="read",
            )

    def test_extension_code_never_receives_a_credential(self):
        """The connector's own logs and result must not contain the secret."""
        result = self.host.invoke(
            "issue-tracker", {"action": "read", "params": {"ticket_id": "T-1042"}},
            actor="t", tenant="acme",
        )
        blob = repr(result.value) + repr(result.logs)
        self.assertNotIn("fixture-issue-tracker-access-token", blob)

    def test_revocation_kills_outstanding_tokens(self):
        self.broker.mint(
            extension="issue-tracker@1.4.0", tenant="acme", resource="issue_tracker",
            actions=("read",), secret_ref="secrets/issue-tracker/oauth-client", intent_hash="x",
        )
        self.assertEqual(len(self.broker.outstanding("issue-tracker@1.4.0")), 1)
        self.host.kill("issue-tracker", reason="test", actor="tester")
        self.assertEqual(len(self.broker.outstanding("issue-tracker@1.4.0")), 0)


class TestIsolation(unittest.TestCase):
    """FR-2 / NFR-2: a misbehaving extension is contained."""

    @classmethod
    def setUpClass(cls):
        cls.host = fresh_host()
        rogue = contract.load_manifest(os.path.join(FIXTURES, "rogue-extension", "extension.yaml"))
        cls.host.registry.load(rogue, actor="red-team")
        cls.results = cls.host.invoke(
            "rogue-extension", {"attack": "all"}, actor="red-team", tenant="acme"
        ).value["results"]

    def test_network_modules_are_blocked(self):
        self.assertIn("blocked", self.results["socket_import"])
        self.assertIn("blocked", self.results["subprocess_import"])

    def test_host_files_and_other_extensions_are_unreadable(self):
        self.assertIn("blocked", self.results["read_host_secrets"])
        self.assertIn("blocked", self.results["read_other_extension"])

    def test_filesystem_writes_are_denied(self):
        self.assertIn("blocked", self.results["filesystem_write"])
        self.assertFalse(os.path.exists("/tmp/rogue-was-here"))

    def test_environment_carries_no_ambient_credentials(self):
        self.assertEqual(self.results["environment_secrets"], "none: environment was cleared")

    def test_undeclared_capability_call_is_blocked(self):
        self.assertIn("blocked", self.results["undeclared_capability_call"])

    def test_undeclared_egress_is_blocked(self):
        self.assertIn("blocked", self.results["undeclared_egress"])
        self.assertIn("blocked", self.results["exfiltration"])

    def test_inproc_runtime_refuses_privileged_extensions(self):
        ext = contract.load_manifest(
            os.path.join(INTEGRATIONS, "issue-tracker", "extension.yaml")
        )
        forced = contract.parse({**ext.raw, "runtime": {**ext.raw["runtime"], "type": "local-inproc"}},
                                source_dir=ext.source_dir)
        with self.assertRaises(SandboxError):
            self.host.sandbox.execute(forced, {"action": "read", "params": {"ticket_id": "T-1042"}})

    def test_remote_extension_runs_on_an_attested_worker(self):
        host = fresh_host()
        host.invoke("knowledge-base", {"action": "search", "params": {"query": "sso"}},
                    actor="t", tenant="acme")
        dispatches = host.audit.find("sandbox.remote_dispatch")
        self.assertTrue(dispatches)
        self.assertTrue(dispatches[0].payload["worker"].startswith("remote-worker-"))

    def test_timeout_kills_a_hanging_extension(self):
        host = fresh_host()
        ext = contract.load_manifest(
            os.path.join(INTEGRATIONS, "classify-ticket", "extension.yaml")
        )
        hung = contract.parse(
            {**ext.raw, "runtime": {**ext.raw["runtime"], "entrypoint": "handler.py:missing"}},
            source_dir=ext.source_dir,
        )
        with self.assertRaises(SandboxError):
            host.sandbox.execute(hung, {"action": "classify", "params": {}})


class TestInjection(unittest.TestCase):
    """FR-3: trust boundary, taint propagation, action-confirmation gate."""

    def test_heuristics_detect_planted_instructions(self):
        from runtime.backends import knowledge_base

        poisoned = knowledge_base.state()["KB-207"]["body"]
        self.assertTrue(scan(poisoned))

    def test_agent_output_is_tainted_after_reading_untrusted_content(self):
        host = fresh_host()
        result = host.run_agent("triage-agent", {"ticket_id": "T-1043"}, actor="t", tenant="acme")
        self.assertTrue(result.taint.tainted)
        self.assertTrue(result.taint.signals)

    def test_planted_instruction_does_not_close_a_ticket(self):
        host = fresh_host()
        result = host.run_agent("triage-agent", {"ticket_id": "T-1043"}, actor="t", tenant="acme")
        closes = [o for o in result.outcomes if o.proposal["action"] == "close"]
        self.assertTrue(closes, "the red-team agent should have proposed a close")
        self.assertTrue(all(not o.allowed for o in closes))
        self.assertEqual(issue_tracker.state()["T-1043"]["status"], "open")

    def test_tainted_high_impact_is_refused_even_with_human_approval(self):
        host = fresh_host(confirmation=AlwaysApproveConfirmation())
        outcome = host.perform(
            "issue_tracker", "close", {"ticket_id": "T-1042", "project": "support-billing"},
            actor="t", tenant="acme", origin="human",
            taint=TaintSet(label=UNTRUSTED, sources=["kb:KB-207"]),
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("R-900", " ".join(outcome.reasons))
        self.assertEqual(issue_tracker.state()["T-1042"]["status"], "open")

    def test_untainted_high_impact_needs_confirmation_and_then_proceeds(self):
        denied = fresh_host().perform(
            "issue_tracker", "close", {"ticket_id": "T-1042", "project": "support-billing"},
            actor="t", tenant="acme", origin="human",
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.error, "confirmation_required")

        host = fresh_host(
            confirmation=ScriptedConfirmation({"issue_tracker:close:T-1042": True})
        )
        allowed = host.perform(
            "issue_tracker", "close", {"ticket_id": "T-1042", "project": "support-billing",
                                       "reason": "duplicate"},
            actor="dana@support", tenant="acme", origin="human",
        )
        self.assertTrue(allowed.allowed, allowed.reasons)
        self.assertEqual(issue_tracker.state()["T-1042"]["status"], "closed")

    def test_confirmation_cannot_be_reused_for_another_target(self):
        host = fresh_host(confirmation=ScriptedConfirmation({"issue_tracker:close:T-1042": True}))
        host.perform("issue_tracker", "close",
                     {"ticket_id": "T-1042", "project": "support-billing"},
                     actor="d", tenant="acme", origin="human")
        second = host.perform("issue_tracker", "close",
                              {"ticket_id": "T-1043", "project": "support-platform"},
                              actor="d", tenant="acme", origin="human")
        self.assertFalse(second.allowed)
        self.assertEqual(issue_tracker.state()["T-1043"]["status"], "open")

    def test_hook_vetoes_credential_shaped_output(self):
        host = fresh_host()
        outcome = host.perform(
            "issue_tracker", "comment",
            {"ticket_id": "T-1042", "project": "support-billing",
             "body": "access_token = fixture-issue-tracker-access-token"},
            actor="t", tenant="acme", origin="human",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("hook veto", " ".join(outcome.reasons))

    def test_hook_redacts_customer_pii(self):
        host = fresh_host()
        host.perform(
            "issue_tracker", "comment",
            {"ticket_id": "T-1042", "project": "support-billing",
             "body": "confirmed with dana.reyes@example.com on 555-0142"},
            actor="t", tenant="acme", origin="human",
        )
        comment = issue_tracker.state()["T-1042"]["comments"][-1]["body"]
        self.assertNotIn("dana.reyes@example.com", comment)
        self.assertIn("[redacted-email]", comment)

    def test_untainted_medium_action_is_not_over_blocked(self):
        """Calibration check: taint-free triage still works unattended."""
        host = fresh_host()
        result = host.run_agent("triage-agent", {"ticket_id": "T-1042"}, actor="t", tenant="acme")
        self.assertTrue(result.executed())
        self.assertIn("billing", issue_tracker.state()["T-1042"]["labels"])


class TestGovernance(unittest.TestCase):
    """FR-4: permission review, versioning, deprecation, kill-switch."""

    def test_permission_expansion_on_upgrade_is_refused(self):
        host = fresh_host()
        with self.assertRaises(PermissionExpansionError) as cm:
            host.load(os.path.join(FIXTURES, "classify-ticket-v1.3.0"))
        self.assertIn("issue_tracker", str(cm.exception))
        self.assertEqual(host.registry.get("classify-ticket").version, "1.2.0")

    def test_permission_diff_is_reportable(self):
        old = contract.load_manifest(os.path.join(INTEGRATIONS, "classify-ticket", "extension.yaml"))
        new = contract.load_manifest(os.path.join(FIXTURES, "classify-ticket-v1.3.0", "extension.yaml"))
        diff = contract.diff_permissions(old, new)
        self.assertEqual(len(diff["added"]), 1)
        self.assertFalse(diff["removed"])

    def test_upgrade_loads_after_re_approval(self):
        host = fresh_host()
        new = contract.load_manifest(
            os.path.join(FIXTURES, "classify-ticket-v1.3.0", "extension.yaml")
        )
        host.registry.approve(
            Grant(extension="classify-ticket", versions="1.3.*", permissions=new.permissions,
                  approver="governance-board", review="GOV-201"),
            actor="governance-board",
        )
        host.load(os.path.join(FIXTURES, "classify-ticket-v1.3.0"))
        self.assertEqual(host.registry.get("classify-ticket").version, "1.3.0")
        self.assertTrue(host.audit.find("governance.grant_approved"))

    def test_downgrade_is_refused(self):
        host = fresh_host()
        old = contract.load_manifest(os.path.join(INTEGRATIONS, "classify-ticket", "extension.yaml"))
        downgraded = contract.parse(
            {**old.raw, "metadata": {**old.raw["metadata"], "version": "1.1.0"}},
            source_dir=old.source_dir,
        )
        with self.assertRaises(Exception):
            host.registry.load(downgraded)

    def test_kill_switch_revokes_tokens_and_unloads_host_wide(self):
        host = fresh_host()
        host.invoke("knowledge-base", {"action": "search", "params": {"query": "sso"}},
                    actor="t", tenant="acme")
        outcome = host.kill("knowledge-base", reason="poisoned article KB-207",
                            actor="security-oncall")
        self.assertEqual(outcome["state"], "revoked")
        self.assertEqual(len(host.broker.outstanding("knowledge-base@1.1.2")), 0)
        self.assertIsNone(host.registry.provider_of("knowledge_base.search"))
        with self.assertRaises(Exception):
            host.invoke("knowledge-base", {"action": "search", "params": {"query": "sso"}},
                        actor="t", tenant="acme")
        kills = host.audit.find("governance.kill_switch")
        self.assertEqual(kills[0].actor, "security-oncall")

    def test_killed_extension_cannot_be_reloaded_without_clearance(self):
        host = fresh_host()
        host.kill("cicd-status", reason="test", actor="security-oncall")
        with self.assertRaises(RevokedError):
            host.load(os.path.join(INTEGRATIONS, "cicd-status"))
        host.registry.clear_revocation("cicd-status", actor="governance-board", review="GOV-999")
        host.load(os.path.join(INTEGRATIONS, "cicd-status"))
        self.assertIsNone(host.registry.liveness_problem("cicd-status"))

    def test_deprecation_is_recorded_without_breaking_callers(self):
        host = fresh_host()
        host.registry.deprecate("cicd-status", successor="cicd-status@1.0.0",
                                sunset="2026-12-01", actor="governance-board")
        self.assertIsNone(host.registry.liveness_problem("cicd-status"))
        row = [r for r in host.registry.inspect() if r["ref"].startswith("cicd-status")][0]
        self.assertEqual(row["state"], "deprecated")
        self.assertEqual(row["deprecation"]["sunset"], "2026-12-01")

    def test_agent_kill_switch_stops_the_whole_flow(self):
        host = fresh_host()
        host.kill("triage-agent", reason="prompt-injection incident INC-42", actor="security-oncall")
        with self.assertRaises(Exception):
            host.run_agent("triage-agent", {"ticket_id": "T-1042"}, actor="t", tenant="acme")


class TestIntegrations(unittest.TestCase):
    """FR-5: three integrations, exercised through the contract only."""

    def setUp(self):
        self.host = fresh_host()

    def test_issue_tracker_read_through_the_contract(self):
        result = self.host.invoke("issue-tracker",
                                  {"action": "read", "params": {"ticket_id": "T-1042"}},
                                  actor="t", tenant="acme")
        self.assertEqual(result.value["data"]["id"], "T-1042")

    def test_knowledge_base_is_read_only_by_contract(self):
        ext = self.host.registry.get("knowledge-base")
        self.assertIsNone(ext.find_permission("knowledge_base", "write"))
        outcome = self.host.perform("knowledge_base", "write", {"article_id": "KB-101"},
                                    actor="t", tenant="acme", origin="human")
        self.assertFalse(outcome.allowed)

    def test_cicd_status_enriches_triage(self):
        result = self.host.invoke("cicd-status",
                                  {"action": "read", "params": {"service": "support-platform"}},
                                  actor="t", tenant="acme")
        self.assertEqual(result.value["data"]["latest"]["status"], "failed")

    def test_all_integrations_declare_their_egress(self):
        for name in ("issue-tracker", "knowledge-base", "cicd-status"):
            ext = self.host.registry.get(name)
            self.assertTrue(ext.egress_allow)
            self.assertTrue(ext.delegated_auth)
            self.assertEqual(ext.output_class, "untrusted")

    def test_egress_outside_the_allowlist_is_refused(self):
        ext = self.host.registry.get("issue-tracker")
        grant = self.host.broker.mint(
            extension=ext.ref, tenant="acme", resource="issue_tracker", actions=("read",),
            secret_ref="secrets/issue-tracker/oauth-client", intent_hash="x",
        )
        with self.assertRaises(EgressDenied):
            self.host.egress.request(
                extension=ext.ref, allowlist=ext.egress_allow, handle=grant.handle,
                method="GET", url="https://kb.example.internal/api/articles/KB-101",
                body={}, resource="issue_tracker", action="read",
            )

    def test_full_triage_flow_touches_all_three_integrations(self):
        result = self.host.run_agent("triage-agent", {"ticket_id": "T-1043"},
                                     actor="t", tenant="acme")
        destinations = {
            r.payload["destination"] for r in self.host.audit.find("egress.call")
        }
        self.assertEqual(
            destinations,
            {"issues.example.internal", "kb.example.internal", "ci.example.internal"},
        )
        self.assertIn("ci:run-9931", result.value["sources"])


class TestAuditability(unittest.TestCase):
    """NFR-4: every action attributable, permissions inspectable, log tamper-evident."""

    def test_every_gate_decision_is_attributable(self):
        host = fresh_host()
        host.run_agent("triage-agent", {"ticket_id": "T-1043"}, actor="alice@support",
                       tenant="acme")
        decisions = host.audit.find("gate.allowed") + host.audit.find("gate.denied")
        self.assertTrue(decisions)
        for record in decisions:
            self.assertTrue(record.actor)
            self.assertTrue(record.extension)
            self.assertIn("resource", record.payload)

    def test_log_is_hash_chained_and_tamper_evident(self):
        host = fresh_host()
        host.invoke("classify-ticket",
                    {"action": "classify", "params": {"subject": "x", "body": "login fails"}},
                    actor="t", tenant="acme")
        self.assertTrue(host.audit.verify())
        host.audit.records[2].payload["tampered"] = True
        self.assertFalse(host.audit.verify())

    def test_loaded_permissions_and_versions_are_inspectable(self):
        host = fresh_host()
        rows = {r["ref"]: r for r in host.registry.inspect()}
        self.assertIn("triage-agent@2.1.0", rows)
        self.assertEqual(rows["triage-agent@2.1.0"]["grant_review"], "GOV-150")
        self.assertIn("issue_tracker:read@tenant=${caller.tenant}",
                      rows["triage-agent@2.1.0"]["permissions"])

    def test_secret_metadata_is_inspectable_but_values_are_not(self):
        host = fresh_host()
        described = host.describe()
        self.assertNotIn("fixture-", str(described["secrets"]))
        self.assertTrue(described["audit_chain_valid"])


# --------------------------------------------------------------------------- #


def _minimal_manifest() -> dict:
    return {
        "apiVersion": "ext/v1",
        "kind": "tool",
        "metadata": {"name": "probe-tool", "version": "0.1.0", "owner": "team-test"},
        "runtime": {"type": "local-subprocess", "entrypoint": "handler.py:handle",
                    "network": "deny"},
        "capabilities": {"provides": ["probe.run"]},
        "io": {"input": {}, "output": {}},
        "lifecycle": {"on_load": "validate_schema"},
    }


if __name__ == "__main__":
    unittest.main(verbosity=2)
