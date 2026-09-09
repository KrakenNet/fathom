"""Runtime introspection — ``agenda``, ``rule_matches``, ``trace`` (#76, #74).

``rule_trace`` says what fired. These say what is *about* to fire, how far a
rule that did not fire got, and what CLIPS itself saw while firing. Every one
of them reads per-module CLIPS state, so the tests here run them both before
an evaluation and after one: ``env.activations()`` and ``env.find_rule()``
report the current module only, and after a run that is wherever the focus
stack left off.
"""

from __future__ import annotations

import pytest

from fathom.engine import Engine
from fathom.errors import ValidationError

RULES = "examples/01-hello-allow-deny"

AGENT_SECRET = ("agent", {"id": "a1", "clearance": "secret"})
REQ_TOP_SECRET = (
    "data_request",
    {"agent_id": "a1", "classification": "top-secret", "resource": "x"},
)


def loaded() -> Engine:
    """Engine with the example pack and one deny-shaped pair of facts."""
    engine = Engine.from_rules(RULES)
    engine.assert_fact(*AGENT_SECRET)
    engine.assert_fact(*REQ_TOP_SECRET)
    return engine


# ---------------------------------------------------------------------------
# agenda()
# ---------------------------------------------------------------------------


class TestAgenda:
    def test_empty_before_any_facts(self) -> None:
        assert Engine.from_rules(RULES).agenda() == []

    def test_reports_the_rules_that_would_fire(self) -> None:
        waiting = {a.rule for a in loaded().agenda()}
        assert "governance::deny-top-secret-for-secret" in waiting

    def test_carries_module_salience_and_matched_facts(self) -> None:
        deny = next(a for a in loaded().agenda() if a.rule.endswith("deny-top-secret-for-secret"))
        assert deny.module == "governance"
        assert deny.salience == 10
        # Both patterns matched, so the activation names both facts.
        assert len(deny.facts) == 2

    def test_empty_once_everything_has_fired(self) -> None:
        engine = loaded()
        engine.evaluate()
        assert engine.agenda() == []

    def test_visible_after_an_evaluation_left_another_module_current(self) -> None:
        """The per-module trap: a bare env.activations() reads MAIN and sees nothing."""
        engine = loaded()
        engine.evaluate()
        engine.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        assert [a.rule for a in engine.agenda()]


# ---------------------------------------------------------------------------
# rule_matches()
# ---------------------------------------------------------------------------


class TestRuleMatches:
    def test_counts_a_rule_that_is_ready_to_fire(self) -> None:
        counts = loaded().rule_matches("governance::deny-top-secret-for-secret")
        assert counts.activations == 1
        assert counts.matches == 2

    def test_a_rule_one_fact_short_matches_without_activating(self) -> None:
        """One of two patterns satisfied: the diagnostic this exists for."""
        engine = Engine.from_rules(RULES)
        engine.assert_fact(*AGENT_SECRET)
        counts = engine.rule_matches("deny-top-secret-for-secret")
        assert counts.matches == 1
        assert counts.activations == 0

    def test_nothing_matched_at_all(self) -> None:
        counts = Engine.from_rules(RULES).rule_matches("deny-top-secret-for-secret")
        assert (counts.matches, counts.partial_matches, counts.activations) == (0, 0, 0)

    def test_accepts_a_bare_name_after_an_evaluation(self) -> None:
        engine = loaded()
        engine.evaluate()
        assert engine.rule_matches("deny-top-secret-for-secret").rule.startswith("governance::")

    def test_unknown_rule_raises(self) -> None:
        with pytest.raises(ValidationError, match="no loaded module defines a rule"):
            Engine.from_rules(RULES).rule_matches("no-such-rule")


# ---------------------------------------------------------------------------
# trace()
# ---------------------------------------------------------------------------


class TestTrace:
    def test_records_each_firing(self) -> None:
        engine = loaded()
        with engine.trace() as firings:
            result = engine.evaluate()
        assert result.decision == "deny"
        assert any("deny-top-secret-for-secret" in line for line in firings)

    def test_records_nothing_when_nothing_fires(self) -> None:
        engine = Engine.from_rules(RULES)
        with engine.trace() as firings:
            engine.evaluate()
        assert firings == []

    def test_the_router_is_removed_afterwards(self) -> None:
        """A leaked router keeps claiming CLIPS stdout for the engine's life."""
        engine = loaded()
        with engine.trace():
            pass
        assert engine._trace_router is None
        with engine.trace() as second:
            engine.evaluate()
        assert second  # the second block still captures, so the first cleaned up

    def test_nested_trace_is_refused(self) -> None:
        engine = loaded()
        with engine.trace():  # noqa: SIM117 - the nesting is what is under test
            with pytest.raises(RuntimeError, match="already active"), engine.trace():
                pass  # pragma: no cover - the inner trace() raises on entry

    def test_cleans_up_when_the_block_raises(self) -> None:
        engine = loaded()
        with pytest.raises(ZeroDivisionError), engine.trace():
            raise ZeroDivisionError
        assert engine._trace_router is None
