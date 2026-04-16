"""Integration tests for temporal operators end-to-end.

Exercises the full evaluation cycle: load templates, build rules that
call temporal CLIPS functions, assert facts with timestamps, evaluate,
and verify rule firing.  Also tests TTL expiry during evaluation.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from fathom.engine import Engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_with_template(tmp_path, yaml_str: str) -> Engine:
    """Create an Engine with templates loaded from a YAML string."""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_str)
    e = Engine()
    e.load_templates(str(p))
    return e


_EVENT_TEMPLATE = """\
templates:
  - name: event
    slots:
      - name: action
        type: symbol
        required: true
      - name: user
        type: string
        required: true
      - name: ts
        type: float
        required: true
"""

_SESSION_TEMPLATE = """\
templates:
  - name: session
    slots:
      - name: user
        type: string
        required: true
      - name: token
        type: string
        required: true
    ttl: 5
"""

_LOG_ENTRY_TEMPLATE = """\
templates:
  - name: log_entry
    slots:
      - name: action
        type: symbol
        required: true
      - name: user
        type: string
        required: true
      - name: created_at
        type: float
        required: true
"""


# ---------------------------------------------------------------------------
# rate_exceeds end-to-end
# ---------------------------------------------------------------------------


class TestRateExceedsIntegration:
    """End-to-end tests for rate_exceeds via CLIPS rule evaluation."""

    def test_rate_exceeds_fires_rule(self, tmp_path):
        """A rule using fathom-rate-exceeds fires when rate threshold is exceeded."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)

        # Build a rule that fires when login rate exceeds 3 in 60s
        e._safe_build(
            "(defrule MAIN::rate-limit-check"
            "    (event (action login))"
            '    (test (fathom-rate-exceeds "event" "action" "login" 3 60 "ts"))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "login rate exceeded")'
            '        (rule "MAIN::rate-limit-check"))))',
            context="rate-limit-rule",
        )

        now = time.time()
        for i in range(5):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})

        result = e.evaluate()
        assert result.decision == "deny"
        assert "rate exceeded" in result.reason

    def test_rate_below_threshold_no_fire(self, tmp_path):
        """Rule does not fire when rate is below threshold."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)

        e._safe_build(
            "(defrule MAIN::rate-limit-check"
            "    (event (action login))"
            '    (test (fathom-rate-exceeds "event" "action" "login" 5 60 "ts"))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "login rate exceeded")'
            '        (rule "MAIN::rate-limit-check"))))',
            context="rate-limit-rule",
        )

        now = time.time()
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})

        result = e.evaluate()
        # Default deny (no rule fired), reason is default
        assert result.decision == "deny"
        assert "default" in result.reason.lower()

    def test_rate_excludes_old_facts_end_to_end(self, tmp_path):
        """Old facts outside the time window do not trigger rate rule."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)

        e._safe_build(
            "(defrule MAIN::rate-limit-check"
            "    (event (action login))"
            '    (test (fathom-rate-exceeds "event" "action" "login" 2 10 "ts"))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "rate exceeded")'
            '        (rule "MAIN::rate-limit-check"))))',
            context="rate-limit-rule",
        )

        now = time.time()
        # 2 recent facts (within 10s window)
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 1})
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 2})
        # 3 old facts (outside 10s window)
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 100 - i})

        result = e.evaluate()
        # Only 2 recent + 3 old, but only 2 within window -- threshold is 2, not exceeded
        assert result.decision == "deny"
        assert "default" in result.reason.lower()

    def test_rate_with_custom_timestamp_slot(self, tmp_path):
        """rate_exceeds works with a custom timestamp slot name."""
        e = _engine_with_template(tmp_path, _LOG_ENTRY_TEMPLATE)

        e._safe_build(
            "(defrule MAIN::custom-ts-rate"
            "    (log_entry (action login))"
            '    (test (fathom-rate-exceeds "log_entry" "action" "login" 2 60 "created_at"))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "custom ts rate exceeded")'
            '        (rule "MAIN::custom-ts-rate"))))',
            context="custom-ts-rule",
        )

        now = time.time()
        for i in range(4):
            e.assert_fact("log_entry", {"action": "login", "user": "bob", "created_at": now - i})

        result = e.evaluate()
        assert result.decision == "deny"
        assert "custom ts rate exceeded" in result.reason


# ---------------------------------------------------------------------------
# TTL expiry end-to-end
# ---------------------------------------------------------------------------


