"""Contradiction detection over the fact layer.

The failure mode worth testing is not "does it find a conflict" but the two
either side of it: reporting one conflict twice (every pair matches in both
assignments unless something orders it) and reporting a legitimate change as
a contradiction (two tails for one head are only in conflict if the claims
are close in time). So the counts matter as much as the contents, and the
negative cases carry as much weight as the positive ones.
"""

from __future__ import annotations

import time

import pytest

from fathom.engine import Engine
from fathom.rule_packs.conflict_detection import DEFAULT_WINDOW_SECONDS

LONG_AGO = 10 * DEFAULT_WINDOW_SECONDS


@pytest.fixture
def engine() -> Engine:
    eng = Engine()
    eng.load_pack("conflict-detection")
    return eng


def _claim(engine: Engine, head: str, relation: str, tail: str, age: float = 0.0) -> None:
    engine.assert_fact(
        "claim",
        {"head": head, "relation": relation, "tail": tail, "observed_at": time.time() - age},
    )


def _conflicts(engine: Engine) -> list[dict[str, object]]:
    engine.evaluate()
    return [dict(f) for f in engine._env.facts() if f.template.name == "conflict"]


def _of_kind(engine: Engine, kind: str) -> list[dict[str, object]]:
    return [c for c in _conflicts(engine) if c["kind"] == kind]


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


class TestMutualExclusion:
    def test_declared_pair_on_one_head_conflicts(self, engine: Engine) -> None:
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "alice", "status", "terminated", LONG_AGO)
        assert _of_kind(engine, "mutual_exclusion") == [
            {
                "kind": "mutual_exclusion",
                "head": "alice",
                "relation": "status",
                "tail_a": "active",
                "tail_b": "terminated",
            }
        ]

    def test_it_is_reported_once_not_once_per_ordering(self, engine: Engine) -> None:
        """Both claims match both patterns; the declaration is what orders them."""
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "alice", "status", "terminated", LONG_AGO)
        assert len(_of_kind(engine, "mutual_exclusion")) == 1

    def test_different_heads_do_not_conflict(self, engine: Engine) -> None:
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "bob", "status", "terminated", LONG_AGO)
        assert _of_kind(engine, "mutual_exclusion") == []

    def test_an_undeclared_pair_is_not_a_conflict(self, engine: Engine) -> None:
        """No declaration, no opinion -- a relation may legitimately be multi-valued."""
        _claim(engine, "alice", "speaks", "german", LONG_AGO)
        _claim(engine, "alice", "speaks", "french", LONG_AGO)
        assert _of_kind(engine, "mutual_exclusion") == []

    def test_the_declaration_is_scoped_to_its_relation(self, engine: Engine) -> None:
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "role", "active", LONG_AGO)
        _claim(engine, "alice", "role", "terminated", LONG_AGO)
        assert _of_kind(engine, "mutual_exclusion") == []


# ---------------------------------------------------------------------------
# Temporal
# ---------------------------------------------------------------------------


class TestTemporalConflict:
    def test_two_tails_inside_the_window_conflict(self, engine: Engine) -> None:
        _claim(engine, "carol", "role", "admin")
        _claim(engine, "carol", "role", "viewer", 60)
        assert len(_of_kind(engine, "temporal")) == 1

    def test_two_tails_outside_the_window_are_a_change(self, engine: Engine) -> None:
        """The same pair of claims, far apart, is someone's role being updated."""
        _claim(engine, "dave", "role", "admin")
        _claim(engine, "dave", "role", "viewer", LONG_AGO)
        assert _of_kind(engine, "temporal") == []

    def test_it_is_reported_once_not_once_per_ordering(self, engine: Engine) -> None:
        """Nothing declares an order here, so `str-compare` has to supply one."""
        _claim(engine, "carol", "role", "admin")
        _claim(engine, "carol", "role", "viewer")
        assert len(_of_kind(engine, "temporal")) == 1

    def test_a_claim_does_not_conflict_with_itself(self, engine: Engine) -> None:
        _claim(engine, "erin", "role", "admin")
        assert _of_kind(engine, "temporal") == []

    def test_the_same_tail_twice_is_agreement(self, engine: Engine) -> None:
        _claim(engine, "erin", "role", "admin")
        _claim(engine, "erin", "role", "admin", 60)
        assert _of_kind(engine, "temporal") == []

    def test_a_claim_with_no_timestamp_never_pairs(self, engine: Engine) -> None:
        """`observed_at` defaults to 0, which is 1970 -- old, not now."""
        engine.assert_fact("claim", {"head": "f", "relation": "role", "tail": "admin"})
        engine.assert_fact("claim", {"head": "f", "relation": "role", "tail": "viewer"})
        assert _of_kind(engine, "temporal") == []

    def test_different_relations_do_not_pair(self, engine: Engine) -> None:
        _claim(engine, "carol", "role", "admin")
        _claim(engine, "carol", "status", "viewer")
        assert _of_kind(engine, "temporal") == []


