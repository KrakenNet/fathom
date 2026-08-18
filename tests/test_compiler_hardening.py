"""Regression tests for compiler/model hardening (1.0 audit findings).

Covers constraint-variable namespacing across fact patterns, strict YAML
schemas (``extra="forbid"``), operator argument validation, temporal operator
arity, and type-aware ``equals`` emission.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError as PydanticValidationError

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError, FathomError, ScopeError
from fathom.models import (
    ConditionEntry,
    FactPattern,
    FunctionDefinition,
    HierarchyDefinition,
    ModuleDefinition,
    RuleDefinition,
    RulesetDefinition,
    SlotDefinition,
    SlotType,
    TemplateDefinition,
    ThenBlock,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def compiler() -> Compiler:
    return Compiler()


def _write_pack(root: Path, rules_yaml: str, templates_yaml: str) -> Path:
    """Write a minimal templates/modules/rules pack and return its directory."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "templates.yaml").write_text(templates_yaml)
    (root / "modules.yaml").write_text(
        "modules:\n  - name: governance\nfocus_order: [governance]\n"
    )
    (root / "rules.yaml").write_text(rules_yaml)
    return root


# ---------------------------------------------------------------------------
# Constraint variable collision across fact patterns
# ---------------------------------------------------------------------------


class TestSlotVariableNamespacing:
    """Two patterns constraining a same-named slot must not join on it."""

    def test_same_slot_name_in_two_patterns_is_not_joined(self, compiler: Compiler) -> None:
        rule = RuleDefinition(
            name="deny-unclassified-pair",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[ConditionEntry(slot="level", expression="not_equals(none)")],
                ),
                FactPattern(
                    template="resource",
                    conditions=[ConditionEntry(slot="level", expression="not_equals(none)")],
                ),
            ],
            then=ThenBlock(action="allow", reason="both non-none"),
        )
        result = compiler.compile_rule(rule, "governance")

        assert "?s_0_level" in result
        assert "?s_1_level" in result

    def test_unaliased_classification_patterns_get_distinct_variables(
        self, compiler: Compiler
    ) -> None:
        rule = RuleDefinition(
            name="two-classification-patterns",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[ConditionEntry(slot="level", expression="below(secret)")],
                ),
                FactPattern(
                    template="resource",
                    conditions=[ConditionEntry(slot="level", expression="below(secret)")],
                ),
            ],
            then=ThenBlock(action="allow", reason="ok"),
        )
        result = compiler.compile_rule(rule, "governance")

        assert "?p0-level" in result
        assert "?p1-level" in result

    def test_rule_fires_when_two_patterns_hold_different_values(self, tmp_path: Path) -> None:
        """End-to-end: agent.level=secret + resource.level=public must fire."""
        pack = _write_pack(
            tmp_path / "pack",
            rules_yaml=textwrap.dedent("""\
                module: governance
                ruleset: collide
                rules:
                  - name: deny-unclassified-pair
                    when:
                      - template: agent
                        conditions:
                          - slot: level
                            expression: "not_equals(none)"
                      - template: resource
                        conditions:
                          - slot: level
                            expression: "not_equals(none)"
                    then:
                      action: allow
                      reason: "both non-none"
            """),
            templates_yaml=textwrap.dedent("""\
                templates:
                  - name: agent
                    slots:
                      - name: level
                        type: symbol
                  - name: resource
                    slots:
                      - name: level
                        type: symbol
            """),
        )
        engine = Engine.from_rules(str(pack))
        engine.assert_fact("agent", {"level": "secret"})
        engine.assert_fact("resource", {"level": "public"})
        result = engine.evaluate()

        assert result.reason == "both non-none"
        assert any(r.endswith("deny-unclassified-pair") for r in result.rule_trace)


# ---------------------------------------------------------------------------
# Strict YAML schemas
# ---------------------------------------------------------------------------