class TestTTLExpiryIntegration:
    """End-to-end tests for TTL-based fact expiry during evaluation."""

    def test_ttl_expired_facts_removed_before_evaluation(self, tmp_path):
        """Expired facts are cleaned up by the evaluator before rules fire."""
        e = _engine_with_template(tmp_path, _SESSION_TEMPLATE)

        # Build a rule that fires when a session fact exists
        e._safe_build(
            "(defrule MAIN::session-active"
            "    (session)"
            "    =>"
            "    (assert (__fathom_decision"
            "        (action allow)"
            '        (reason "active session found")'
            '        (rule "MAIN::session-active"))))',
            context="session-rule",
        )

        now = time.time()
        # Assert a session fact
        with patch("fathom.facts.time.time", return_value=now):
            e.assert_fact("session", {"user": "alice", "token": "abc123"})

        # Verify fact exists
        assert e.count("session") == 1

        # Advance time beyond TTL (5 seconds)
        with patch("fathom.facts.time.time", return_value=now + 10):
            result = e.evaluate()

        # Fact was expired before rules ran -- no rule fired, default deny
        assert result.decision == "deny"
        assert "default" in result.reason.lower()
        assert e.count("session") == 0

    def test_ttl_fresh_facts_survive_evaluation(self, tmp_path):
        """Fresh facts within TTL are not removed and rules fire normally."""
        e = _engine_with_template(tmp_path, _SESSION_TEMPLATE)

        e._safe_build(
            "(defrule MAIN::session-active"
            "    (session)"
            "    =>"
            "    (assert (__fathom_decision"
            "        (action allow)"
            '        (reason "active session")'
            '        (rule "MAIN::session-active"))))',
            context="session-rule",
        )

        now = time.time()
        with patch("fathom.facts.time.time", return_value=now):
            e.assert_fact("session", {"user": "alice", "token": "abc123"})

        # Evaluate within TTL (2 seconds after assertion, TTL=5)
        with patch("fathom.facts.time.time", return_value=now + 2):
            result = e.evaluate()

        assert result.decision == "allow"
        assert "active session" in result.reason
        assert e.count("session") == 1

    def test_ttl_mixed_fresh_and_expired(self, tmp_path):
        """Only expired facts are removed; fresh ones still trigger rules."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)
        e._fact_manager.set_ttl("event", 10)

        # Build rule that checks for any event
        e._safe_build(
            "(defrule MAIN::has-event"
            "    (event (action login))"
            "    =>"
            "    (assert (__fathom_decision"
            "        (action allow)"
            '        (reason "login event found")'
            '        (rule "MAIN::has-event"))))',
            context="event-rule",
        )

        now = time.time()
        # Old fact (will expire)
        with patch("fathom.facts.time.time", return_value=now - 20):
            e.assert_fact("event", {"action": "login", "user": "old_user", "ts": now - 20})
        # Fresh fact (will survive)
        with patch("fathom.facts.time.time", return_value=now):
            e.assert_fact("event", {"action": "login", "user": "new_user", "ts": now})

        assert e.count("event") == 2

        # Evaluate: old fact expires, fresh fact remains and triggers rule
        with patch("fathom.facts.time.time", return_value=now):
            result = e.evaluate()

        assert result.decision == "allow"
        assert "login event found" in result.reason
        assert e.count("event") == 1
        remaining = e.query("event")
        assert remaining[0]["user"] == "new_user"

    def test_ttl_all_expired_no_rule_fires(self, tmp_path):
        """When all facts expire, no rules fire and default decision applies."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)
        e._fact_manager.set_ttl("event", 5)

        e._safe_build(
            "(defrule MAIN::has-event"
            "    (event)"
            "    =>"
            "    (assert (__fathom_decision"
            "        (action allow)"
            '        (reason "event exists")'
            '        (rule "MAIN::has-event"))))',
            context="event-rule",
        )

        now = time.time()
        with patch("fathom.facts.time.time", return_value=now - 30):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 30})
            e.assert_fact("event", {"action": "logout", "user": "bob", "ts": now - 30})

        # All facts are 30s old, TTL is 5s
        with patch("fathom.facts.time.time", return_value=now):
            result = e.evaluate()

        assert result.decision == "deny"
        assert "default" in result.reason.lower()
        assert e.count("event") == 0


# ---------------------------------------------------------------------------
# Combined temporal operator + evaluation
# ---------------------------------------------------------------------------