# ---------------------------------------------------------------------------
# Granularity
# ---------------------------------------------------------------------------


class TestGranularityConflict:
    def test_broader_and_narrower_claims_conflict(self, engine: Engine) -> None:
        engine.assert_fact(
            "subsumes", {"relation": "lives_in", "broader": "germany", "narrower": "berlin"}
        )
        _claim(engine, "bob", "lives_in", "germany", LONG_AGO)
        _claim(engine, "bob", "lives_in", "berlin", LONG_AGO)
        assert _of_kind(engine, "granularity") == [
            {
                "kind": "granularity",
                "head": "bob",
                "relation": "lives_in",
                "tail_a": "germany",
                "tail_b": "berlin",
            }
        ]

    def test_it_is_reported_once_not_once_per_ordering(self, engine: Engine) -> None:
        engine.assert_fact(
            "subsumes", {"relation": "lives_in", "broader": "germany", "narrower": "berlin"}
        )
        _claim(engine, "bob", "lives_in", "germany", LONG_AGO)
        _claim(engine, "bob", "lives_in", "berlin", LONG_AGO)
        assert len(_of_kind(engine, "granularity")) == 1

    def test_unrelated_tails_are_not_a_granularity_conflict(self, engine: Engine) -> None:
        engine.assert_fact(
            "subsumes", {"relation": "lives_in", "broader": "germany", "narrower": "berlin"}
        )
        _claim(engine, "bob", "lives_in", "germany", LONG_AGO)
        _claim(engine, "bob", "lives_in", "france", LONG_AGO)
        assert _of_kind(engine, "granularity") == []


# ---------------------------------------------------------------------------
# The pack as a whole
# ---------------------------------------------------------------------------


class TestPack:
    def test_pack_loads_through_the_public_api(self, engine: Engine) -> None:
        assert set(engine.template_registry) == {
            "claim",
            "mutual_exclusion",
            "subsumes",
            "conflict",
        }

    def test_one_pair_can_be_two_conflicts(self, engine: Engine) -> None:
        """Contradictory *and* simultaneous is two findings about one pair.

        Collapsing them would throw away the reason, which is the part a
        resolution step needs.
        """
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active")
        _claim(engine, "alice", "status", "terminated")
        kinds = sorted(c["kind"] for c in _conflicts(engine))
        assert kinds == ["mutual_exclusion", "temporal"]

    def test_detection_renders_no_decision(self, engine: Engine) -> None:
        """What to do about a contradiction is not this pack's call."""
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "alice", "status", "terminated", LONG_AGO)
        result = engine.evaluate()
        assert result.rule_trace == []

    def test_asserting_alone_detects_nothing(self, engine: Engine) -> None:
        """Detection is host-evaluated, never re-entrant inside an assert."""
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "alice", "status", "terminated", LONG_AGO)
        before = [f for f in engine._env.facts() if f.template.name == "conflict"]
        assert before == []

    def test_a_subscribe_listener_sees_no_conflict_mid_assert(self, engine: Engine) -> None:
        """The re-entrancy #146 warns about, pinned so a refactor cannot reintroduce it.

        Listeners fire synchronously inside `assert_fact`, which does not run
        inference. A listener that tried to react to a conflict would never
        see one, which is the point -- detection belongs to `evaluate()`.
        """
        seen: list[str] = []
        engine.subscribe(lambda fact: seen.append(fact.template))
        engine.assert_fact(
            "mutual_exclusion",
            {"relation": "status", "tail_a": "active", "tail_b": "terminated"},
        )
        _claim(engine, "alice", "status", "active", LONG_AGO)
        _claim(engine, "alice", "status", "terminated", LONG_AGO)
        assert "conflict" not in seen
        assert _of_kind(engine, "mutual_exclusion") != []

    def test_default_window_matches_the_shipped_rule(self) -> None:
        from fathom.rule_packs.conflict_detection import get_rules

        rule = next(r for r in get_rules() if r["name"] == "detect-temporal-conflict")
        windows = [
            c["expression"]
            for pattern in rule["when"]
            for c in pattern["conditions"]
            if c.get("expression", "").startswith("changed_within")
        ]
        assert windows == [f"changed_within({DEFAULT_WINDOW_SECONDS})"] * 2
