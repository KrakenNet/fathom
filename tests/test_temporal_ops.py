"""Unit tests for temporal operator enhancements and TTL cleanup.

Tests cover:
- fathom_rate_exceeds: rate detection with configurable timestamp slot
- fathom_last_n: check if >= N matching facts exist
- fathom_distinct_count: count distinct slot values per group
- fathom_sequence_detected: ordered event pattern detection
- TTL cleanup: expired fact retraction via FactManager
- Edge cases: empty working memory, single fact, zero window
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from fathom.engine import Engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clips_bool(result: object) -> bool:
    """Convert a CLIPS Symbol boolean result to a Python bool."""
    return str(result) == "TRUE"


def _clips_json_str(obj: object) -> str:
    """Encode a Python object as a CLIPS-escaped JSON string literal.

    CLIPS strings use double-quotes; internal double-quotes must be
    backslash-escaped so the entire JSON blob can be passed as a
    single CLIPS string argument.
    """
    raw = json.dumps(obj, separators=(",", ":"))
    return raw.replace('"', '\\"')


_TEMPORAL_TEMPLATE = """\
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

_CUSTOM_TS_TEMPLATE = """\
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

_TTL_TEMPLATE = """\
templates:
  - name: session
    slots:
      - name: user
        type: string
        required: true
      - name: token
        type: string
        required: true
    ttl: 60
"""

_MULTI_SLOT_TEMPLATE = """\
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


def _engine_with_template(tmp_path, yaml_str: str) -> Engine:
    """Create an Engine with templates from a YAML string."""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_str)
    e = Engine()
    e.load_templates(str(p))
    return e


# ---------------------------------------------------------------------------
# rate_exceeds tests
# ---------------------------------------------------------------------------


class TestRateExceeds:
    """Tests for fathom-rate-exceeds temporal operator."""

    def test_rate_below_threshold(self, tmp_path):
        """Rate below threshold returns False."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        # Assert 2 facts — threshold is 3
        for i in range(2):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 3 60 "ts")')
        assert _clips_bool(result) is False

    def test_rate_exceeds_threshold(self, tmp_path):
        """Rate above threshold returns True."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(5):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 3 60 "ts")')
        assert _clips_bool(result) is True

    def test_rate_excludes_old_facts(self, tmp_path):
        """Facts outside the time window are not counted."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        # 2 recent + 3 old (outside 10-second window)
        for i in range(2):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 100 - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 3 10 "ts")')
        assert _clips_bool(result) is False

    def test_rate_with_custom_timestamp_slot(self, tmp_path):
        """Rate detection with a non-default timestamp slot."""
        e = _engine_with_template(tmp_path, _CUSTOM_TS_TEMPLATE)
        now = time.time()
        for i in range(4):
            e.assert_fact("log_entry", {"action": "login", "user": "bob", "created_at": now - i})
        result = e._env.eval(
            '(fathom-rate-exceeds "log_entry" "action" "login" 3 60 "created_at")'
        )
        assert _clips_bool(result) is True

    def test_rate_exact_threshold_not_exceeded(self, tmp_path):
        """Exactly at threshold (not exceeding) returns False."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 3 60 "ts")')
        assert _clips_bool(result) is False

    def test_rate_zero_window(self, tmp_path):
        """Zero window means no facts can be within range."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(5):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 0 0 "ts")')
        # window=0 means (current - ts) < 0 is always False
        assert _clips_bool(result) is False

    def test_rate_empty_working_memory(self, tmp_path):
        """No facts means rate is zero."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 0 60 "ts")')
        assert _clips_bool(result) is False

    def test_rate_filters_by_slot_value(self, tmp_path):
        """Only facts matching the slot value are counted."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        for i in range(3):
            e.assert_fact("event", {"action": "logout", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-rate-exceeds "event" "action" "login" 3 60 "ts")')
        # 3 login facts — threshold is 3, so not exceeded (need > 3)
        assert _clips_bool(result) is False


# ---------------------------------------------------------------------------
# last_n tests
# ---------------------------------------------------------------------------


class TestLastN:
    """Tests for fathom-last-n temporal operator."""

    def test_last_n_sufficient_facts(self, tmp_path):
        """Returns True when >= N matching facts exist."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(5):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-last-n "event" "action" "login" 3)')
        assert _clips_bool(result) is True

    def test_last_n_insufficient_facts(self, tmp_path):
        """Returns False when < N matching facts exist."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(2):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-last-n "event" "action" "login" 3)')
        assert _clips_bool(result) is False

    def test_last_n_exact_count(self, tmp_path):
        """Returns True when exactly N matching facts exist."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        for i in range(3):
            e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - i})
        result = e._env.eval('(fathom-last-n "event" "action" "login" 3)')
        assert _clips_bool(result) is True

    def test_last_n_empty_memory(self, tmp_path):
        """Returns False when no facts exist."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        result = e._env.eval('(fathom-last-n "event" "action" "login" 1)')
        assert _clips_bool(result) is False

    def test_last_n_filters_by_value(self, tmp_path):
        """Only counts facts matching the specified slot value."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        e.assert_fact("event", {"action": "logout", "user": "alice", "ts": now - 1})
        e.assert_fact("event", {"action": "login", "user": "bob", "ts": now - 2})
        result = e._env.eval('(fathom-last-n "event" "action" "login" 2)')
        assert _clips_bool(result) is True
        result2 = e._env.eval('(fathom-last-n "event" "action" "login" 3)')
        assert _clips_bool(result2) is False


