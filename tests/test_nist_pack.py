"""Tests for the NIST SP 800-53 rule pack.

Covers AC (Access Control), AU (Audit and Accountability), and
SC (System and Communications Protection) rule families with
positive and negative cases for each rule.
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
PACK_DIR = str(Path(_nist_pkg.__path__[0]))


@pytest.fixture
def nist_engine() -> Engine:
    """Fresh Engine loaded with the NIST 800-53 rule pack."""
    return Engine.from_rules(PACK_DIR)


@pytest.fixture
def nist_rulesets():
    """Parsed rulesets from all NIST rule YAML files."""
    c = Compiler()
    rules_dir = Path(PACK_DIR) / "rules"
    return [c.parse_rule_file(f) for f in sorted(rules_dir.glob("*.yaml"))]


# =========================================================================
# Pack loading
# =========================================================================


class TestNISTPackLoading:
    """Verify the NIST pack loads successfully."""

    def test_pack_loads_successfully(self, nist_engine: Engine) -> None:
        assert len(nist_engine._template_registry) >= 3

    def test_access_request_template_registered(self, nist_engine: Engine) -> None:
        assert "access_request" in nist_engine._template_registry

    def test_audit_event_template_registered(self, nist_engine: Engine) -> None:
        assert "audit_event" in nist_engine._template_registry

    def test_data_transfer_template_registered(self, nist_engine: Engine) -> None:
        assert "data_transfer" in nist_engine._template_registry

    def test_nist_module_registered(self, nist_engine: Engine) -> None:
        assert "nist" in nist_engine._module_registry


# =========================================================================
# AC-3: Access Enforcement
# =========================================================================


class TestAccessEnforcement:
    """AC-3: deny unclassified subject accessing classified resource."""

    def test_unclassified_accessing_classified_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "classified-doc",
                "action": "read",
                "clearance": "unclassified",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "AC-3" in (result.reason or "")

    def test_unclassified_accessing_restricted_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "restricted-area",
                "action": "read",
                "clearance": "unclassified",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_unclassified_accessing_public_not_denied(self, nist_engine: Engine) -> None:
        """Unclassified user accessing a public resource should NOT trigger AC-3."""
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "public-docs",
                "action": "read",
                "clearance": "unclassified",
            },
        )
        result = nist_engine.evaluate()
        # AC-3 shouldn't fire: resource not classified/restricted/secret/top.secret
        assert "AC-3" not in (result.reason or "")


# =========================================================================
# AC-4: Information Flow Enforcement
# =========================================================================


class TestInfoFlowEnforcement:
    """AC-4: deny classified data flowing to external destinations."""

    def test_secret_to_external_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "external-api",
                "classification": "secret",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "nist::info-flow-enforcement" in result.rule_trace

    def test_confidential_to_public_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "public-site",
                "classification": "confidential",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_unclassified_to_external_not_denied(self, nist_engine: Engine) -> None:
        """Unclassified data to external should NOT trigger AC-4."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "external-api",
                "classification": "unclassified",
            },
        )
        result = nist_engine.evaluate()
        # AC-4 should not fire; may still be denied by SC-7 (boundary protection)
        assert "AC-4" not in (result.reason or "")

    def test_secret_to_internal_not_denied(self, nist_engine: Engine) -> None:
        """Secret data staying internal should NOT trigger AC-4."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "internal-archive",
                "classification": "secret",
            },
        )
        result = nist_engine.evaluate()
        assert "AC-4" not in (result.reason or "")


# =========================================================================
# AC-6: Least Privilege
# =========================================================================


class TestLeastPrivilege:
    """AC-6: deny privileged actions without context justification."""

    def test_admin_without_context_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "admin-1",
                "resource": "server-config",
                "action": "admin",
                "context": "",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "AC-6" in (result.reason or "")

    def test_delete_without_context_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "records",
                "action": "delete",
                "context": "",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_admin_with_context_not_denied_by_ac6(self, nist_engine: Engine) -> None:
        """Privileged action WITH context justification should NOT trigger AC-6."""
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "admin-1",
                "resource": "server-config",
                "action": "admin",
                "context": "approved maintenance window",
            },
        )
        result = nist_engine.evaluate()
        assert "AC-6" not in (result.reason or "")

    def test_read_without_context_not_denied_by_ac6(self, nist_engine: Engine) -> None:
        """Non-privileged action (read) should NOT trigger AC-6."""
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "public-docs",
                "action": "read",
                "context": "",
            },
        )
        result = nist_engine.evaluate()
        assert "AC-6" not in (result.reason or "")


# =========================================================================
# AC-17: Remote Access
# =========================================================================


class TestRemoteAccess:
    """AC-17: escalate remote privileged actions."""

    def test_remote_admin_escalated(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "remote-admin",
                "resource": "server",
                "action": "admin",
                "context": "remote-session",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"
        assert "AC-17" in (result.reason or "")

    def test_vpn_escalate_escalated(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "server",
                "action": "escalate",
                "context": "vpn-connection",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"

    def test_local_admin_not_escalated_by_ac17(self, nist_engine: Engine) -> None:
        """Local (non-remote) admin should NOT trigger AC-17."""
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "admin-1",
                "resource": "server",
                "action": "admin",
                "context": "local-console",
            },
        )
        result = nist_engine.evaluate()
        assert "AC-17" not in (result.reason or "")

    def test_remote_read_not_escalated_by_ac17(self, nist_engine: Engine) -> None:
        """Remote non-privileged action (read) should NOT trigger AC-17."""
        nist_engine.assert_fact(
            "access_request",
            {
                "subject": "user-1",
                "resource": "docs",
                "action": "read",
                "context": "remote-session",
            },
        )
        result = nist_engine.evaluate()
        assert "AC-17" not in (result.reason or "")


# =========================================================================
# AU-2: Audit Events
# =========================================================================


class TestAuditEvents:
    """AU-2: escalate auditable events with unknown outcome."""

    def test_login_unknown_outcome_escalated(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "login",
                "subject": "user-1",
                "outcome": "unknown",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"
        assert "AU-2" in (result.reason or "")

    def test_delete_unknown_outcome_escalated(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "delete",
                "subject": "user-1",
                "resource": "doc-1",
                "outcome": "unknown",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"

    def test_login_success_not_escalated(self, nist_engine: Engine) -> None:
        """Auditable event with known outcome should NOT trigger AU-2."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "login",
                "subject": "user-1",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-2" not in (result.reason or "")

    def test_non_audit_event_not_escalated(self, nist_engine: Engine) -> None:
        """Non-auditable event type with unknown outcome should NOT trigger AU-2."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "heartbeat",
                "subject": "system",
                "outcome": "unknown",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-2" not in (result.reason or "")


# =========================================================================
# AU-3: Content of Audit Records
# =========================================================================


class TestAuditContent:
    """AU-3: deny audit records missing subject."""

    def test_empty_subject_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "",
                "resource": "doc-1",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "nist::audit-content" in result.rule_trace

    def test_present_subject_not_denied_by_au3(self, nist_engine: Engine) -> None:
        """Audit record with subject should NOT trigger AU-3."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "doc-1",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-3" not in (result.reason or "")


