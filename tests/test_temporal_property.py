"""Hypothesis property-based tests for temporal operators.

Tests invariants of fathom-last-n, fathom-distinct-count, and TTL cleanup
using randomly generated fact counts, boundary timestamps, and edge cases.
"""

from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from fathom.engine import Engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clips_bool(result: object) -> bool:
    """Convert a CLIPS eval result (Symbol TRUE/FALSE) to a Python bool."""
    return str(result) == "TRUE"


# ---------------------------------------------------------------------------
# Template YAML shared across tests
# ---------------------------------------------------------------------------

_TEMPORAL_TEMPLATE_YAML = """\
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
        default: 0.0
"""

_TTL_TEMPLATE_YAML = """\
templates:
  - name: ttl_event
    slots:
      - name: action
        type: symbol
        required: true
      - name: user
        type: string
        required: true
      - name: ts
        type: float
        default: 0.0
    ttl: 2
"""


def _make_engine(yaml_str: str) -> Engine:
    """Create an Engine with the given template YAML loaded."""
    engine = Engine()
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        os.write(fd, yaml_str.encode())
        os.close(fd)
        engine.load_templates(path)
    finally:
        os.unlink(path)
    return engine


# ---------------------------------------------------------------------------
# fathom-last-n invariants
# ---------------------------------------------------------------------------


