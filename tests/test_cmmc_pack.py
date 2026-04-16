"""Tests for the CMMC Level 2 rule pack.

Covers CUI access control (AC.L2), audit traceability (AU.L2), and
incident handling (IR.L2) practices with positive and negative cases
for each rule.  CMMC depends on the NIST 800-53 rule pack for shared
templates (data_transfer, audit_event) and the nist module.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.models import LogLevel

# ---------------------------------------------------------------------------
# Pack directory resolution
# ---------------------------------------------------------------------------

_nist_pkg = importlib.import_module("fathom.rule_packs.nist_800_53")
NIST_DIR = Path(_nist_pkg.__path__[0])

_cmmc_pkg = importlib.import_module("fathom.rule_packs.cmmc")
CMMC_DIR = Path(_cmmc_pkg.__path__[0])


@pytest.fixture
def cmmc_engine() -> Engine:
    """Engine loaded with NIST (dependency) then CMMC rule pack."""
    e = Engine()
    # Load NIST first (templates: access_request, audit_event, data_transfer; module: nist)
    e.load_templates(str(NIST_DIR / "templates"))
    e.load_modules(str(NIST_DIR / "modules"))
    e.load_rules(str(NIST_DIR / "rules"))
    # Load CMMC on top (template: cui_policy; module: cmmc; rules reference nist templates too)
    e.load_templates(str(CMMC_DIR / "templates"))
    e.load_modules(str(CMMC_DIR / "modules"))
    e.load_rules(str(CMMC_DIR / "rules"))
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
    """IR.L2-3.6.1: escalate on CUI access matching incident pattern.

    The temporal count_exceeds threshold is metadata-only until temporal
    operators are wired into rule compilation.  The rule currently fires
    whenever a cui_policy fact has action in [read, write, admin, export].
    """

    def test_incident_trigger_fires_on_matching_access(self, cmmc_engine: Engine) -> None:
        """CUI access with matching action triggers incident handling rule."""
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "analyst-1",
                "resource": "cui-doc-1",
                "action": "read",
                "justification": "authorized review",
            },
        )
        result = cmmc_engine.evaluate()
        assert "cmmc::ir-l2-incident-handling" in result.rule_trace

    def test_incident_handling_salience_wins(self, cmmc_engine: Engine) -> None:
        """IR rule (salience 200) should produce escalate when justified."""
        cmmc_engine.assert_fact(
            "cui_policy",
            {
                "subject": "user-1",
                "resource": "cui-doc-1",
                "action": "write",
                "justification": "authorized task",
            },
        )
        result = cmmc_engine.evaluate()
        assert result.decision == "escalate"
        assert "IR.L2-3.6.1" in (result.reason or "")


# =========================================================================
# Rule metadata validation
# =========================================================================


class TestCMMCRuleMetadata:
    """Verify salience and log-level metadata across CMMC rules."""

    def test_all_deny_rules_salience_gte_100(self, cmmc_ruleset) -> None:
        for rule in cmmc_ruleset.rules:
            if rule.then.action.value == "deny":
                assert rule.salience >= 100, (
                    f"Deny rule '{rule.name}' has salience {rule.salience} < 100"
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
