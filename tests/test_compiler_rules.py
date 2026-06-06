"""Unit tests for rule compilation and YAML rule parsing in Compiler."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from fathom.compiler import Compiler
from fathom.errors import CompilationError
from fathom.models import (
    ActionType,
    AssertSpec,
    ConditionEntry,
    FactPattern,
    LogLevel,
    RuleDefinition,
    ThenBlock,
)
from tests.conftest import normalize_clips

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    name: str = "test-rule",
    salience: int = 0,
    when: list[FactPattern] | None = None,
    then: ThenBlock | None = None,
) -> RuleDefinition:
    """Build a RuleDefinition with sensible defaults."""
    if when is None:
        when = [
            FactPattern(
                template="agent",
                conditions=[ConditionEntry(slot="clearance", expression="equals(secret)")],
            )
        ]
    if then is None:
        then = ThenBlock(action=ActionType.DENY, reason="test reason")
    return RuleDefinition(name=name, salience=salience, when=when, then=then)


# ---------------------------------------------------------------------------
# TestCompileCondition -- comparison operators
# ---------------------------------------------------------------------------


class TestCompileConditionComparison:
    """Test _compile_condition for each comparison operator."""

    @pytest.mark.parametrize(
        "op,arg,expected",
        [
            ("equals", "secret", "(clearance secret)"),
            ("equals", "top-secret", "(clearance top-secret)"),
            ("equals", "public", "(clearance public)"),
        ],
        ids=["equals-secret", "equals-top-secret", "equals-public"],
    )
    def test_equals(self, compiler: Compiler, op: str, arg: str, expected: str) -> None:
        result = compiler._compile_condition("clearance", f"{op}({arg})", {}, None)
        assert result == expected

    @pytest.mark.parametrize(
        "op,arg,expected",
        [
            ("not_equals", "public", "(clearance ?s_clearance&:(neq ?s_clearance public))"),
            ("not_equals", "secret", "(clearance ?s_clearance&:(neq ?s_clearance secret))"),
        ],
        ids=["neq-public", "neq-secret"],
    )
    def test_not_equals(self, compiler: Compiler, op: str, arg: str, expected: str) -> None:
        result = compiler._compile_condition("clearance", f"{op}({arg})", {}, None)
        assert result == expected

    @pytest.mark.parametrize(
        "op,arg,expected",
        [
            ("greater_than", "5", "(level ?s_level&:(> ?s_level 5))"),
            ("greater_than", "100", "(level ?s_level&:(> ?s_level 100))"),
            ("greater_than", "0", "(level ?s_level&:(> ?s_level 0))"),
        ],
        ids=["gt-5", "gt-100", "gt-0"],
    )
    def test_greater_than(self, compiler: Compiler, op: str, arg: str, expected: str) -> None:
        result = compiler._compile_condition("level", f"{op}({arg})", {}, None)
        assert result == expected

    @pytest.mark.parametrize(
        "op,arg,expected",
        [
            ("less_than", "10", "(level ?s_level&:(< ?s_level 10))"),
            ("less_than", "1", "(level ?s_level&:(< ?s_level 1))"),
        ],
        ids=["lt-10", "lt-1"],
    )
    def test_less_than(self, compiler: Compiler, op: str, arg: str, expected: str) -> None:
        result = compiler._compile_condition("level", f"{op}({arg})", {}, None)
        assert result == expected

    @pytest.mark.parametrize(
        "arg,expected",
        [
            (
                "[secret, top-secret]",
                "(clearance ?s_clearance&:(or (eq ?s_clearance secret)"
                " (eq ?s_clearance top-secret)))",
            ),
            (
                "[a, b, c]",
                "(clearance ?s_clearance&:(or (eq ?s_clearance a)"
                " (eq ?s_clearance b) (eq ?s_clearance c)))",
            ),
        ],
        ids=["in-two", "in-three"],
    )
    def test_in(self, compiler: Compiler, arg: str, expected: str) -> None:
        result = compiler._compile_condition("clearance", f"in({arg})", {}, None)
        assert result == expected

    @pytest.mark.parametrize(
        "arg,expected",
        [
            ("[public, internal]", "(clearance ?s_clearance&~public&~internal)"),
            ("[a]", "(clearance ?s_clearance&~a)"),
        ],
        ids=["not-in-two", "not-in-single"],
    )
    def test_not_in(self, compiler: Compiler, arg: str, expected: str) -> None:
        result = compiler._compile_condition("clearance", f"not_in({arg})", {}, None)
        assert result == expected

    def test_contains(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("name", "contains(admin)", {}, None)
        assert result == "(name ?s_name&:(str-index admin ?s_name))"

    def test_contains_different_slot(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("description", "contains(danger)", {}, None)
        assert result == "(description ?s_description&:(str-index danger ?s_description))"

    @pytest.mark.parametrize(
        "pattern,expected_pattern",
        [
            (".*admin.*", ".*admin.*"),
            ("^test$", "^test$"),
        ],
        ids=["regex-admin", "regex-anchored"],
    )
    def test_matches(self, compiler: Compiler, pattern: str, expected_pattern: str) -> None:
        result = compiler._compile_condition("name", f"matches({pattern})", {}, None)
        assert f'(name ?s_name&:(fathom-matches ?s_name "{expected_pattern}"))' == result

    def test_matches_escapes_special_chars(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("name", 'matches(test\\"quote)', {}, None)
        assert "fathom-matches" in result
        assert '\\\\"' in result  # escaped quote


# ---------------------------------------------------------------------------
# TestCompileConditionClassification -- classification operators
# ---------------------------------------------------------------------------


class TestCompileConditionClassification:
    """Test classification operators: below, meets_or_exceeds, within_scope."""

    @pytest.mark.parametrize(
        "op,clips_fn",
        [
            ("below", "below"),
            ("meets_or_exceeds", "meets-or-exceeds"),
            ("within_scope", "within-scope"),
        ],
        ids=["below", "meets-or-exceeds", "within-scope"],
    )
    def test_classification_ops_with_literal(
        self, compiler: Compiler, op: str, clips_fn: str
    ) -> None:
        result = compiler._compile_condition("clearance", f"{op}(secret)", {}, "$agent")
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(clearance ?agent-clearance)"
        assert test_ce == f"(test ({clips_fn} ?agent-clearance secret))"

    @pytest.mark.parametrize(
        "op,clips_fn",
        [
            ("below", "below"),
            ("meets_or_exceeds", "meets-or-exceeds"),
            ("within_scope", "within-scope"),
        ],
        ids=["below-xref", "meets-xref", "scope-xref"],
    )
    def test_classification_ops_with_cross_ref(
        self, compiler: Compiler, op: str, clips_fn: str
    ) -> None:
        result = compiler._compile_condition(
            "clearance", f"{op}($data.classification)", {}, "$agent"
        )
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(clearance ?agent-clearance)"
        assert test_ce == f"(test ({clips_fn} ?agent-clearance ?data-classification))"

    def test_classification_without_alias_uses_v_prefix(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("clearance", "below(secret)", {}, None)
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(clearance ?v-clearance)"
        assert test_ce == "(test (below ?v-clearance secret))"


# ---------------------------------------------------------------------------
# TestCompileConditionTemporal -- temporal operators
# ---------------------------------------------------------------------------


class TestCompileConditionTemporal:
    """Test temporal operators: changed_within, count_exceeds, rate_exceeds."""

    def test_changed_within(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("timestamp", "changed_within(300)", {}, "$event")
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(timestamp ?event-timestamp)"
        assert test_ce == "(test (fathom-changed-within ?event-timestamp 300))"

    def test_changed_within_no_alias(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("ts", "changed_within(60)", {}, None)
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(ts ?v-ts)"
        assert test_ce == "(test (fathom-changed-within ?v-ts 60))"

    def test_count_exceeds(self, compiler: Compiler) -> None:
        result = compiler._compile_condition(
            "action", "count_exceeds(audit-log, action, login, 5)", {}, "$evt"
        )
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(action ?evt-action)"
        assert test_ce == '(test (fathom-count-exceeds "audit-log" "action" "login" 5))'

    def test_rate_exceeds(self, compiler: Compiler) -> None:
        result = compiler._compile_condition(
            "action",
            "rate_exceeds(audit-log, action, login, 10, 300)",
            {},
            "$evt",
        )
        assert isinstance(result, tuple)
        slot_binding, test_ce = result
        assert slot_binding == "(action ?evt-action)"
        assert test_ce == ('(test (fathom-rate-exceeds "audit-log" "action" "login" 10 300 "ts"))')


# ---------------------------------------------------------------------------
# TestCrossRefs -- $alias.field references
# ---------------------------------------------------------------------------


class TestCrossRefs:
    """Test _resolve_cross_refs and cross-ref usage in conditions."""

    @pytest.mark.parametrize(
        "arg,expected",
        [
            ("$agent.id", "?agent-id"),
            ("$data.level", "?data-level"),
            ("$request.classification", "?request-classification"),
        ],
        ids=["agent-id", "data-level", "request-classification"],
    )
    def test_resolve_cross_refs(self, arg: str, expected: str) -> None:
        result = Compiler._resolve_cross_refs(arg)
        assert result == expected

    @pytest.mark.parametrize(
        "arg",
        ["secret", "123", "noDot", "plain-value"],
        ids=["word", "number", "camelCase", "hyphenated"],
    )
    def test_resolve_cross_refs_returns_none_for_literals(self, arg: str) -> None:
        result = Compiler._resolve_cross_refs(arg)
        assert result is None

    def test_resolve_cross_refs_no_dollar_sign(self) -> None:
        result = Compiler._resolve_cross_refs("agent.id")
        assert result is None

    def test_equals_with_cross_ref(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("id", "equals($agent.id)", {}, None)
        assert result == "(id ?agent-id)"

    def test_not_equals_with_cross_ref(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("status", "not_equals($other.status)", {}, None)
        assert result == "(status ?s_status&:(neq ?s_status ?other-status))"

    def test_greater_than_with_cross_ref(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("level", "greater_than($req.min_level)", {}, None)
        assert result == "(level ?s_level&:(> ?s_level ?req-min_level))"

    def test_less_than_with_cross_ref(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("priority", "less_than($other.priority)", {}, None)
        assert result == "(priority ?s_priority&:(< ?s_priority ?other-priority))"


# ---------------------------------------------------------------------------
# TestReasonInterpolation -- {variable} in reason strings
# ---------------------------------------------------------------------------


class TestReasonInterpolation:
    """Test _compile_reason for variable interpolation."""

    def test_plain_reason_quoted(self) -> None:
        result = Compiler._compile_reason("Access denied")
        assert result == '"Access denied"'

    def test_single_variable(self) -> None:
        result = Compiler._compile_reason("{clearance} insufficient")
        assert result == '(str-cat ?clearance " insufficient")'

    def test_multiple_variables(self) -> None:
        result = Compiler._compile_reason("Agent {agent_id} has {clearance} clearance")
        assert "str-cat" in result
        assert "?agent_id" in result
        assert "?clearance" in result

    def test_variable_at_end(self) -> None:
        result = Compiler._compile_reason("Level is {level}")
        assert result == '(str-cat "Level is " ?level)'

    def test_variable_at_start(self) -> None:
        result = Compiler._compile_reason("{action} taken")
        assert result == '(str-cat ?action " taken")'

    def test_adjacent_variables(self) -> None:
        result = Compiler._compile_reason("{a}{b}")
        assert result == "(str-cat ?a ?b)"

    def test_reason_with_quotes_escaped(self) -> None:
        result = Compiler._compile_reason('Said "hello"')
        assert r"\"hello\"" in result

    def test_empty_reason(self) -> None:
        result = Compiler._compile_reason("")
        assert result == '""'


# ---------------------------------------------------------------------------
# TestParseOperator -- _parse_operator
# ---------------------------------------------------------------------------


class TestParseOperator:
    """Test _parse_operator expression parsing."""

    @pytest.mark.parametrize(
        "expr,expected_op,expected_arg",
        [
            ("equals(secret)", "equals", "secret"),
            ("not_equals(public)", "not_equals", "public"),
            ("greater_than(5)", "greater_than", "5"),
            ("less_than(10)", "less_than", "10"),
            ("in([a, b])", "in", "[a, b]"),
            ("matches(.*admin.*)", "matches", ".*admin.*"),
            ("contains(test)", "contains", "test"),
            ("below(secret)", "below", "secret"),
        ],
        ids=[
            "equals",
            "not_equals",
            "gt",
            "lt",
            "in",
            "matches",
            "contains",
            "below",
        ],
    )
    def test_parse_operator(self, expr: str, expected_op: str, expected_arg: str) -> None:
        op, arg = Compiler._parse_operator(expr)
        assert op == expected_op
        assert arg == expected_arg

    def test_parse_operator_invalid_no_parens(self) -> None:
        with pytest.raises(CompilationError, match="(?i)invalid.*expression"):
            Compiler._parse_operator("equals_secret")

    def test_parse_operator_invalid_no_closing_paren(self) -> None:
        with pytest.raises(CompilationError, match="(?i)invalid.*expression"):
            Compiler._parse_operator("equals(secret")


# ---------------------------------------------------------------------------
# TestParseListArg -- _parse_list_arg
# ---------------------------------------------------------------------------


class TestParseListArg:
    """Test _parse_list_arg bracket parsing."""

    def test_two_items(self) -> None:
        result = Compiler._parse_list_arg("[a, b]")
        assert result == ["a", "b"]

    def test_three_items(self) -> None:
        result = Compiler._parse_list_arg("[x, y, z]")
        assert result == ["x", "y", "z"]

    def test_single_item(self) -> None:
        result = Compiler._parse_list_arg("[only]")
        assert result == ["only"]

    def test_strips_whitespace(self) -> None:
        result = Compiler._parse_list_arg("[  a ,  b  ]")
        assert result == ["a", "b"]

    def test_no_brackets_raises(self) -> None:
        with pytest.raises(CompilationError, match="(?i)expected list argument"):
            Compiler._parse_list_arg("a, b")

    def test_empty_list_raises(self) -> None:
        with pytest.raises(CompilationError, match="(?i)empty list argument"):
            Compiler._parse_list_arg("[]")


# ---------------------------------------------------------------------------
# TestCompileRule -- full rule compilation
# ---------------------------------------------------------------------------


class TestCompileRule:
    """Test compile_rule for full defrule generation."""

    def test_basic_rule_structure(self, compiler: Compiler) -> None:
        rule = _make_rule()
        result = compiler.compile_rule(rule, "governance")
        assert result.startswith("(defrule governance::test-rule")
        assert "(agent" in result
        assert "(clearance secret)" in result
        assert "=>" in result
        assert "__fathom_decision" in result
        assert result.strip().endswith(")")

    def test_salience_included_when_nonzero(self, compiler: Compiler) -> None:
        rule = _make_rule(salience=100)
        result = compiler.compile_rule(rule, "governance")
        assert "(declare (salience 100))" in result

    def test_salience_omitted_when_zero(self, compiler: Compiler) -> None:
        rule = _make_rule(salience=0)
        result = compiler.compile_rule(rule, "governance")
        assert "salience" not in result

    def test_negative_salience(self, compiler: Compiler) -> None:
        rule = _make_rule(salience=-50)
        result = compiler.compile_rule(rule, "governance")
        assert "(declare (salience -50))" in result

    def test_module_prefix_in_rule_name(self, compiler: Compiler) -> None:
        rule = _make_rule(name="my-rule")
        result = compiler.compile_rule(rule, "security")
        assert "(defrule security::my-rule" in result

    def test_multiple_fact_patterns(self, compiler: Compiler) -> None:
        patterns = [
            FactPattern(
                template="agent",
                conditions=[ConditionEntry(slot="clearance", expression="equals(secret)")],
            ),
            FactPattern(
                template="data_request",
                conditions=[
                    ConditionEntry(slot="classification", expression="equals(top-secret)")
                ],
            ),
        ]
        rule = _make_rule(when=patterns)
        result = compiler.compile_rule(rule, "gov")
        assert "(agent (clearance secret))" in result
        assert "(data_request (classification top-secret))" in result

    def test_fact_pattern_no_conditions(self, compiler: Compiler) -> None:
        patterns = [FactPattern(template="agent", conditions=[])]
        rule = _make_rule(when=patterns)
        result = compiler.compile_rule(rule, "mod")
        assert "(agent)" in result

    def test_action_deny(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="denied")
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "(action deny)" in result

    def test_action_allow(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.ALLOW, reason="allowed")
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "(action allow)" in result

    @pytest.mark.parametrize(
        "action",
        [ActionType.ESCALATE, ActionType.SCOPE, ActionType.ROUTE],
        ids=["escalate", "scope", "route"],
    )
    def test_action_types(self, compiler: Compiler, action: ActionType) -> None:
        then = ThenBlock(action=action, reason="test")
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert f"(action {action.value})" in result

    @pytest.mark.parametrize(
        "log_level",
        [LogLevel.NONE, LogLevel.SUMMARY, LogLevel.FULL],
        ids=["log-none", "log-summary", "log-full"],
    )
    def test_log_levels(self, compiler: Compiler, log_level: LogLevel) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="test", log=log_level)
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert f"(log-level {log_level.value})" in result

    def test_notify_field(self, compiler: Compiler) -> None:
        then = ThenBlock(
            action=ActionType.DENY,
            reason="test",
            notify=["admin@test.com", "ops@test.com"],
        )
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "admin@test.com, ops@test.com" in result

    def test_attestation_true(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="test", attestation=True)
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "(attestation TRUE)" in result

    def test_attestation_false(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="test", attestation=False)
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "(attestation FALSE)" in result

    def test_metadata_field(self, compiler: Compiler) -> None:
        then = ThenBlock(
            action=ActionType.DENY,
            reason="test",
            metadata={"key1": "val1", "key2": "val2"},
        )
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        # metadata is JSON-encoded inside a CLIPS string
        assert '(metadata "{\\"key1\\": \\"val1\\", \\"key2\\": \\"val2\\"}")' in result

    def test_reason_in_rhs(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="Access denied: clearance")
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert '(reason "Access denied: clearance")' in result

    def test_reason_with_interpolation_in_rhs(self, compiler: Compiler) -> None:
        then = ThenBlock(
            action=ActionType.DENY,
            reason="Agent {agent_id} denied",
        )
        rule = _make_rule(then=then)
        result = compiler.compile_rule(rule, "mod")
        assert "(reason (str-cat" in result
        assert "?agent_id" in result

    def test_rule_name_in_decision(self, compiler: Compiler) -> None:
        rule = _make_rule(name="deny-access")
        result = compiler.compile_rule(rule, "governance")
        assert '(rule "governance::deny-access")' in result

    def test_classification_conditions_produce_test_ces(self, compiler: Compiler) -> None:
        patterns = [
            FactPattern(
                template="agent",
                alias="$agent",
                conditions=[
                    ConditionEntry(
                        slot="clearance",
                        expression="below($data.classification)",
                    )
                ],
            ),
            FactPattern(
                template="data_request",
                alias="$data",
                conditions=[
                    ConditionEntry(slot="classification", expression="equals(top-secret)")
                ],
            ),
        ]
        rule = _make_rule(when=patterns)
        result = compiler.compile_rule(rule, "gov")
        # Test CE should appear after all patterns
        lines = result.split("\n")
        test_line_indices = [i for i, line in enumerate(lines) if "(test (below" in line]
        pattern_line_indices = [i for i, line in enumerate(lines) if "(data_request" in line]
        # test CE must come after pattern CEs
        assert len(test_line_indices) == 1
        assert test_line_indices[0] > pattern_line_indices[0]


# ---------------------------------------------------------------------------
# TestCompileAction -- _compile_action
# ---------------------------------------------------------------------------


class TestCompileAction:
    """Test _compile_action for RHS generation."""

    def test_basic_action(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.DENY, reason="test deny")
        result = compiler._compile_action(then, "mod::rule")
        assert "(assert (__fathom_decision" in result
        assert "(action deny)" in result
        assert '(reason "test deny")' in result
        assert '(rule "mod::rule")' in result

    def test_empty_notify(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.ALLOW, reason="ok")
        result = compiler._compile_action(then, "mod::rule")
        assert '(notify "")' in result

    def test_empty_metadata(self, compiler: Compiler) -> None:
        then = ThenBlock(action=ActionType.ALLOW, reason="ok")
        result = compiler._compile_action(then, "mod::rule")
        assert '(metadata "")' in result


# ---------------------------------------------------------------------------
# TestCompileAssertAction -- user-asserts in RHS (FR-5, FR-6, FR-7, FR-15)
# ---------------------------------------------------------------------------


class TestCompileAssertAction:
    """Test RHS emission for action-only, assert-only, and empty-assert rules."""

    def test_action_only_emission_unchanged(self, compiler: Compiler) -> None:
        """AC-4.3: a rule with only `action` must emit the pre-spec RHS shape."""
        rule = _make_rule(
            name="test-rule",
            then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        expected = (
            "(defrule MAIN::test-rule "
            "(agent (clearance secret)) "
            "=> "
            "(assert (__fathom_decision "
            "(action allow) "
            '(reason "ok") '
            '(rule "MAIN::test-rule") '
            "(log-level summary) "
            '(notify "") '
            "(attestation FALSE) "
            '(metadata ""))) '
            ")"
        )
        assert normalize_clips(result) == expected

    def test_assert_only_no_decision_line(self, compiler: Compiler) -> None:
        """AC-1.1, FR-7: assert-only rule (action=None) emits no __fathom_decision."""
        rule = _make_rule(
            name="assert-rule",
            then=ThenBlock(
                asserts=[AssertSpec(template="routing_decision", slots={"source_id": "?sid"})]
            ),
        )
        result = compiler.compile_rule(rule, "MAIN")
        assert "__fathom_decision" not in result
        assert "(assert (routing_decision (source_id ?sid)))" in result

    def test_empty_asserts_with_action(self, compiler: Compiler) -> None:
        """FR-15: empty asserts + action emits only the __fathom_decision line."""
        rule = _make_rule(
            name="empty-rule",
            then=ThenBlock(action=ActionType.DENY, reason="denied", asserts=[]),
        )
        result = compiler.compile_rule(rule, "MAIN")
        assert "(assert (__fathom_decision" in result
        # Exactly one (assert ...) in the RHS — no trailing user asserts.
        assert result.count("(assert (") == 1

    def test_multiple_asserts_preserve_yaml_order(self, compiler: Compiler) -> None:
        """AC-1.2: multiple asserts are emitted in YAML list order."""
        rule = _make_rule(
            name="multi-assert-rule",
            then=ThenBlock(
                asserts=[
                    AssertSpec(template="first_fact", slots={"id": "?a"}),
                    AssertSpec(template="second_fact", slots={"id": "?b"}),
                    AssertSpec(template="third_fact", slots={"id": "?c"}),
                ]
            ),
        )
        result = compiler.compile_rule(rule, "MAIN")
        idx_first = result.index("(first_fact")
        idx_second = result.index("(second_fact")
        idx_third = result.index("(third_fact")
        assert idx_first < idx_second < idx_third

    def test_coexist_decision_then_asserts(self, compiler: Compiler) -> None:
        """AC-1.3, UQ-3: __fathom_decision first, then user asserts in YAML order."""
        rule = _make_rule(
            name="coexist-rule",
            then=ThenBlock(
                action=ActionType.ALLOW,
                reason="ok",
                asserts=[
                    AssertSpec(template="audit_event", slots={"kind": '"login"'}),
                    AssertSpec(template="routing_decision", slots={"source_id": "?sid"}),
                ],
            ),
        )
        result = compiler.compile_rule(rule, "MAIN")
        idx_decision = result.index("__fathom_decision")
        idx_first_assert = result.index("(audit_event")
        idx_second_assert = result.index("(routing_decision")
        assert idx_decision < idx_first_assert < idx_second_assert

    def test_slot_value_variable_passthrough(self) -> None:
        """FR-6: slot values starting with ``?`` are emitted verbatim."""
        assert Compiler._emit_slot_value("?v") == "?v"

    def test_slot_value_expression_passthrough(self) -> None:
        """FR-6: slot values starting with ``(`` are emitted verbatim."""
        assert Compiler._emit_slot_value("(f ?a)") == "(f ?a)"

    def test_slot_value_string_quoted(self) -> None:
        """FR-6: bare string slot values are CLIPS-quoted."""
        assert Compiler._emit_slot_value("hi") == '"hi"'

    def test_slot_value_string_escapes_quotes_and_backslash(self) -> None:
        """FR-6: backslashes and quotes in bare strings are escaped."""
        assert Compiler._emit_slot_value('a"b\\c') == '"a\\"b\\\\c"'


# ---------------------------------------------------------------------------
# TestCompileBind -- LHS bind emission (AC-2.1, AC-2.3, AC-2.5, FR-9)
# ---------------------------------------------------------------------------


class TestCompileBind:
    """Test LHS bind emission: bind-only, bind+expression, and no-bind regression."""

    def test_bind_only_emits_slot_var(self, compiler: Compiler) -> None:
        """AC-2.1: bind without expression emits `(slot ?var)` in the LHS."""
        rule = _make_rule(
            name="bind-only",
            when=[
                FactPattern(
                    template="source",
                    conditions=[ConditionEntry(slot="id", bind="?sid")],
                )
            ],
            then=ThenBlock(asserts=[AssertSpec(template="r", slots={"id": "?sid"})]),
        )
        result = compiler.compile_rule(rule, "MAIN")
        assert "(source (id ?sid))" in result

    def test_bind_with_equals_expression(self, compiler: Compiler) -> None:
        """AC-2.3: bind + equals(literal) emits `(slot ?var&literal)` using `&` combinator."""
        rule = _make_rule(
            name="bind-eq",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[
                        ConditionEntry(slot="level", bind="?lvl", expression="equals(secret)")
                    ],
                )
            ],
            then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        # Bind variable appears and is joined to the equality constraint via `&`.
        assert "?lvl" in result
        assert "(agent (level ?lvl&secret))" in result

    def test_bind_with_not_equals_expression(self, compiler: Compiler) -> None:
        """AC-2.3: bind + not_equals emits `(slot ?var&?s_slot&:(neq ?s_slot literal))`."""
        rule = _make_rule(
            name="bind-neq",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[
                        ConditionEntry(slot="level", bind="?lvl", expression="not_equals(public)")
                    ],
                )
            ],
            then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        # Bind variable appears and is joined to the inequality constraint via `&`.
        assert "?lvl" in result
        assert "(agent (level ?lvl&?s_level&:(neq ?s_level public)))" in result

    def test_test_standalone_emits_only_test_ce(self, compiler: Compiler) -> None:
        """``test`` alone emits ``(test ...)`` without a slot pattern."""
        rule = _make_rule(
            name="raw-test",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[ConditionEntry(test="(my-fn)")],
                )
            ],
            then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        assert "(agent)" in result
        assert "(test (my-fn))" in result

    def test_test_combined_with_bind_emits_both(self, compiler: Compiler) -> None:
        """``test`` combined with ``bind`` emits slot pattern AND test CE."""
        rule = _make_rule(
            name="bind-and-test",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[
                        ConditionEntry(slot="id", bind="?sid", test="(my-fn ?sid)"),
                    ],
                )
            ],
            then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        assert "(agent (id ?sid))" in result
        assert "(test (my-fn ?sid))" in result

    def test_no_bind_byte_identical_to_preslot(self, compiler: Compiler) -> None:
        """AC-2.5: a rule with no `bind` on any ConditionEntry compiles byte-identically
        to the pre-spec output (regression guard against accidental bind-path leakage).
        """
        rule = _make_rule(
            name="test-rule",
            then=ThenBlock(action=ActionType.DENY, reason="test reason"),
        )
        result = compiler.compile_rule(rule, "MAIN")
        expected = (
            "(defrule MAIN::test-rule "
            "(agent (clearance secret)) "
            "=> "
            "(assert (__fathom_decision "
            "(action deny) "
            '(reason "test reason") '
            '(rule "MAIN::test-rule") '
            "(log-level summary) "
            '(notify "") '
            "(attestation FALSE) "
            '(metadata ""))) '
            ")"
        )
        assert normalize_clips(result) == expected


# ---------------------------------------------------------------------------
# TestCompileFactPattern -- _compile_fact_pattern
# ---------------------------------------------------------------------------


class TestCompileFactPattern:
    """Test _compile_fact_pattern for LHS pattern generation."""

    def test_empty_conditions(self, compiler: Compiler) -> None:
        pattern = FactPattern(template="agent", conditions=[])
        lhs, test_ces = compiler._compile_fact_pattern(pattern, {})
        assert lhs == "(agent)"
        assert test_ces == []

    def test_single_condition(self, compiler: Compiler) -> None:
        pattern = FactPattern(
            template="agent",
            conditions=[ConditionEntry(slot="clearance", expression="equals(secret)")],
        )
        lhs, test_ces = compiler._compile_fact_pattern(pattern, {})
        assert lhs == "(agent (clearance secret))"
        assert test_ces == []

    def test_multiple_conditions(self, compiler: Compiler) -> None:
        pattern = FactPattern(
            template="agent",
            conditions=[
                ConditionEntry(slot="clearance", expression="equals(secret)"),
                ConditionEntry(slot="role", expression="equals(admin)"),
            ],
        )
        lhs, test_ces = compiler._compile_fact_pattern(pattern, {})
        assert "(clearance secret)" in lhs
        assert "(role admin)" in lhs

    def test_classification_condition_returns_test_ce(self, compiler: Compiler) -> None:
        pattern = FactPattern(
            template="agent",
            alias="$agent",
            conditions=[ConditionEntry(slot="clearance", expression="below(top-secret)")],
        )
        lhs, test_ces = compiler._compile_fact_pattern(pattern, {})
        assert "(clearance ?agent-clearance)" in lhs
        assert len(test_ces) == 1
        assert "(test (below ?agent-clearance top-secret))" in test_ces[0]


# ---------------------------------------------------------------------------
# TestValidation -- error cases
# ---------------------------------------------------------------------------


class TestRuleValidation:
    """Test validation errors in compile_rule and operators."""

    def test_empty_rule_name_raises(self, compiler: Compiler) -> None:
        # Empty name now rejected at the Pydantic model layer.
        with pytest.raises(ValueError, match="valid CLIPS identifier"):
            _make_rule(name="")

    def test_empty_when_raises(self, compiler: Compiler) -> None:
        rule = RuleDefinition(
            name="bad-rule",
            when=[],
            then=ThenBlock(action=ActionType.DENY, reason="test"),
        )
        with pytest.raises(CompilationError, match="no conditions"):
            compiler.compile_rule(rule, "mod")

    def test_unsupported_operator_raises(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)unsupported condition operator"):
            compiler._compile_condition("slot", "bogus(value)", {}, None)

    def test_invalid_expression_format_raises(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)invalid.*expression"):
            compiler._compile_condition("slot", "noparens", {}, None)

    def test_empty_list_arg_raises(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)empty list argument"):
            compiler._compile_condition("slot", "in([])", {}, None)

    def test_not_in_empty_list_raises(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)empty list argument"):
            compiler._compile_condition("slot", "not_in([])", {}, None)

    def test_non_bracket_list_raises(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)expected list argument"):
            compiler._compile_condition("slot", "in(a, b)", {}, None)


# ---------------------------------------------------------------------------
# TestParseRuleFile -- YAML parsing
# ---------------------------------------------------------------------------


class TestParseRuleFile:
    """Test parse_rule_file for YAML rule file parsing."""

    def test_parse_valid_rule_file(self, compiler: Compiler, sample_rules_path: Path) -> None:
        result = compiler.parse_rule_file(sample_rules_path)
        assert result.module == "governance"
        assert len(result.rules) >= 1
        assert result.rules[0].name == "deny-insufficient-clearance"

    def test_parse_rule_file_has_when_and_then(
        self, compiler: Compiler, sample_rules_path: Path
    ) -> None:
        result = compiler.parse_rule_file(sample_rules_path)
        rule = result.rules[0]
        assert len(rule.when) > 0
        assert rule.then.action == ActionType.DENY

    def test_parse_rule_file_missing_module_raises(
        self, compiler: Compiler, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(
            "rules:\n  - name: test\n    when: []\n    then:\n      action: deny\n"
        )
        with pytest.raises(CompilationError, match="module"):
            compiler.parse_rule_file(yaml_file)

    def test_parse_rule_file_missing_rules_raises(
        self, compiler: Compiler, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("module: test\n")
        with pytest.raises(CompilationError, match="rules"):
            compiler.parse_rule_file(yaml_file)

    def test_parse_rule_file_invalid_yaml_raises(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(": : invalid:\nyaml:: [")
        with pytest.raises(CompilationError, match="(?i)invalid YAML"):
            compiler.parse_rule_file(yaml_file)

    def test_parse_rule_file_nonexistent_raises(self, compiler: Compiler, tmp_path: Path) -> None:
        with pytest.raises(CompilationError, match="(?i)cannot read file"):
            compiler.parse_rule_file(tmp_path / "nonexistent.yaml")

    def test_parse_rule_file_duplicate_rule_names_raises(
        self, compiler: Compiler, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "dup.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            module: test
            rules:
              - name: same-rule
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: "r1"
              - name: same-rule
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(b)"
                then:
                  action: allow
                  reason: "r2"
        """)
        )
        with pytest.raises(CompilationError, match="(?i)duplicate rule name"):
            compiler.parse_rule_file(yaml_file)

    def test_parse_rule_file_default_version(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "ver.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            module: test
            rules:
              - name: r1
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: "r"
        """)
        )
        result = compiler.parse_rule_file(yaml_file)
        assert result.version == "1.0"

    def test_parse_rule_file_explicit_version(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "ver.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            module: test
            version: "2.5"
            rules:
              - name: r1
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: "r"
        """)
        )
        result = compiler.parse_rule_file(yaml_file)
        assert result.version == "2.5"

    def test_parse_rule_file_ruleset_from_filename(
        self, compiler: Compiler, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "my-rules.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            module: test
            rules:
              - name: r1
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: "r"
        """)
        )
        result = compiler.parse_rule_file(yaml_file)
        assert result.ruleset == "my-rules"

    def test_parse_rule_file_explicit_ruleset(self, compiler: Compiler, tmp_path: Path) -> None:
        yaml_file = tmp_path / "file.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            module: test
            ruleset: custom-name
            rules:
              - name: r1
                when:
                  - template: agent
                    conditions:
                      - slot: x
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: "r"
        """)
        )
        result = compiler.parse_rule_file(yaml_file)
        assert result.ruleset == "custom-name"

    def test_parse_rule_file_salience(self, compiler: Compiler, sample_rules_path: Path) -> None:
        result = compiler.parse_rule_file(sample_rules_path)
        rule = result.rules[0]
        assert rule.salience == 100


# ---------------------------------------------------------------------------
# TestEscapeClipsString -- string escaping edge cases
# ---------------------------------------------------------------------------


class TestEscapeClipsString:
    """Test _escape_clips_string in rule context."""

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("hello", "hello"),
            ('say "hi"', 'say \\"hi\\"'),
            ("back\\slash", "back\\\\slash"),
            ('both "and" \\here', 'both \\"and\\" \\\\here'),
        ],
        ids=["plain", "quotes", "backslash", "both"],
    )
    def test_escape_clips_string(self, input_str: str, expected: str) -> None:
        result = Compiler._escape_clips_string(input_str)
        assert result == expected
