"""Tests for the HIPAA Privacy and Security Rule pack.

Covers minimum necessary standard (164.502(b)), transmission security
(164.312(e)(1)), and breach notification trigger (164.402) with
positive and negative cases for each rule.
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
                "ts": time.time(),
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
                "ts": time.time(),
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
                "ts": time.time(),
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
                "ts": time.time(),
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
    """Breach trigger (164.402): escalate on more than 10 PHI reads in 300s.

    The threshold is compiled as a ``rate_exceeds`` condition on the ts
    slot, so a single access must not be reported as a breach event.
    """

    def test_single_access_does_not_trigger_breach(self, hipaa_engine: Engine) -> None:
        """One justified read is not a 164.402 breach-notification event."""
        hipaa_engine.assert_fact(
            "phi_policy",
            {
                "resource": "patient-record",
                "role": "nurse",
                "access_level": "read",
                "justification": "patient care",
                "ts": time.time(),
            },
        )
        result = hipaa_engine.evaluate()
        assert "hipaa::breach-trigger" not in result.rule_trace
        assert "164.402" not in (result.reason or "")

    def test_threshold_reads_do_not_trigger_breach(self, hipaa_engine: Engine) -> None:
        """Exactly the threshold (10 reads) is below the > 10 trigger."""
        for i in range(10):
            hipaa_engine.assert_fact(
                "phi_policy",
                {
                    "resource": f"patient-record-{i}",
                    "role": "analyst",
                    "access_level": "read",
                    "justification": "audit review",
                    "ts": time.time(),
                },
            )
        result = hipaa_engine.evaluate()
        assert "hipaa::breach-trigger" not in result.rule_trace

    def test_bulk_reads_within_window_trigger_breach(self, hipaa_engine: Engine) -> None:
        """More than 10 reads inside the 300s window escalates."""
        for i in range(11):
            hipaa_engine.assert_fact(
                "phi_policy",
                {
                    "resource": f"patient-record-{i}",
                    "role": "analyst",
                    "access_level": "read",
                    "justification": "audit review",
                    "ts": time.time(),
                },
            )
        result = hipaa_engine.evaluate()
        assert "hipaa::breach-trigger" in result.rule_trace
        assert result.decision == "escalate"
        assert "164.402" in (result.reason or "")

    def test_bulk_reads_outside_window_do_not_trigger(self, hipaa_engine: Engine) -> None:
        """Reads older than the 300s window do not count toward the threshold."""
        stale = time.time() - 3600
        for i in range(15):
            hipaa_engine.assert_fact(
                "phi_policy",
                {
                    "resource": f"patient-record-{i}",
                    "role": "analyst",
                    "access_level": "read",
                    "justification": "audit review",
                    "ts": stale,
                },
            )
        result = hipaa_engine.evaluate()
        assert "hipaa::breach-trigger" not in result.rule_trace

    def test_breach_metadata_reaches_the_result(self, hipaa_engine: Engine) -> None:
        """Control metadata is emitted with the decision, not silently dropped."""
        for i in range(11):
            hipaa_engine.assert_fact(
                "phi_policy",
                {
                    "resource": f"patient-record-{i}",
                    "role": "analyst",
                    "access_level": "read",
                    "justification": "audit review",
                    "ts": time.time(),
                },
            )
        result = hipaa_engine.evaluate()
        assert result.metadata["control"] == "164.402"
        assert result.metadata["threshold"] == "10"
        assert result.metadata["window_seconds"] == "300"


# =========================================================================
# Rule metadata validation
# =========================================================================


class TestHIPAARuleMetadata:
    """Verify salience and log-level metadata across HIPAA rules."""

    def test_deny_salience_below_every_escalate(self, hipaa_ruleset) -> None:
        """Severity must be monotone in reverse salience (last write wins)."""
        deny_saliences = [r.salience for r in hipaa_ruleset.rules if r.then.action.value == "deny"]
        escalate_saliences = [
            r.salience for r in hipaa_ruleset.rules if r.then.action.value == "escalate"
        ]
        assert deny_saliences and escalate_saliences
        assert max(deny_saliences) < min(escalate_saliences), (
            f"deny saliences {deny_saliences} must all be below "
            f"escalate saliences {escalate_saliences}"
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