# =========================================================================
# AU-6: Audit Review, Analysis, and Reporting
# =========================================================================


class TestAuditReview:
    """AU-6: escalate failed privileged actions."""

    def test_failed_escalate_event(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "escalate",
                "subject": "user-1",
                "outcome": "denied",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"
        assert "AU-6" in (result.reason or "")

    def test_failed_delete_event(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "delete",
                "subject": "user-1",
                "outcome": "failed",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "escalate"

    def test_successful_escalate_not_triggered(self, nist_engine: Engine) -> None:
        """Successful privileged action should NOT trigger AU-6."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "escalate",
                "subject": "user-1",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-6" not in (result.reason or "")

    def test_failed_login_not_triggered(self, nist_engine: Engine) -> None:
        """Failed non-privileged event (login) should NOT trigger AU-6."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "login",
                "subject": "user-1",
                "outcome": "failed",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-6" not in (result.reason or "")


# =========================================================================
# AU-12: Audit Generation
# =========================================================================


class TestAuditGeneration:
    """AU-12: deny data events without resource identification."""

    def test_access_event_without_resource_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "AU-12" in (result.reason or "")

    def test_modify_event_without_resource_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "modify",
                "subject": "user-1",
                "resource": "",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_access_event_with_resource_not_denied_by_au12(self, nist_engine: Engine) -> None:
        """Data event with resource should NOT trigger AU-12."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "access",
                "subject": "user-1",
                "resource": "doc-1",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-12" not in (result.reason or "")

    def test_login_event_without_resource_not_denied_by_au12(self, nist_engine: Engine) -> None:
        """Non-data event type (login) without resource should NOT trigger AU-12."""
        nist_engine.assert_fact(
            "audit_event",
            {
                "event_type": "login",
                "subject": "user-1",
                "resource": "",
                "outcome": "success",
                "ts": 1700000000.0,
            },
        )
        result = nist_engine.evaluate()
        assert "AU-12" not in (result.reason or "")


# =========================================================================
# SC-7: Boundary Protection
# =========================================================================


class TestBoundaryProtection:
    """SC-7: deny external transfers over insecure protocols."""

    def test_external_plaintext_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "external-api",
                "protocol": "plaintext",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "SC-7" in (result.reason or "")

    def test_public_ftp_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "file-server",
                "destination": "public-site",
                "protocol": "ftp",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_external_tls_not_denied_by_sc7(self, nist_engine: Engine) -> None:
        """Secure protocol to external destination should NOT trigger SC-7."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "internal-db",
                "destination": "external-api",
                "classification": "unclassified",
                "protocol": "tls",
            },
        )
        result = nist_engine.evaluate()
        assert "SC-7" not in (result.reason or "")

    def test_internal_plaintext_not_denied_by_sc7(self, nist_engine: Engine) -> None:
        """Insecure protocol to internal destination should NOT trigger SC-7."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "app-server",
                "destination": "internal-db",
                "protocol": "plaintext",
            },
        )
        result = nist_engine.evaluate()
        assert "SC-7" not in (result.reason or "")


# =========================================================================
# SC-16: Transmission of Security and Privacy Attributes
# =========================================================================


class TestTransmissionConfidentiality:
    """SC-16: deny classified data over insecure protocols."""

    def test_secret_over_plaintext_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "secure-db",
                "destination": "internal-archive",
                "classification": "secret",
                "protocol": "plaintext",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"
        assert "SC-16" in (result.reason or "")

    def test_confidential_over_ftp_denied(self, nist_engine: Engine) -> None:
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "secure-db",
                "destination": "backup-server",
                "classification": "confidential",
                "protocol": "ftp",
            },
        )
        result = nist_engine.evaluate()
        assert result.decision == "deny"

    def test_secret_over_tls_not_denied_by_sc16(self, nist_engine: Engine) -> None:
        """Classified data over secure protocol should NOT trigger SC-16."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "secure-db",
                "destination": "internal-archive",
                "classification": "secret",
                "protocol": "tls",
            },
        )
        result = nist_engine.evaluate()
        assert "SC-16" not in (result.reason or "")

    def test_unclassified_over_plaintext_not_denied_by_sc16(self, nist_engine: Engine) -> None:
        """Unclassified data over insecure protocol should NOT trigger SC-16."""
        nist_engine.assert_fact(
            "data_transfer",
            {
                "source": "app-server",
                "destination": "internal-db",
                "classification": "unclassified",
                "protocol": "plaintext",
            },
        )
        result = nist_engine.evaluate()
        assert "SC-16" not in (result.reason or "")


# =========================================================================
# Rule metadata validation
# =========================================================================


class TestNISTRuleMetadata:
    """Verify salience and log-level metadata across all NIST rules."""

    def test_all_deny_rules_salience_gte_80(self, nist_rulesets) -> None:
        for ruleset in nist_rulesets:
            for rule in ruleset.rules:
                if rule.then.action.value == "deny":
                    assert rule.salience >= 80, (
                        f"Deny rule '{rule.name}' has salience {rule.salience} < 80"
                    )

    def test_all_rules_use_log_full(self, nist_rulesets) -> None:
        for ruleset in nist_rulesets:
            for rule in ruleset.rules:
                assert rule.then.log == LogLevel.FULL, (
                    f"Rule '{rule.name}' uses log={rule.then.log}, expected full"
                )

    def test_pack_has_at_least_ten_rules(self, nist_rulesets) -> None:
        total = sum(len(rs.rules) for rs in nist_rulesets)
        assert total >= 10
