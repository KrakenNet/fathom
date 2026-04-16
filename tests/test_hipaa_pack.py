"""Tests for the HIPAA Privacy and Security Rule pack.

Covers minimum necessary standard (164.502(b)), transmission security
(164.312(e)(1)), and breach notification trigger (164.402) with
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

_hipaa_pkg = importlib.import_module("fathom.rule_packs.hipaa")
PACK_DIR = str(Path(_hipaa_pkg.__path__[0]))


@pytest.fixture
def hipaa_engine() -> Engine:
    """Fresh Engine loaded with the HIPAA rule pack."""
    return Engine.from_rules(PACK_DIR)


@pytest.fixture
def hipaa_ruleset():
    """Parsed ruleset metadata from the HIPAA rules YAML."""
    c = Compiler()
    rules_path = Path(PACK_DIR) / "rules" / "hipaa_rules.yaml"
    return c.parse_rule_file(rules_path)


# =========================================================================
# Pack loading
# =========================================================================


class TestHIPAAPackLoading:
    """Verify the HIPAA pack loads successfully."""

    def test_pack_loads_successfully(self, hipaa_engine: Engine) -> None:
        assert len(hipaa_engine._template_registry) >= 2

    def test_phi_policy_template_registered(self, hipaa_engine: Engine) -> None:
        assert "phi_policy" in hipaa_engine._template_registry

    def test_data_transfer_template_registered(self, hipaa_engine: Engine) -> None:
        assert "data_transfer" in hipaa_engine._template_registry

    def test_hipaa_module_registered(self, hipaa_engine: Engine) -> None:
        assert "hipaa" in hipaa_engine._module_registry


# =========================================================================
# 164.502(b): Minimum Necessary Standard
# =========================================================================


class TestMinimumNecessary:
    """Minimum necessary: deny PHI access without justification."""

    def test_read_without_justification_denied(self, hipaa_engine: Engine) -> None:
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "nurse",
                "access_level": "read",
                "justification": "",
            },
        )
        result = hipaa_engine.evaluate()
        assert result.decision == "deny"
        assert "164.502(b)" in (result.reason or "")

    def test_write_without_justification_denied(self, hipaa_engine: Engine) -> None:
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "doctor",
                "access_level": "write",
                "justification": "",
            },
        )
        result = hipaa_engine.evaluate()
        assert result.decision == "deny"

    def test_admin_without_justification_denied(self, hipaa_engine: Engine) -> None:
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "admin",
                "access_level": "admin",
                "justification": "",
            },
        )
        result = hipaa_engine.evaluate()
        assert result.decision == "deny"

    def test_read_with_justification_not_denied(self, hipaa_engine: Engine) -> None:
        """PHI access with justification should NOT trigger minimum necessary."""
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "nurse",
                "access_level": "read",
                "justification": "patient care coordination",
            },
        )
        result = hipaa_engine.evaluate()
        assert "164.502(b)" not in (result.reason or "")


# =========================================================================
# 164.312(e)(1): Transmission Security
# =========================================================================


class TestTransmissionSecurity:
    """Transmission security: deny unencrypted PHI transfers."""

    def test_unencrypted_phi_transfer_denied(self, hipaa_engine: Engine) -> None:
        hipaa_engine.assert_fact(
            "data_transfer",
            {
                "source": "ehr-system",
                "destination": "lab-system",
                "data_type": "phi",
                "encrypted": "FALSE",
            },
        )
        result = hipaa_engine.evaluate()
        assert result.decision == "deny"
        assert "164.312(e)(1)" in (result.reason or "")

    def test_encrypted_phi_transfer_not_denied(self, hipaa_engine: Engine) -> None:
        """Encrypted PHI transfer should NOT trigger transmission security."""
        hipaa_engine.assert_fact(
            "data_transfer",
            {
                "source": "ehr-system",
                "destination": "lab-system",
                "data_type": "phi",
                "encrypted": "TRUE",
            },
        )
        result = hipaa_engine.evaluate()
        assert "164.312(e)(1)" not in (result.reason or "")

    def test_non_phi_unencrypted_not_denied(self, hipaa_engine: Engine) -> None:
        """Non-PHI unencrypted transfer should NOT trigger transmission security."""
        hipaa_engine.assert_fact(
            "data_transfer",
            {
                "source": "web-server",
                "destination": "cdn",
                "data_type": "public",
                "encrypted": "FALSE",
            },
        )
        result = hipaa_engine.evaluate()
        assert "164.312(e)(1)" not in (result.reason or "")


# =========================================================================
# 164.402: Breach Notification Trigger
# =========================================================================


class TestBreachNotification:
    """Breach trigger (164.402): escalate on PHI access matching breach pattern.

    The temporal count_exceeds threshold is metadata-only until temporal
    operators are wired into rule compilation.  The rule currently fires
    whenever a phi_policy fact has access_level in [read, write, admin].
    """

    def test_breach_trigger_fires_on_matching_access(self, hipaa_engine: Engine) -> None:
        """PHI access with matching access_level triggers breach rule."""
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "analyst",
                "access_level": "read",
                "justification": "audit review",
            },
        )
        result = hipaa_engine.evaluate()
        assert "hipaa::breach-trigger" in result.rule_trace

    def test_breach_trigger_salience_wins(self, hipaa_engine: Engine) -> None:
        """Breach trigger (salience 200) should produce escalate when justified."""
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "nurse",
                "access_level": "read",
                "justification": "patient care",
            },
        )
        result = hipaa_engine.evaluate()
        assert result.decision == "escalate"
        assert "164.402" in (result.reason or "")


# =========================================================================
# Rule metadata validation
# =========================================================================


class TestHIPAARuleMetadata:
    """Verify salience and log-level metadata across HIPAA rules."""

    def test_all_deny_rules_salience_gte_100(self, hipaa_ruleset) -> None:
        for rule in hipaa_ruleset.rules:
            if rule.then.action.value == "deny":
                assert rule.salience >= 100, (
                    f"Deny rule '{rule.name}' has salience {rule.salience} < 100"
                )

    def test_breach_trigger_highest_salience(self, hipaa_ruleset) -> None:
        breach_rule = next(r for r in hipaa_ruleset.rules if r.name == "breach-trigger")
        assert breach_rule.salience == 200

    def test_all_rules_use_log_full(self, hipaa_ruleset) -> None:
        for rule in hipaa_ruleset.rules:
            assert rule.then.log == LogLevel.FULL, (
                f"Rule '{rule.name}' uses log={rule.then.log}, expected full"
            )

    def test_pack_has_at_least_three_rules(self, hipaa_ruleset) -> None:
        assert len(hipaa_ruleset.rules) >= 3