# ---------------------------------------------------------------------------
# distinct_count tests
# ---------------------------------------------------------------------------


class TestDistinctCount:
    """Tests for fathom-distinct-count temporal operator."""

    def test_distinct_exceeds_threshold(self, tmp_path):
        """Returns True when distinct count exceeds threshold."""
        e = _engine_with_template(tmp_path, _MULTI_SLOT_TEMPLATE)
        now = time.time()
        e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now})
        e.assert_fact("access", {"user": "alice", "resource": "db2", "ts": now})
        e.assert_fact("access", {"user": "alice", "resource": "db3", "ts": now})
        # alice accessed 3 distinct resources — threshold is 2
        result = e._env.eval('(fathom-distinct-count "access" "user" "resource" 2)')
        assert _clips_bool(result) is True

    def test_distinct_below_threshold(self, tmp_path):
        """Returns False when distinct count does not exceed threshold."""
        e = _engine_with_template(tmp_path, _MULTI_SLOT_TEMPLATE)
        now = time.time()
        e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now})
        e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now + 1})
        # alice accessed 1 distinct resource — threshold is 2
        result = e._env.eval('(fathom-distinct-count "access" "user" "resource" 2)')
        assert _clips_bool(result) is False

    def test_distinct_empty_memory(self, tmp_path):
        """Returns False when no facts exist."""
        e = _engine_with_template(tmp_path, _MULTI_SLOT_TEMPLATE)
        result = e._env.eval('(fathom-distinct-count "access" "user" "resource" 0)')
        assert _clips_bool(result) is False

    def test_distinct_multiple_groups(self, tmp_path):
        """Returns True when any group exceeds threshold."""
        e = _engine_with_template(tmp_path, _MULTI_SLOT_TEMPLATE)
        now = time.time()
        # alice: 1 resource, bob: 3 resources
        e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now})
        e.assert_fact("access", {"user": "bob", "resource": "db1", "ts": now})
        e.assert_fact("access", {"user": "bob", "resource": "db2", "ts": now})
        e.assert_fact("access", {"user": "bob", "resource": "db3", "ts": now})
        result = e._env.eval('(fathom-distinct-count "access" "user" "resource" 2)')
        assert _clips_bool(result) is True

    def test_distinct_duplicates_not_counted(self, tmp_path):
        """Duplicate values within a group are counted once."""
        e = _engine_with_template(tmp_path, _MULTI_SLOT_TEMPLATE)
        now = time.time()
        for i in range(5):
            e.assert_fact("access", {"user": "alice", "resource": "db1", "ts": now + i})
        # 5 facts but only 1 distinct resource
        result = e._env.eval('(fathom-distinct-count "access" "user" "resource" 1)')
        assert _clips_bool(result) is False


# ---------------------------------------------------------------------------
# sequence_detected tests
# ---------------------------------------------------------------------------