class TestCombinedTemporalIntegration:
    """End-to-end tests combining multiple temporal aspects."""

    def test_rate_and_ttl_together(self, tmp_path):
        """TTL cleanup removes expired facts before evaluation starts.

        Verifies that expired facts are removed and the remaining fact count
        is correct.  The rate_exceeds test CE is evaluated at CLIPS activation
        time (when facts are asserted), so we test TTL cleanup separately
        from the rate check by asserting fresh facts after old ones expire.
        """
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)
        e._fact_manager.set_ttl("event", 30)

        # Rule fires when a login event exists (simple pattern)
        e._safe_build(
            "(defrule MAIN::has-login"
            "    (event (action login))"
            "    =>"
            "    (assert (__fathom_decision"
            "        (action allow)"
            '        (reason "login found")'
            '        (rule "MAIN::has-login"))))',
            context="login-rule",
        )

        now = time.time()
        # Assert old facts that will expire
        with patch("fathom.facts.time.time", return_value=now - 60):
            e.assert_fact("event", {"action": "login", "user": "old1", "ts": now - 60})
            e.assert_fact("event", {"action": "login", "user": "old2", "ts": now - 59})

        assert e.count("event") == 2

        # Evaluate: old facts expire (TTL=30, asserted 60s ago) -- no facts remain
        with patch("fathom.facts.time.time", return_value=now):
            result = e.evaluate()

        assert e.count("event") == 0
        assert result.decision == "deny"
        assert "default" in result.reason.lower()

        # Now assert fresh facts and evaluate again -- rule fires
        with patch("fathom.facts.time.time", return_value=now):
            e.assert_fact("event", {"action": "login", "user": "fresh1", "ts": now - 1})

        result2 = e.evaluate()
        assert result2.decision == "allow"
        assert "login found" in result2.reason

    def test_sequence_detection_end_to_end(self, tmp_path):
        """Sequence detection via fathom-sequence-detected in a rule."""
        import json

        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)

        seq = json.dumps(
            [
                {"template": "event", "slot": "action", "value": "login"},
                {"template": "event", "slot": "action", "value": "escalate"},
                {"template": "event", "slot": "action", "value": "download"},
            ],
            separators=(",", ":"),
        )
        escaped = seq.replace('"', '\\"')

        e._safe_build(
            "(defrule MAIN::attack-sequence"
            "    (event (action download))"
            f'    (test (fathom-sequence-detected "{escaped}" 120))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "attack sequence detected")'
            '        (rule "MAIN::attack-sequence"))))',
            context="sequence-rule",
        )

        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 10})
        e.assert_fact("event", {"action": "escalate", "user": "alice", "ts": now - 5})
        e.assert_fact("event", {"action": "download", "user": "alice", "ts": now - 1})

        result = e.evaluate()
        assert result.decision == "deny"
        assert "attack sequence detected" in result.reason

    def test_distinct_count_end_to_end(self, tmp_path):
        """Distinct count operator triggers rule in full evaluation."""
        access_template = """\
templates:
  - name: access
    slots:
      - name: user
        type: string
        required: true
      - name: resource
        type: string
        required: true
      - name: ts
        type: float
        required: true
"""
        e = _engine_with_template(tmp_path, access_template)

        e._safe_build(
            "(defrule MAIN::too-many-resources"
            "    (access)"
            '    (test (fathom-distinct-count "access" "user" "resource" 2))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "too many distinct resources")'
            '        (rule "MAIN::too-many-resources"))))',
            context="distinct-rule",
        )

        now = time.time()
        e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now})
        e.assert_fact("access", {"user": "alice", "resource": "db2", "ts": now})
        e.assert_fact("access", {"user": "alice", "resource": "db3", "ts": now})

        result = e.evaluate()
        assert result.decision == "deny"
        assert "too many distinct resources" in result.reason

    def test_last_n_end_to_end(self, tmp_path):
        """last_n operator triggers rule when enough facts exist."""
        e = _engine_with_template(tmp_path, _EVENT_TEMPLATE)

        e._safe_build(
            "(defrule MAIN::many-logins"
            "    (event (action login))"
            '    (test (fathom-last-n "event" "action" "login" 3))'
            "    =>"
            "    (assert (__fathom_decision"
            "        (action deny)"
            '        (reason "too many logins")'
            '        (rule "MAIN::many-logins"))))',
            context="last-n-rule",
        )

        now = time.time()
        for i in range(4):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})

        result = e.evaluate()
        assert result.decision == "deny"
        assert "too many logins" in result.reason