class TestLastNInvariants:
    """Property-based tests for the fathom-last-n temporal operator."""

    @given(n=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_last_n_returns_true_when_enough_facts(self, n: int) -> None:
        """fathom-last-n(event, action, login, N) is true when >= N matching facts exist."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(n):
            engine.assert_fact("event", {"action": "login", "user": f"u{i}", "ts": float(i)})

        # Call the CLIPS function via the environment
        result = engine._env.eval(f"(fathom-last-n event action login {n})")
        assert _clips_bool(result), f"Expected True with {n} facts, got {result}"

    @given(
        total=st.integers(min_value=2, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=50)
    def test_last_n_k_less_than_total(self, total: int, data: st.DataObject) -> None:
        """fathom-last-n(event, action, login, k) is true when k <= total facts."""
        k = data.draw(st.integers(min_value=1, max_value=total))
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(total):
            engine.assert_fact("event", {"action": "login", "user": f"u{i}", "ts": float(i)})

        result = engine._env.eval(f"(fathom-last-n event action login {k})")
        assert _clips_bool(result), f"Expected True with {total} facts and k={k}"

    @given(
        total=st.integers(min_value=1, max_value=30),
        data=st.data(),
    )
    @settings(max_examples=50)
    def test_last_n_false_when_insufficient(self, total: int, data: st.DataObject) -> None:
        """fathom-last-n returns false when asking for more facts than exist."""
        ask = data.draw(st.integers(min_value=total + 1, max_value=total + 20))
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(total):
            engine.assert_fact("event", {"action": "login", "user": f"u{i}", "ts": float(i)})

        result = engine._env.eval(f"(fathom-last-n event action login {ask})")
        assert not _clips_bool(result), f"Expected False with {total} facts and ask={ask}"

    @given(n=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_last_n_zero_matching_returns_false(self, n: int) -> None:
        """fathom-last-n returns false when no facts match the slot value."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        # Assert facts with a different action
        for i in range(n):
            engine.assert_fact("event", {"action": "logout", "user": f"u{i}", "ts": float(i)})

        result = engine._env.eval(f"(fathom-last-n event action login {n})")
        assert not _clips_bool(result)

    def test_last_n_empty_working_memory(self) -> None:
        """fathom-last-n returns false on empty working memory for any n >= 1."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        result = engine._env.eval("(fathom-last-n event action login 1)")
        assert not _clips_bool(result)


# ---------------------------------------------------------------------------
# fathom-distinct-count invariants
# ---------------------------------------------------------------------------


class TestDistinctCountInvariants:
    """Property-based tests for fathom-distinct-count."""

    @given(n=st.integers(min_value=1, max_value=30))
    @settings(max_examples=50)
    def test_all_same_values_not_exceed_one(self, n: int) -> None:
        """With all identical count_slot values, distinct_count threshold=1 is false."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(n):
            # Same action, same user -- only 1 distinct user per action group
            engine.assert_fact("event", {"action": "login", "user": "alice", "ts": float(i)})

        # threshold=1 asks: any group with > 1 distinct values? No.
        result = engine._env.eval("(fathom-distinct-count event action user 1)")
        assert not _clips_bool(result), (
            f"Expected False: {n} facts with same user should have distinct_count=1, not >1"
        )

    @given(n=st.integers(min_value=2, max_value=30))
    @settings(max_examples=50)
    def test_distinct_values_detected(self, n: int) -> None:
        """With n distinct user values in one group, distinct_count > (n-1) is true."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(n):
            engine.assert_fact("event", {"action": "login", "user": f"user_{i}", "ts": float(i)})

        # n distinct users; threshold = n-1 means "more than n-1 distinct" = true
        result = engine._env.eval(f"(fathom-distinct-count event action user {n - 1})")
        assert _clips_bool(result), f"Expected True with {n} distinct users, threshold={n - 1}"

    @given(n=st.integers(min_value=1, max_value=30))
    @settings(max_examples=50)
    def test_distinct_count_at_threshold_is_false(self, n: int) -> None:
        """distinct_count uses strict > comparison, so exactly n distinct
        at threshold n is false."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        for i in range(n):
            engine.assert_fact("event", {"action": "login", "user": f"user_{i}", "ts": float(i)})

        # threshold = n: asks "more than n distinct?" which is false when exactly n exist
        result = engine._env.eval(f"(fathom-distinct-count event action user {n})")
        assert not _clips_bool(result), (
            f"Expected False with exactly {n} distinct users at threshold {n}"
        )

    def test_distinct_count_empty_working_memory(self) -> None:
        """distinct_count on empty working memory returns false for any threshold."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        result = engine._env.eval("(fathom-distinct-count event action user 0)")
        assert not _clips_bool(result)

    @given(
        n_groups=st.integers(min_value=1, max_value=5),
        n_per_group=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    def test_distinct_count_multiple_groups(self, n_groups: int, n_per_group: int) -> None:
        """Each group has n_per_group distinct users; only exceeds threshold < n_per_group."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        actions = ["read", "write", "delete", "update", "list"]
        for g in range(n_groups):
            action = actions[g % len(actions)]
            for u in range(n_per_group):
                engine.assert_fact(
                    "event",
                    {"action": action, "user": f"user_{g}_{u}", "ts": float(g * 100 + u)},
                )

        # Each group has exactly n_per_group distinct users
        # threshold = n_per_group means "more than n_per_group" -> false
        result = engine._env.eval(f"(fathom-distinct-count event action user {n_per_group})")
        assert not _clips_bool(result)

        if n_per_group > 1:
            # threshold = n_per_group - 1 means "more than n_per_group - 1" -> true
            result = engine._env.eval(
                f"(fathom-distinct-count event action user {n_per_group - 1})"
            )
            assert _clips_bool(result)


# ---------------------------------------------------------------------------
# TTL boundary conditions
# ---------------------------------------------------------------------------


class TestTTLBoundaryConditions:
    """Property-based tests for TTL cleanup edge cases."""

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=50)
    def test_fresh_facts_survive_cleanup(self, n: int) -> None:
        """Facts asserted just now should survive cleanup (TTL=2s)."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)
        for i in range(n):
            engine.assert_fact("ttl_event", {"action": "ping", "user": f"u{i}", "ts": float(i)})

        retracted = engine._fact_manager.cleanup_expired()
        assert retracted == 0, f"Expected 0 retracted, got {retracted}"

        remaining = engine.count("ttl_event")
        assert remaining == n, f"Expected {n} remaining, got {remaining}"

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=50)
    def test_expired_facts_are_cleaned(self, n: int) -> None:
        """Facts with timestamps in the past beyond TTL are retracted."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)

        # Patch time.time so facts appear to have been asserted 10s ago
        past_time = time.time() - 10.0
        with patch("fathom.facts.time.time", return_value=past_time):
            for i in range(n):
                engine.assert_fact(
                    "ttl_event", {"action": "ping", "user": f"u{i}", "ts": float(i)}
                )

        # Now cleanup with real time -- all facts are >10s old, TTL=2s
        retracted = engine._fact_manager.cleanup_expired()
        assert retracted == n, f"Expected {n} retracted, got {retracted}"

        remaining = engine.count("ttl_event")
        assert remaining == 0, f"Expected 0 remaining, got {remaining}"

    @given(n=st.integers(min_value=2, max_value=20))
    @settings(max_examples=50)
    def test_mixed_fresh_and_expired(self, n: int) -> None:
        """Only expired facts are cleaned; fresh ones survive."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)
        half = n // 2
        expired_count = half
        fresh_count = n - half

        # Assert first half as expired (10s ago)
        past_time = time.time() - 10.0
        with patch("fathom.facts.time.time", return_value=past_time):
            for i in range(expired_count):
                engine.assert_fact(
                    "ttl_event", {"action": "ping", "user": f"expired_{i}", "ts": float(i)}
                )

        # Assert second half as fresh (now)
        for i in range(fresh_count):
            engine.assert_fact(
                "ttl_event", {"action": "ping", "user": f"fresh_{i}", "ts": float(100 + i)}
            )

        retracted = engine._fact_manager.cleanup_expired()
        assert retracted == expired_count, f"Expected {expired_count} retracted, got {retracted}"

        remaining = engine.count("ttl_event")
        assert remaining == fresh_count, f"Expected {fresh_count} remaining, got {remaining}"

    def test_ttl_exact_boundary(self) -> None:
        """Facts at exact TTL boundary (ts + ttl < now) are retracted."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)

        # Assert a fact at exactly TTL boundary: ts + ttl == now
        # The condition is `ts + ttl < now`, so at exact boundary it should NOT be retracted
        boundary_time = time.time() - 2.0  # exactly 2s ago, TTL=2s
        with patch("fathom.facts.time.time", return_value=boundary_time):
            engine.assert_fact("ttl_event", {"action": "ping", "user": "boundary", "ts": 0.0})

        # At exact boundary: asserted_at + ttl == now, condition is strict <
        # So fact should NOT be retracted at exact boundary
        now = boundary_time + 2.0
        with patch("fathom.facts.time.time", return_value=now):
            retracted = engine._fact_manager.cleanup_expired()

        # ts + ttl == now => not < now => not retracted
        assert retracted == 0, "Fact at exact TTL boundary should not be retracted (strict <)"

    def test_ttl_just_past_boundary(self) -> None:
        """Facts just past TTL boundary are retracted."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)

        past_time = time.time() - 2.001  # just past 2s TTL
        with patch("fathom.facts.time.time", return_value=past_time):
            engine.assert_fact("ttl_event", {"action": "ping", "user": "past", "ts": 0.0})

        # Now: asserted_at + 2 < now (since asserted 2.001s ago)
        retracted = engine._fact_manager.cleanup_expired()
        assert retracted == 1, "Fact just past TTL boundary should be retracted"

    def test_cleanup_on_empty_returns_zero(self) -> None:
        """cleanup_expired on empty working memory returns 0."""
        engine = _make_engine(_TTL_TEMPLATE_YAML)
        retracted = engine._fact_manager.cleanup_expired()
        assert retracted == 0


# ---------------------------------------------------------------------------
# Edge cases: large windows and boundary values
# ---------------------------------------------------------------------------


class TestTemporalEdgeCases:
    """Edge cases for temporal operators with extreme values."""

    @given(window=st.floats(min_value=1.0, max_value=1e8))
    @settings(max_examples=30)
    def test_large_window_rate_exceeds(self, window: float) -> None:
        """rate_exceeds with large windows still works correctly."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        now = time.time()
        engine.assert_fact("event", {"action": "login", "user": "alice", "ts": now})
        engine.assert_fact("event", {"action": "login", "user": "bob", "ts": now})

        # 2 matching facts, threshold=1, large window => should be true
        result = engine._env.eval(f"(fathom-rate-exceeds event action login 1 {window} ts)")
        assert _clips_bool(result)

    def test_last_n_with_n_equals_one(self) -> None:
        """last_n with n=1 returns true if at least one matching fact exists."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        engine.assert_fact("event", {"action": "login", "user": "alice", "ts": 0.0})
        result = engine._env.eval("(fathom-last-n event action login 1)")
        assert _clips_bool(result)

    @given(n=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_last_n_deduplication_by_clips(self, n: int) -> None:
        """CLIPS deduplicates identical facts; last_n reflects actual count."""
        engine = _make_engine(_TEMPORAL_TEMPLATE_YAML)
        # Assert the same fact n times -- CLIPS deduplicates to 1
        for _ in range(n):
            engine.assert_fact("event", {"action": "login", "user": "alice", "ts": 0.0})

        # Only 1 unique fact exists due to CLIPS deduplication
        result_1 = engine._env.eval("(fathom-last-n event action login 1)")
        assert _clips_bool(result_1)

        result_2 = engine._env.eval("(fathom-last-n event action login 2)")
        assert not _clips_bool(result_2), "CLIPS deduplicates identical facts to 1"
