"""Tests for the CMMC Level 2 rule pack.

Covers CUI access control (AC.L2), audit traceability (AU.L2), and
incident handling (IR.L2) practices with positive and negative cases
for each rule.  CMMC depends on the NIST 800-53 rule pack for shared
templates (data_transfer, audit_event) and the nist module.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path

import pytest

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.models import LogLevel

# ---------------------------------------------------------------------------
# Pack directory resolution
# ---------------------------------------------------------------------------

_cmmc_pkg = importlib.import_module("fathom.rule_packs.cmmc")
CMMC_DIR = Path(_cmmc_pkg.__path__[0])


@pytest.fixture
def cmmc_engine() -> Engine:
    """Engine loaded with the CMMC pack through its own entry point.

    The pack declares ``PACK_DEPENDENCIES = ("nist-800-53",)``, so the
    loader pulls in the NIST templates (audit_event, data_transfer) and
    the nist module first -- no hand-rolled two-pack fixture.
    """
    e = Engine()
    e.load_pack("cmmc")
    return e


@pytest.fixture
def cmmc_ruleset():
    """Parsed ruleset metadata from the CMMC rules YAML."""
    c = Compiler()
    rules_path = CMMC_DIR / "rules" / "cmmc_rules.yaml"
    return c.parse_rule_file(rules_path)


# =========================================================================
# Pack loading
# =========================================================================


class TestCMMCPackLoading:
    """Verify the CMMC pack loads on top of NIST."""

    def test_cui_policy_template_registered(self, cmmc_engine: Engine) -> None:
        assert "cui_policy" in cmmc_engine._template_registry

    def test_nist_templates_available(self, cmmc_engine: Engine) -> None:
        assert "data_transfer" in cmmc_engine._template_registry
        assert "audit_event" in cmmc_engine._template_registry

    def test_cmmc_module_registered(self, cmmc_engine: Engine) -> None:
        assert "cmmc" in cmmc_engine._module_registry

    def test_nist_module_registered(self, cmmc_engine: Engine) -> None:
        assert "nist" in cmmc_engine._module_registry


# =========================================================================
# AC.L2-3.1.1: Authorized Access Control
# =========================================================================


class TestAuthorizedAccess:
    """AC.L2-3.1.1: deny CUI access without justification."""

    def test_read_without_justification_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-document",
                "action": "read",
                "justification": "",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"
        assert "AC.L2-3.1.1" in (result.reason or "")

    def test_write_without_justification_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-document",
                "action": "write",
                "justification": "",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"

    def test_read_with_justification_not_denied(self, cmmc_engine: Engine) -> None:
        """CUI access WITH justification should NOT trigger AC.L2-3.1.1."""
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-document",
                "action": "read",
                "justification": "project requirement",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert "AC.L2-3.1.1" not in (result.reason or "")


# =========================================================================
# AC.L2-3.1.3: CUI Flow Enforcement
# =========================================================================


class TestCUIFlow:
    """AC.L2-3.1.3: deny CUI data flowing to external destinations."""

    def test_cui_to_external_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-server",
                "destination": "external-api",
                "classification": "cui_basic",
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"
        assert "cmmc::ac-l2-cui-flow" in result.rule_trace

    def test_cui_specified_to_public_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "data_transfer",
            {
                "source": "secure-store",
                "destination": "public-site",
                "classification": "cui_specified",
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"

    def test_unclassified_to_external_no_cmmc_deny(self, cmmc_engine: Engine) -> None:
        """Unclassified data to external should NOT trigger AC.L2-3.1.3."""
        cmmc_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-server",
                "destination": "external-api",
                "classification": "unclassified",
            },
        )
        result = cmmc_engine.evaluate()
        assert "AC.L2-3.1.3" not in (result.reason or "")

    def test_cui_to_internal_not_denied(self, cmmc_engine: Engine) -> None:
        """CUI data staying internal should NOT trigger AC.L2-3.1.3."""
        cmmc_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-server",
                "destination": "internal-archive",
                "classification": "cui_basic",
            },
        )
        result = cmmc_engine.evaluate()
        assert "AC.L2-3.1.3" not in (result.reason or "")


# =========================================================================
# AC.L2-3.1.5: Least Privilege
# =========================================================================


class TestCUILeastPrivilege:
    """AC.L2-3.1.5: deny privileged CUI actions without justification."""

    def test_admin_without_justification_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "admin-1",
                "resource": "cui-system",
                "action": "admin",
                "justification": "",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"
        assert "AC.L2-3.1.5" in (result.reason or "")

    def test_delete_without_justification_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-records",
                "action": "delete",
                "justification": "",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"

    def test_admin_with_justification_not_denied(self, cmmc_engine: Engine) -> None:
        """Privileged action WITH justification should NOT trigger AC.L2-3.1.5."""
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "admin-1",
                "resource": "cui-system",
                "action": "admin",
                "justification": "authorized maintenance",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert "AC.L2-3.1.5" not in (result.reason or "")

    def test_read_without_justification_not_least_priv(self, cmmc_engine: Engine) -> None:
        """Non-privileged action (read) should NOT trigger AC.L2-3.1.5.

        Note: AC.L2-3.1.1 may still fire, but AC.L2-3.1.5 should not.
        """
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-document",
                "action": "read",
                "justification": "",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        # read is not in [admin, escalate, override, delete]
        assert "AC.L2-3.1.5" not in (result.reason or "")


# =========================================================================
# AU.L2-3.3.1: System Audit Records
# =========================================================================


class TestCUIAuditRecords:
    """AU.L2-3.3.1: escalate audit events with unknown outcome."""

    def test_access_unknown_outcome_escalated(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "cui-doc",
                "outcome": "unknown",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "escalate"
        assert "AU.L2-3.3.1" in (result.reason or "") or "AU-2" in (result.reason or "")

    def test_export_unknown_outcome_escalated(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "export",
                "subject": "user-1",
                "resource": "cui-data",
                "outcome": "unknown",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "escalate"

    def test_access_success_not_escalated(self, cmmc_engine: Engine) -> None:
        """Known outcome should NOT trigger AU.L2-3.3.1."""
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "cui-doc",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert "AU.L2-3.3.1" not in (result.reason or "")


# =========================================================================
# AU.L2-3.3.2: Audit Traceability
# =========================================================================


class TestAuditTraceability:
    """AU.L2-3.3.2: deny audit events without subject identity."""

    def test_access_without_subject_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "",
                "resource": "cui-doc",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"
        assert "AU.L2-3.3.2" in (result.reason or "") or "AU-3" in (result.reason or "")

    def test_modify_without_subject_denied(self, cmmc_engine: Engine) -> None:
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "modify",
                "subject": "",
                "resource": "cui-doc",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "deny"

    def test_access_with_subject_not_denied(self, cmmc_engine: Engine) -> None:
        """Audit event with subject should NOT trigger AU.L2-3.3.2."""
        cmmc_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "cui-doc",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = cmmc_engine.evaluate()
        assert "AU.L2-3.3.2" not in (result.reason or "")


# =========================================================================
# IR.L2-3.6.1: Incident Handling
# =========================================================================


class TestIncidentHandling:
    """IR.L2-3.6.1: escalate on more than 20 CUI reads in 600s.

    The threshold is compiled as a ``rate_exceeds`` condition on the ts
    slot, so a single access must not be reported as an incident.
    """

    def test_single_access_does_not_trigger_incident(self, cmmc_engine: Engine) -> None:
        """One justified read is not an IR.L2-3.6.1 incident."""
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "analyst-1",
                "resource": "cui-doc-1",
                "action": "read",
                "justification": "authorized review",
                "ts": time.time(),
            },
        )
        result = cmmc_engine.evaluate()
        assert "cmmc::ir-l2-incident-handling" not in result.rule_trace
        assert "IR.L2-3.6.1" not in (result.reason or "")

    def test_bulk_reads_within_window_trigger_incident(self, cmmc_engine: Engine) -> None:
        """More than 20 reads inside the 600s window escalates."""
        for i in range(21):
            cmmc_engine.assert_fact(
                "cui_policy",
                {
                    "subject": "analyst-1",
                    "resource": f"cui-doc-{i}",
                    "action": "read",
                    "justification": "authorized review",
                    "ts": time.time(),
                },
            )
        result = cmmc_engine.evaluate()
        assert "cmmc::ir-l2-incident-handling" in result.rule_trace
        assert result.decision == "escalate"
        assert "IR.L2-3.6.1" in (result.reason or "")

    def test_bulk_reads_outside_window_do_not_trigger(self, cmmc_engine: Engine) -> None:
        """Reads older than the 600s window do not count toward the threshold."""
        stale = time.time() - 7200
        for i in range(25):
            cmmc_engine.assert_fact(
                "cui_policy",
                {
                    "subject": "analyst-1",
                    "resource": f"cui-doc-{i}",
                    "action": "read",
                    "justification": "authorized review",
                    "ts": stale,
                },
            )
        result = cmmc_engine.evaluate()
        assert "cmmc::ir-l2-incident-handling" not in result.rule_trace

    def test_incident_metadata_reaches_the_result(self, cmmc_engine: Engine) -> None:
        """Practice metadata is emitted with the decision, not silently dropped."""
        for i in range(21):
            cmmc_engine.assert_fact(
                "cui_policy",
                {
                    "subject": "analyst-1",
                    "resource": f"cui-doc-{i}",
                    "action": "read",
                    "justification": "authorized review",
                    "ts": time.time(),
                },
            )
        result = cmmc_engine.evaluate()
        assert result.metadata["cmmc_practice"] == "IR.L2-3.6.1"
        assert result.metadata["cmmc_level"] == "2"
        assert result.metadata["threshold"] == "20"


# =========================================================================
# Rule metadata validation
# =========================================================================


class TestCMMCRuleMetadata:
    """Verify salience and log-level metadata across CMMC rules."""

    def test_deny_salience_below_every_escalate(self, cmmc_ruleset) -> None:
        """Severity must be monotone in reverse salience (last write wins)."""
        deny_saliences = [r.salience for r in cmmc_ruleset.rules if r.then.action.value == "deny"]
        escalate_saliences = [
            r.salience for r in cmmc_ruleset.rules if r.then.action.value == "escalate"
        ]
        assert deny_saliences and escalate_saliences
        assert max(deny_saliences) < min(escalate_saliences), (
            f"deny saliences {deny_saliences} must all be below "
            f"escalate saliences {escalate_saliences}"
        )

    def test_incident_handling_highest_salience(self, cmmc_ruleset) -> None:
        ir_rule = next(r for r in cmmc_ruleset.rules if r.name == "ir-l2-incident-handling")
        assert ir_rule.salience == 200

    def test_all_rules_use_log_full(self, cmmc_ruleset) -> None:
        for rule in cmmc_ruleset.rules:
            assert rule.then.log == LogLevel.FULL, (
                f"Rule '{rule.name}' uses log={rule.then.log}, expected full"
            )

    def test_pack_has_at_least_six_rules(self, cmmc_ruleset) -> None:
        assert len(cmmc_ruleset.rules) >= 6