class TestExtraKeysForbidden:
    """Typo'd YAML keys must be validation errors, not silently dropped."""

    def test_rule_definition_rejects_misspelled_salience(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            RuleDefinition(
                name="r",
                sailence=999,
                when=[
                    FactPattern(
                        template="t",
                        conditions=[ConditionEntry(slot="x", expression="equals(a)")],
                    )
                ],
                then=ThenBlock(action="deny", reason="r"),
            )

    def test_slot_definition_rejects_misspelled_required(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            SlotDefinition(name="s", type="string", requried=True)

    def test_fact_pattern_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            FactPattern(
                template="t",
                conditions=[ConditionEntry(slot="x", expression="equals(a)")],
                temporal={"operator": "count_exceeds"},
            )

    def test_condition_entry_rejects_misspelled_expression(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            ConditionEntry(slot="x", expresion="equals(a)")

    def test_then_block_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            ThenBlock(action="deny", reason="r", actionn="allow")

    def test_then_block_still_accepts_assert_alias(self) -> None:
        block = ThenBlock(**{"action": "allow", "assert": [{"template": "audit", "slots": {}}]})
        assert block.asserts[0].template == "audit"

    def test_template_definition_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            TemplateDefinition(name="t", slots=[{"name": "s", "type": "string"}], tll=5)

    def test_module_definition_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            ModuleDefinition(name="m", prioritty=1)

    def test_ruleset_definition_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            RulesetDefinition(ruleset="r", module="m", rules=[], versionn="1.0")

    def test_function_definition_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            FunctionDefinition(name="f", params=[], bodyy="(x)")

    def test_hierarchy_definition_rejects_unknown_key(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)extra"):
            HierarchyDefinition(name="h", levels=["low"], compartmets=["a"])


# ---------------------------------------------------------------------------
# CLIPS identifier hardening
# ---------------------------------------------------------------------------


class TestIdentifierHardening:
    """Values interpolated into generated CLIPS must be identifiers."""

    def test_fact_pattern_template_rejects_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            FactPattern(
                template='agent) (test (system "touch /tmp/PWNED")) (agent',
                conditions=[ConditionEntry(slot="name", expression='equals("bob")')],
            )

    def test_fact_pattern_alias_rejects_injection(self) -> None:
        """The alias is interpolated into generated CLIPS variable names."""
        with pytest.raises(PydanticValidationError, match="(?i)CLIPS identifier"):
            FactPattern(
                template="agent",
                alias='$v-level)) (test (system "touch /tmp/PWNED")) (agent (level ?zz',
                conditions=[ConditionEntry(slot="level", expression="equals(secret)")],
            )

    def test_fact_pattern_alias_must_start_with_dollar(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)must start with"):
            FactPattern(
                template="agent",
                alias="req",
                conditions=[ConditionEntry(slot="level", expression="equals(secret)")],
            )

    def test_fact_pattern_alias_cannot_take_the_generated_namespace(self) -> None:
        """`$p<N>` is what unaliased patterns get — sharing it silently joins."""
        with pytest.raises(PydanticValidationError, match="(?i)reserved"):
            FactPattern(
                template="agent",
                alias="$p1",
                conditions=[ConditionEntry(slot="level", expression="equals(secret)")],
            )

    def test_duplicate_aliases_are_rejected(self, compiler: Compiler) -> None:
        """Two patterns sharing an alias used to overwrite silently."""
        cond = [ConditionEntry(slot="level", expression="equals(secret)")]
        rule = RuleDefinition(
            name="dup",
            when=[
                FactPattern(template="agent", alias="$a", conditions=cond),
                FactPattern(template="resource", alias="$a", conditions=cond),
            ],
            then=ThenBlock(action="deny", reason="x"),
        )
        with pytest.raises(CompilationError, match="(?i)reuses alias"):
            compiler.compile_rule(rule, "gov")

    def test_condition_slot_rejects_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            ConditionEntry(
                slot='name "bob")) (test (system "touch /tmp/PWNED")) (agent (level',
                expression="equals(secret)",
            )

    def test_condition_bind_rejects_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)CLIPS identifier"):
            ConditionEntry(
                slot="name",
                bind='?v)) (test (system "touch /tmp/PWNED")) (agent (name ?w',
            )

    def test_condition_bind_accepts_plain_variable(self) -> None:
        assert ConditionEntry(slot="name", bind="?sid").bind == "?sid"

    def test_expression_rejects_early_close(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)closes its argument"):
            ConditionEntry(slot="id", expression='equals(a1)) (admin (level 9)')

    def test_expression_accepts_regex_and_quoted_arguments(self) -> None:
        assert ConditionEntry(slot="id", expression="matches(^(a|b)$)").expression
        assert ConditionEntry(slot="id", expression='has_compartments("")').expression

    @pytest.mark.parametrize(
        "expression",
        [
            "matches([)])",  # ')' inside a regex character class is literal
            "matches([(])",
            "contains(a :-) b)",  # free text containing a bare ')'
        ],
    )
    def test_escape_and_quote_operators_accept_bare_parens(self, expression: str) -> None:
        """`contains` and `matches` fully escape+quote their argument.

        Their argument cannot close the generated construct, so the
        paren-balance rule that protects the raw-emitting operators must not
        be applied to them — doing so rejected legitimate regexes.
        """
        assert ConditionEntry(slot="body", expression=expression).expression == expression

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("matches([)])", '(fathom-matches ?s_0_body "[)]")'),
            ("contains(a :-) b)", '(str-index "a :-) b" ?s_0_body)'),
        ],
    )
    def test_those_arguments_still_compile_to_a_quoted_construct(
        self, expression: str, expected: str
    ) -> None:
        """Accepting them is only safe because they land inside a CLIPS string."""
        rule = RuleDefinition(
            name="t",
            when=[FactPattern(template="agent", conditions=[
                ConditionEntry(slot="body", expression=expression)
            ])],
            then=ThenBlock(action="deny", reason="x"),
        )
        clips = Compiler().compile_rule(rule, "gov")
        assert expected in clips

    def test_hierarchy_levels_reject_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            HierarchyDefinition(
                name="clearance",
                levels=['low then (system "touch /tmp/PWNED")) (case zzz', "high"],
            )

    def test_slot_definition_name_rejects_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            SlotDefinition(name="name (type STRING)) (slot backdoor", type="string")

    def test_symbol_allowed_values_reject_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            SlotDefinition(
                name="lvl",
                type="symbol",
                allowed_values=["public", "secret)) (slot backdoor (type SYMBOL"],
            )

    def test_symbol_default_rejects_injection(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)valid CLIPS identifier"):
            SlotDefinition(name="lvl", type="symbol", default="ok)) (slot backdoor")

    def test_numeric_default_must_be_numeric(self) -> None:
        with pytest.raises(PydanticValidationError, match="(?i)must be numeric"):
            SlotDefinition(name="n", type="integer", default="ok)) (slot backdoor")

    def test_string_slot_literals_are_still_free_form(self) -> None:
        slot = SlotDefinition(name="s", type="string", allowed_values=["a b) c"], default="x y")
        assert slot.allowed_values == ["a b) c"]

    def test_operator_argument_rejects_embedded_call(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)invalid argument"):
            compiler._compile_condition(
                "name", 'not_equals((system "touch /tmp/PWNED"))', {}, None
            )

    def test_list_operator_arguments_are_validated(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError, match="(?i)invalid argument"):
            compiler._compile_condition("name", "in([a b, c])", {}, None)

    def test_condition_test_escape_hatch_still_passes_through(self, compiler: Compiler) -> None:
        pattern = FactPattern(
            template="agent",
            conditions=[ConditionEntry(test="(my-fn ?sid)")],
        )
        lhs, test_ces = compiler._compile_fact_pattern(pattern, {})
        assert lhs == "(agent)"
        assert test_ces == ["(test (my-fn ?sid))"]


