"""Working memory tests for Engine — query, count, retract, persistence, reset, clear_facts."""

from __future__ import annotations

import pytest

from fathom.engine import Engine
from fathom.errors import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_with_templates(tmp_path):
    """Engine with agent and data_request templates loaded."""
    yaml_content = """templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
  - name: data_request
    slots:
      - name: agent_id
        type: string
        required: true
      - name: classification
        type: symbol
        required: true
      - name: resource
        type: string
        default: ""
"""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_content)
    e = Engine()
    e.load_templates(str(p))
    return e


@pytest.fixture
def engine_with_single_template(tmp_path):
    """Engine with just the agent template loaded."""
    yaml_content = """templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
"""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_content)
    e = Engine()
    e.load_templates(str(p))
    return e


@pytest.fixture
def engine_three_templates(tmp_path):
    """Engine with agent, data_request, and event templates."""
    yaml_content = """templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
  - name: data_request
    slots:
      - name: agent_id
        type: string
        required: true
      - name: classification
        type: symbol
        required: true
      - name: resource
        type: string
        default: ""
  - name: event
    slots:
      - name: name
        type: string
        required: true
      - name: severity
        type: integer
        default: 0
"""
    p = tmp_path / "templates.yaml"
    p.write_text(yaml_content)
    e = Engine()
    e.load_templates(str(p))
    return e


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestQueryNoFilter:
    """Query all facts of a template (no filter)."""

    def test_query_returns_all_facts(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = e.query("agent")
        assert len(results) == 2

    def test_query_returns_correct_data(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        results = e.query("agent")
        assert results[0]["id"] == "a1"
        assert results[0]["clearance"] == "secret"

    def test_query_empty_template(self, engine_with_templates):
        results = engine_with_templates.query("agent")
        assert results == []

    def test_query_returns_list_of_dicts(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        results = e.query("agent")
        assert isinstance(results, list)
        assert isinstance(results[0], dict)

    def test_query_one_template_ignores_other(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        agent_results = e.query("agent")
        assert len(agent_results) == 1
        assert agent_results[0]["id"] == "a1"


class TestQueryWithFilter:
    """Query with single-slot and multi-slot filters."""

    def test_single_slot_filter(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = e.query("agent", {"clearance": "secret"})
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    def test_multi_slot_filter(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        results = e.query("agent", {"id": "a1", "clearance": "secret"})
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    def test_filter_no_match(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        results = e.query("agent", {"clearance": "top-secret"})
        assert results == []

    def test_filter_matches_all(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        results = e.query("agent", {"clearance": "secret"})
        assert len(results) == 2

    @pytest.mark.parametrize(
        "filter_slot,filter_value,expected_count",
        [
            ("id", "a1", 1),
            ("id", "a2", 1),
            ("id", "a4", 0),
            ("clearance", "secret", 2),
            ("clearance", "top-secret", 1),
            ("clearance", "unclassified", 0),
        ],
    )
    def test_parametrized_filters(
        self,
        engine_with_templates,
        filter_slot,
        filter_value,
        expected_count,
    ):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a3", "clearance": "top-secret"})
        results = e.query("agent", {filter_slot: filter_value})
        assert len(results) == expected_count


class TestQueryAfterMultipleAsserts:
    """Query after asserting multiple facts."""

    def test_query_after_bulk_assert(self, engine_with_templates):
        e = engine_with_templates
        e.assert_facts(
            [
                ("agent", {"id": "a1", "clearance": "secret"}),
                ("agent", {"id": "a2", "clearance": "top-secret"}),
                ("agent", {"id": "a3", "clearance": "secret"}),
            ]
        )
        results = e.query("agent")
        assert len(results) == 3

    def test_query_filter_after_bulk_assert(self, engine_with_templates):
        e = engine_with_templates
        e.assert_facts(
            [
                ("agent", {"id": "a1", "clearance": "secret"}),
                ("agent", {"id": "a2", "clearance": "top-secret"}),
            ]
        )
        results = e.query("agent", {"clearance": "secret"})
        assert len(results) == 1
        assert results[0]["id"] == "a1"


class TestQueryErrors:
    """Query error cases."""

    def test_query_unknown_template_raises(self, engine_with_templates):
        with pytest.raises(ValidationError, match="Unknown template"):
            engine_with_templates.query("nonexistent")

    def test_query_unknown_template_error_has_template(self, engine_with_templates):
        with pytest.raises(ValidationError) as exc_info:
            engine_with_templates.query("nonexistent")
        assert exc_info.value.template == "nonexistent"


class TestQueryDoesNotTriggerEvaluation:
    """Query should not trigger CLIPS evaluation."""

    def test_query_does_not_fire_rules(self, tmp_path):
        """Query should not cause rules to fire (no side effects)."""
        tmpl_yaml = """templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
"""
        modules_yaml = """modules:
  - name: test_mod
focus_order:
  - test_mod
"""
        rules_yaml = """ruleset: test
module: test_mod
rules:
  - name: always-deny
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "equals(secret)"
    then:
      action: deny
      reason: "always deny"
"""
        tp = tmp_path / "templates.yaml"
        tp.write_text(tmpl_yaml)
        mp = tmp_path / "modules.yaml"
        mp.write_text(modules_yaml)
        rp = tmp_path / "rules.yaml"
        rp.write_text(rules_yaml)

        e = Engine()
        e.load_templates(str(tp))
        e.load_modules(str(mp))
        e.load_rules(str(rp))
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})

        # Query should not trigger evaluation
        _results = e.query("agent")

        # Now evaluate -- if query had triggered rules, decision facts
        # would have been cleaned up and we'd get default.
        result = e.evaluate()
        assert result.decision == "deny"
        assert result.reason == "always deny"


# ---------------------------------------------------------------------------
# Count tests
# ---------------------------------------------------------------------------


class TestCount:
    """Count facts with and without filters."""

    def test_count_all(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert e.count("agent") == 2

    def test_count_with_filter(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert e.count("agent", {"clearance": "secret"}) == 1

    def test_count_zero_when_empty(self, engine_with_templates):
        assert engine_with_templates.count("agent") == 0

    def test_count_zero_with_no_match_filter(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert e.count("agent", {"clearance": "top-secret"}) == 0

    @pytest.mark.parametrize("num_facts", [1, 2, 3, 5, 10])
    def test_count_n_facts(self, engine_with_templates, num_facts):
        e = engine_with_templates
        for i in range(num_facts):
            e.assert_fact("agent", {"id": f"a{i}", "clearance": "secret"})
        assert e.count("agent") == num_facts

    def test_count_unknown_template_raises(self, engine_with_templates):
        with pytest.raises(ValidationError, match="Unknown template"):
            engine_with_templates.count("nonexistent")

    def test_count_across_templates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        assert e.count("agent") == 1
        assert e.count("data_request") == 1


# ---------------------------------------------------------------------------
# Retract tests
# ---------------------------------------------------------------------------


class TestRetractWithFilter:
    """Retract with filter removes matching facts only."""

    def test_retract_matching_only(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        retracted = e.retract("agent", {"clearance": "secret"})
        assert retracted == 1
        assert e.count("agent") == 1
        remaining = e.query("agent")
        assert remaining[0]["id"] == "a2"

    def test_retract_multiple_matching(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a3", "clearance": "top-secret"})
        retracted = e.retract("agent", {"clearance": "secret"})
        assert retracted == 2
        assert e.count("agent") == 1

    def test_retract_no_match_returns_zero(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        retracted = e.retract("agent", {"clearance": "top-secret"})
        assert retracted == 0
        assert e.count("agent") == 1

    @pytest.mark.parametrize(
        "filter_val,expected_retracted,expected_remaining",
        [
            ("secret", 2, 1),
            ("top-secret", 1, 2),
            ("unclassified", 0, 3),
        ],
    )
    def test_retract_parametrized_filters(
        self,
        engine_with_templates,
        filter_val,
        expected_retracted,
        expected_remaining,
    ):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a3", "clearance": "top-secret"})
        retracted = e.retract("agent", {"clearance": filter_val})
        assert retracted == expected_retracted
        assert e.count("agent") == expected_remaining


class TestRetractWithoutFilter:
    """Retract without filter removes all facts of template."""

    def test_retract_all(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        retracted = e.retract("agent")
        assert retracted == 2
        assert e.count("agent") == 0

    def test_retract_all_preserves_other_template(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        e.retract("agent")
        assert e.count("agent") == 0
        assert e.count("data_request") == 1

    def test_retract_from_empty_returns_zero(self, engine_with_templates):
        retracted = engine_with_templates.retract("agent")
        assert retracted == 0


class TestRetractReturnCount:
    """Retract returns correct count."""

    @pytest.mark.parametrize("num_facts", [0, 1, 2, 3, 5])
    def test_retract_returns_count(self, engine_with_templates, num_facts):
        e = engine_with_templates
        for i in range(num_facts):
            e.assert_fact("agent", {"id": f"a{i}", "clearance": "secret"})
        retracted = e.retract("agent")
        assert retracted == num_facts


# ---------------------------------------------------------------------------
# CLIPS deduplication tests
# ---------------------------------------------------------------------------


class TestDeduplication:
    """CLIPS deduplicates identical facts."""

    def test_duplicate_assert_produces_one_fact(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert e.count("agent") == 1

    def test_different_facts_not_deduplicated(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "secret"})
        assert e.count("agent") == 2


# ---------------------------------------------------------------------------
# Persistence across evaluate() tests
# ---------------------------------------------------------------------------


class TestPersistenceAcrossEvaluate:
    """Working memory persists across evaluate() calls."""

    def test_facts_survive_evaluate(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.evaluate()
        results = e.query("agent")
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    def test_facts_survive_multiple_evaluates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.evaluate()
        e.evaluate()
        e.evaluate()
        results = e.query("agent")
        assert len(results) == 1
        assert results[0]["id"] == "a1"

    def test_count_stable_across_evaluates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert e.count("agent") == 2
        e.evaluate()
        assert e.count("agent") == 2
        e.evaluate()
        assert e.count("agent") == 2

    def test_assert_after_evaluate(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.evaluate()
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert e.count("agent") == 2

    def test_retract_after_evaluate(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        e.evaluate()
        retracted = e.retract("agent", {"id": "a1"})
        assert retracted == 1
        assert e.count("agent") == 1


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------


class TestReset:
    """reset() clears all facts."""

    def test_reset_clears_facts(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert e.count("agent") == 1
        e.reset()
        assert e.count("agent") == 0

    def test_reset_count_returns_zero(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        e.reset()
        assert e.count("agent") == 0

    def test_reset_clears_multiple_templates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        e.reset()
        assert e.count("agent") == 0
        assert e.count("data_request") == 0

    def test_can_assert_after_reset(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.reset()
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = e.query("agent")
        assert len(results) == 1
        assert results[0]["id"] == "a2"

    def test_templates_survive_reset(self, engine_with_templates):
        """Templates (deftemplates) persist through reset."""
        e = engine_with_templates
        e.reset()
        # Should not raise -- template still registered
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert e.count("agent") == 1

    def test_double_reset(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.reset()
        e.reset()
        assert e.count("agent") == 0
        # Still functional
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert e.count("agent") == 1


# ---------------------------------------------------------------------------
# Clear_facts tests
# ---------------------------------------------------------------------------


class TestClearFacts:
    """clear_facts() removes user facts, preserves templates."""

    def test_clear_facts_removes_user_facts(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        e.clear_facts()
        assert e.count("agent") == 0

    def test_clear_facts_preserves_templates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.clear_facts()
        # Can still assert after clear -- templates survive
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        assert e.count("agent") == 1

    def test_clear_facts_multiple_templates(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        e.clear_facts()
        assert e.count("agent") == 0
        assert e.count("data_request") == 0

    def test_clear_facts_on_empty(self, engine_with_templates):
        """clear_facts on empty working memory is a no-op."""
        e = engine_with_templates
        e.clear_facts()  # Should not raise
        assert e.count("agent") == 0

    def test_clear_facts_then_assert_and_query(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.clear_facts()
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        results = e.query("agent")
        assert len(results) == 1
        assert results[0]["id"] == "a2"

    def test_clear_facts_three_templates(self, engine_three_templates):
        e = engine_three_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        e.assert_fact("event", {"name": "login"})
        e.clear_facts()
        assert e.count("agent") == 0
        assert e.count("data_request") == 0
        assert e.count("event") == 0

    def test_clear_facts_all_templates_still_usable(self, engine_three_templates):
        e = engine_three_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        e.clear_facts()
        # All three templates should still be usable
        e.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        e.assert_fact("data_request", {"agent_id": "a2", "classification": "secret"})
        e.assert_fact("event", {"name": "access"})
        assert e.count("agent") == 1
        assert e.count("data_request") == 1
        assert e.count("event") == 1


# ---------------------------------------------------------------------------
# Symbol conversion tests
# ---------------------------------------------------------------------------


class TestSymbolConversion:
    """Symbol-typed slots should be returned as plain Python str."""

    def test_symbol_returned_as_str(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        results = e.query("agent")
        assert isinstance(results[0]["clearance"], str)
        assert results[0]["clearance"] == "secret"

    @pytest.mark.parametrize(
        "clearance_value",
        ["secret", "top-secret", "unclassified", "confidential"],
    )
    def test_various_symbols(self, engine_with_templates, clearance_value):
        e = engine_with_templates
        e.assert_fact("agent", {"id": "a1", "clearance": clearance_value})
        results = e.query("agent")
        assert results[0]["clearance"] == clearance_value
        assert isinstance(results[0]["clearance"], str)


# ---------------------------------------------------------------------------
# Default value tests
# ---------------------------------------------------------------------------


class TestDefaultValues:
    """Default slot values are applied correctly."""

    def test_default_value_applied(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact("data_request", {"agent_id": "a1", "classification": "public"})
        results = e.query("data_request")
        assert results[0]["resource"] == ""

    def test_explicit_value_overrides_default(self, engine_with_templates):
        e = engine_with_templates
        e.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "public", "resource": "/api/data"},
        )
        results = e.query("data_request")
        assert results[0]["resource"] == "/api/data"


# ---------------------------------------------------------------------------
# Parametrized combined scenarios
# ---------------------------------------------------------------------------


class TestCombinedScenarios:
    """Combined assert/query/retract/count scenarios."""

    @pytest.mark.parametrize(
        "actions,expected_final_count",
        [
            # (action_list, expected count at end)
            ([("assert", "a1"), ("assert", "a2")], 2),
            ([("assert", "a1"), ("assert", "a2"), ("retract", "a1")], 1),
            ([("assert", "a1"), ("assert", "a2"), ("retract_all", None)], 0),
            ([("assert", "a1"), ("retract", "a1"), ("assert", "a2")], 1),
            ([("assert", "a1"), ("assert", "a1")], 1),  # dedup
        ],
        ids=[
            "two-asserts",
            "assert-assert-retract-one",
            "assert-assert-retract-all",
            "assert-retract-assert",
            "dedup-same-fact",
        ],
    )
    def test_action_sequences(self, engine_with_single_template, actions, expected_final_count):
        e = engine_with_single_template
        for action, agent_id in actions:
            if action == "assert":
                e.assert_fact("agent", {"id": agent_id, "clearance": "secret"})
            elif action == "retract":
                e.retract("agent", {"id": agent_id})
            elif action == "retract_all":
                e.retract("agent")
        assert e.count("agent") == expected_final_count

    @pytest.mark.parametrize(
        "num_agents",
        [1, 5, 10, 20],
    )
    def test_scale_assert_query_count(self, engine_with_single_template, num_agents):
        e = engine_with_single_template
        for i in range(num_agents):
            e.assert_fact("agent", {"id": f"a{i}", "clearance": "secret"})
        assert e.count("agent") == num_agents
        results = e.query("agent")
        assert len(results) == num_agents