class TestSequenceDetected:
    """Tests for fathom-sequence-detected temporal operator."""

    def test_sequence_in_order(self, tmp_path):
        """Returns True when events appear in correct temporal order."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 3})
        e.assert_fact("event", {"action": "escalate", "user": "alice", "ts": now - 2})
        e.assert_fact("event", {"action": "download", "user": "alice", "ts": now - 1})
        escaped = _clips_json_str(
            [
                {"template": "event", "slot": "action", "value": "login"},
                {"template": "event", "slot": "action", "value": "escalate"},
                {"template": "event", "slot": "action", "value": "download"},
            ]
        )
        result = e._env.eval(f'(fathom-sequence-detected "{escaped}" 60)')
        assert _clips_bool(result) is True

    def test_sequence_out_of_order(self, tmp_path):
        """Returns False when events are not in temporal order."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        # download before escalate
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 3})
        e.assert_fact("event", {"action": "download", "user": "alice", "ts": now - 2})
        e.assert_fact("event", {"action": "escalate", "user": "alice", "ts": now - 1})
        escaped = _clips_json_str(
            [
                {"template": "event", "slot": "action", "value": "login"},
                {"template": "event", "slot": "action", "value": "escalate"},
                {"template": "event", "slot": "action", "value": "download"},
            ]
        )
        result = e._env.eval(f'(fathom-sequence-detected "{escaped}" 60)')
        assert _clips_bool(result) is False

    def test_sequence_missing_event(self, tmp_path):
        """Returns False when one event in the sequence is missing."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 2})
        # "escalate" never asserted
        e.assert_fact("event", {"action": "download", "user": "alice", "ts": now - 1})
        escaped = _clips_json_str(
            [
                {"template": "event", "slot": "action", "value": "login"},
                {"template": "event", "slot": "action", "value": "escalate"},
                {"template": "event", "slot": "action", "value": "download"},
            ]
        )
        result = e._env.eval(f'(fathom-sequence-detected "{escaped}" 60)')
        assert _clips_bool(result) is False

    def test_sequence_outside_window(self, tmp_path):
        """Returns False when sequence spans beyond the time window."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now - 120})
        e.assert_fact("event", {"action": "escalate", "user": "alice", "ts": now - 60})
        e.assert_fact("event", {"action": "download", "user": "alice", "ts": now - 1})
        escaped = _clips_json_str(
            [
                {"template": "event", "slot": "action", "value": "login"},
                {"template": "event", "slot": "action", "value": "escalate"},
                {"template": "event", "slot": "action", "value": "download"},
            ]
        )
        # window=10 seconds, but first event is 120s ago
        result = e._env.eval(f'(fathom-sequence-detected "{escaped}" 10)')
        assert _clips_bool(result) is False

    def test_sequence_empty_memory(self, tmp_path):
        """Returns False when no facts exist."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        escaped = _clips_json_str(
            [
                {"template": "event", "slot": "action", "value": "login"},
            ]
        )
        result = e._env.eval(f'(fathom-sequence-detected "{escaped}" 60)')
        assert _clips_bool(result) is False


# ---------------------------------------------------------------------------
# TTL cleanup tests
# ---------------------------------------------------------------------------


class TestTTLCleanup:
    """Tests for TTL-based fact expiration via FactManager."""

    def test_ttl_from_template_definition(self, tmp_path):
        """TTL defined in template YAML is picked up by FactManager."""
        e = _engine_with_template(tmp_path, _TTL_TEMPLATE)
        assert "session" in e._fact_manager._ttl_config
        assert e._fact_manager._ttl_config["session"] == 60

    def test_ttl_cleanup_removes_expired(self, tmp_path):
        """Expired facts are retracted by cleanup_expired."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        e._fact_manager.set_ttl("event", 10)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        # Simulate time passing beyond TTL
        with patch("fathom.facts.time.time", return_value=now + 20):
            retracted = e._fact_manager.cleanup_expired()
        assert retracted == 1
        assert e.count("event") == 0

    def test_ttl_cleanup_keeps_fresh_facts(self, tmp_path):
        """Fresh facts within TTL are not retracted."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        e._fact_manager.set_ttl("event", 60)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        # Time advances by 10s, TTL is 60s — fact should remain
        with patch("fathom.facts.time.time", return_value=now + 10):
            retracted = e._fact_manager.cleanup_expired()
        assert retracted == 0
        assert e.count("event") == 1

    def test_ttl_cleanup_mixed_expired_and_fresh(self, tmp_path):
        """Only expired facts are retracted; fresh ones remain."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        e._fact_manager.set_ttl("event", 30)
        now = time.time()

        # Mock time.time for assert_fact to control timestamps
        with patch("fathom.facts.time.time", return_value=now - 60):
            e.assert_fact("event", {"action": "login", "user": "old", "ts": now - 60})
        with patch("fathom.facts.time.time", return_value=now):
            e.assert_fact("event", {"action": "login", "user": "new", "ts": now})

        # Now cleanup — old fact (asserted 60s ago, TTL=30) should expire
        with patch("fathom.facts.time.time", return_value=now):
            retracted = e._fact_manager.cleanup_expired()
        assert retracted == 1
        remaining = e.query("event")
        assert len(remaining) == 1
        assert remaining[0]["user"] == "new"

    def test_ttl_cleanup_no_ttl_configured(self, tmp_path):
        """Templates without TTL are not affected by cleanup."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        retracted = e._fact_manager.cleanup_expired()
        assert retracted == 0
        assert e.count("event") == 1

    def test_ttl_set_programmatically(self, tmp_path):
        """set_ttl can configure TTL after template loading."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        e._fact_manager.set_ttl("event", 5)
        now = time.time()
        e.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        with patch("fathom.facts.time.time", return_value=now + 10):
            retracted = e._fact_manager.cleanup_expired()
        assert retracted == 1

    def test_ttl_cleanup_returns_count(self, tmp_path):
        """cleanup_expired returns accurate count of retracted facts."""
        e = _engine_with_template(tmp_path, _TEMPORAL_TEMPLATE)
        e._fact_manager.set_ttl("event", 5)
        now = time.time()
        for i in range(4):
            e.assert_fact("event", {"action": "login", "user": f"user{i}", "ts": now})
        with patch("fathom.facts.time.time", return_value=now + 10):
            retracted = e._fact_manager.cleanup_expired()
        assert retracted == 4