# ---------------------------------------------------------------------------
# Operator diagnostics
# ---------------------------------------------------------------------------


class TestOperatorDiagnostics:
    def test_missing_operator_name_raises(self) -> None:
        with pytest.raises(CompilationError, match="(?i)missing operator name"):
            Compiler._parse_operator("(secret)")

    def test_unsupported_operator_lists_supported_operators(self, compiler: Compiler) -> None:
        with pytest.raises(CompilationError) as exc_info:
            compiler._compile_condition("x", "bogus(a)", {}, None)
        message = str(exc_info.value)
        for op in ("equals", "dominates", "in_compartment", "has_compartments", "last_n"):
            assert op in message

    @pytest.mark.parametrize(
        "expression",
        [
            "count_exceeds(a, b)",
            "rate_exceeds(a, b, c)",
            "last_n(a, b)",
            "distinct_count(a)",
            "sequence_detected(x)",
        ],
    )
    def test_temporal_arity_raises_compilation_error(
        self, compiler: Compiler, expression: str
    ) -> None:
        with pytest.raises(CompilationError, match="(?i)requires at least"):
            compiler._compile_condition("name", expression, {}, None)


# ---------------------------------------------------------------------------
# contains() quoting and type-aware equals
# ---------------------------------------------------------------------------


class TestLiteralEmission:
    def test_contains_quotes_multi_word_argument(self, compiler: Compiler) -> None:
        result = compiler._compile_condition("body", "contains(hello world)", {}, None)
        assert result == '(body ?s_0_body&:(str-index "hello world" ?s_0_body))'

    def test_contains_multi_word_matches_end_to_end(self, tmp_path: Path) -> None:
        pack = _write_pack(
            tmp_path / "contains",
            rules_yaml=textwrap.dedent("""\
                module: governance
                ruleset: contains
                rules:
                  - name: flag-phrase
                    when:
                      - template: message
                        conditions:
                          - slot: body
                            expression: "contains(access denied)"
                    then:
                      action: deny
                      reason: "phrase found"
            """),
            templates_yaml=textwrap.dedent("""\
                templates:
                  - name: message
                    slots:
                      - name: body
                        type: string
            """),
        )
        engine = Engine.from_rules(str(pack))
        engine.assert_fact("message", {"body": "the server said access denied today"})
        result = engine.evaluate()

        assert result.reason == "phrase found"

    def test_equals_quotes_literal_for_string_slot(self, compiler: Compiler) -> None:
        templates = {
            "user": TemplateDefinition(
                name="user",
                slots=[SlotDefinition(name="id", type=SlotType.STRING)],
            )
        }
        rule = RuleDefinition(
            name="email-match",
            when=[
                FactPattern(
                    template="user",
                    conditions=[
                        ConditionEntry(slot="id", expression="equals(alice@example.com)")
                    ],
                )
            ],
            then=ThenBlock(action="allow", reason="ok"),
        )
        result = compiler.compile_rule(rule, "governance", templates)
        assert '(user (id "alice@example.com"))' in result

    def test_equals_leaves_symbol_slot_unquoted(self, compiler: Compiler) -> None:
        templates = {
            "user": TemplateDefinition(
                name="user",
                slots=[SlotDefinition(name="level", type=SlotType.SYMBOL)],
            )
        }
        rule = RuleDefinition(
            name="level-match",
            when=[
                FactPattern(
                    template="user",
                    conditions=[ConditionEntry(slot="level", expression="equals(secret)")],
                )
            ],
            then=ThenBlock(action="allow", reason="ok"),
        )
        result = compiler.compile_rule(rule, "governance", templates)
        assert "(user (level secret))" in result

    def test_log_level_reaches_the_decision_fact(self, compiler: Compiler) -> None:
        rule = RuleDefinition(
            name="quiet",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[ConditionEntry(slot="id", expression="equals(a)")],
                )
            ],
            then=ThenBlock(action="allow", reason="ok", log="none"),
        )
        assert "(log-level none)" in compiler.compile_rule(rule, "governance")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestScopeErrorHierarchy:
    def test_scope_error_is_a_fathom_error_and_a_runtime_error(self) -> None:
        assert issubclass(ScopeError, FathomError)
        assert issubclass(ScopeError, RuntimeError)

    def test_scope_error_is_caught_by_fathom_error(self) -> None:
        with pytest.raises(FathomError):
            raise ScopeError("wrong scope")
