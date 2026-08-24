"""Fathom -> Rego export.

Rego is the smaller language, so most of a real Fathom ruleset has no form
here at all: facts that persist, joins across facts, the temporal and
classification operators. The export is therefore mostly refusal, and the
tests are mostly about refusing for the right reason rather than emitting
Rego that parses and means something else.

Where OPA is installed, the generated policy is handed back to `opa parse`
and re-converted, which is the only check that proves the output is Rego and
not merely Rego-shaped.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from fathom.cli import app
from fathom.engine import Engine
from fathom.rego import convert_ast, export_engine, parse_rego

if TYPE_CHECKING:
    from fathom.rego import ExportResult

FIXTURES = Path(__file__).parent / "fixtures" / "rego"

_ONE_TEMPLATE = """
templates:
  - name: request
    slots:
      - name: role
        type: string
      - name: attempts
        type: integer
      - name: path
        type: string
      - name: flagged
        type: symbol
"""

_MODULE = "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"


def _pack(root: Path, rules_yaml: str, templates_yaml: str = _ONE_TEMPLATE) -> Engine:
    for kind, text in (
        ("templates", templates_yaml),
        ("modules", _MODULE),
        ("rules", rules_yaml),
    ):
        (root / kind).mkdir(parents=True, exist_ok=True)
        (root / kind / "r.yaml").write_text(text, encoding="utf-8")
    return Engine.from_rules(str(root))


def _rules(*rules: dict) -> str:
    return yaml.safe_dump(
        {"module": "gov", "ruleset": "gov", "rules": list(rules)}, sort_keys=False
    )


def _rule(name: str, conditions: list[dict], **then: object) -> dict:
    return {
        "name": name,
        "when": [{"template": "request", "conditions": conditions}],
        "then": {"action": "allow", "reason": "because", **then},
    }


def _export(tmp_path: Path, *rules: dict) -> ExportResult:
    return export_engine(_pack(tmp_path, _rules(*rules)))


def _converted_engine(tmp_path: Path, fixture: str) -> tuple[Engine, str]:
    """Load a Rego fixture through the converter, as a user migrating would."""
    result = convert_ast(json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8")))
    for kind, payload in (
        ("templates", {"templates": result.templates}),
        ("modules", {"modules": result.modules, "focus_order": [result.module]}),
        ("rules", {"module": result.module, "ruleset": result.module, "rules": result.rules}),
    ):
        (tmp_path / kind).mkdir(parents=True, exist_ok=True)
        (tmp_path / kind / "c.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
    return Engine.from_rules(str(tmp_path)), result.package


# ---------------------------------------------------------------------------
# The exportable subset
# ---------------------------------------------------------------------------


class TestOperators:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("equals(admin)", 'input.request.role == "admin"'),
            ("not_equals(admin)", 'input.request.role != "admin"'),
            ("in([admin, root])", 'input.request.role in {"admin", "root"}'),
            ("not_in([admin, root])", 'not input.request.role in {"admin", "root"}'),
            ("contains(adm)", 'contains(input.request.role, "adm")'),
            ("matches(^adm)", 'regex.match("^adm", input.request.role)'),
        ],
    )
    def test_string_operators(self, tmp_path: Path, expression: str, expected: str) -> None:
        result = _export(tmp_path, _rule("r", [{"slot": "role", "expression": expression}]))
        assert expected in result.source

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("greater_than(3)", "input.request.attempts > 3"),
            ("less_than(3)", "input.request.attempts < 3"),
            ("equals(3)", "input.request.attempts == 3"),
        ],
    )
    def test_numeric_literals_are_not_quoted(
        self, tmp_path: Path, expression: str, expected: str
    ) -> None:
        """The declared slot type decides, not the shape of the text."""
        result = _export(tmp_path, _rule("r", [{"slot": "attempts", "expression": expression}]))
        assert expected in result.source

    def test_a_numeric_looking_string_stays_a_string(self, tmp_path: Path) -> None:
        """`equals(5)` on a string slot is the string "5" in Fathom."""
        result = _export(tmp_path, _rule("r", [{"slot": "role", "expression": "equals(5)"}]))
        assert 'input.request.role == "5"' in result.source

    def test_symbol_true_and_false_go_back_to_rego_booleans(self, tmp_path: Path) -> None:
        """The inverse of what flatten_input does on the way in."""
        result = _export(tmp_path, _rule("r", [{"slot": "flagged", "expression": "equals(true)"}]))
        assert "input.request.flagged == true" in result.source

    def test_a_regex_containing_a_dollar_is_not_read_as_a_cross_reference(
        self, tmp_path: Path
    ) -> None:
        """`$alias.field` is a cross-fact reference; `foo$` is an end anchor."""
        result = _export(
            tmp_path, _rule("r", [{"slot": "path", "expression": r"matches(\.key$)"}])
        )
        assert result.skipped == []
        assert r"regex.match(\"\\\\.key$\"" in json.dumps(result.source)


class TestStructure:
    def test_the_action_becomes_the_document_name(self, tmp_path: Path) -> None:
        result = _export(
            tmp_path,
            _rule("a", [{"slot": "role", "expression": "equals(admin)"}]),
            _rule("d", [{"slot": "role", "expression": "equals(guest)"}], action="deny"),
        )
        assert "allow if {" in result.source
        assert "deny if {" in result.source
        assert "default allow := false" in result.source
        assert "default deny := false" in result.source

    def test_the_reason_survives_as_a_comment(self, tmp_path: Path) -> None:
        """Rego has nowhere to put a reason, and dropping it loses the why."""
        result = _export(tmp_path, _rule("r", [{"slot": "role", "expression": "equals(admin)"}]))
        assert "# because" in result.source
        assert "# fathom rule: r" in result.source

    def test_conditions_become_one_line_each(self, tmp_path: Path) -> None:
        result = _export(
            tmp_path,
            _rule(
                "r",
                [
                    {"slot": "role", "expression": "equals(admin)"},
                    {"slot": "attempts", "expression": "less_than(3)"},
                ],
            ),
        )
        body = result.source.split("allow if {")[1].split("}")[0]
        assert [line.strip() for line in body.strip().splitlines()] == [
            'input.request.role == "admin"',
            "input.request.attempts < 3",
        ]

    def test_the_package_defaults_to_the_module(self, tmp_path: Path) -> None:
        assert (
            _export(tmp_path, _rule("r", [{"slot": "role", "expression": "equals(a)"}])).package
            == "gov"
        )

    def test_an_explicit_package_wins(self, tmp_path: Path) -> None:
        engine = _pack(tmp_path, _rules(_rule("r", [{"slot": "role", "expression": "equals(a)"}])))
        assert export_engine(engine, package="authz.basic").package == "authz.basic"


class TestSlotAddressing:
    def test_a_single_input_template_addresses_slots_at_the_document_root(
        self, tmp_path: Path
    ) -> None:
        """The shape `fathom convert rego` produces, so a policy round-trips."""
        engine, _ = _converted_engine(tmp_path, "basic")
        source = export_engine(engine).source
        assert "input.user_role" in source
        assert "input.input." not in source

    def test_other_templates_keep_their_name_in_the_path(self, tmp_path: Path) -> None:
        """Two rules over different templates can never match the same fact;
        collapsing them onto one root would say they can."""
        result = _export(tmp_path, _rule("r", [{"slot": "role", "expression": "equals(admin)"}]))
        assert "input.request.role" in result.source
        assert "matches more than one fact template" in result.source


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    def _reason(self, result: ExportResult) -> str:
        return " ".join(s.reason for s in result.skipped)

    def test_a_cross_fact_join(self, tmp_path: Path) -> None:
        rule = _rule("r", [{"slot": "role", "expression": "equals(admin)"}])
        rule["when"].append({"template": "request", "conditions": []})
        result = _export(tmp_path, rule)
        assert result.rule_count == 0
        assert "joins across facts" in self._reason(result)

    def test_a_rule_that_asserts_facts(self, tmp_path: Path) -> None:
        result = _export(
            tmp_path,
            _rule(
                "r",
                [{"slot": "role", "expression": "equals(admin)"}],
                **{"assert": [{"template": "request", "slots": {"role": "x"}}]},
            ),
        )
        assert "cannot add to working memory" in self._reason(result)

    def test_an_assert_only_rule_with_no_decision(self, tmp_path: Path) -> None:
        rule = _rule("r", [{"slot": "role", "expression": "equals(admin)"}])
        rule["then"] = {
            "reason": "note",
            "assert": [{"template": "request", "slots": {"role": "x"}}],
        }
        assert "cannot add to working memory" in self._reason(_export(tmp_path, rule))

    def test_a_temporal_operator_says_which_family_it_is_in(self, tmp_path: Path) -> None:
        result = _export(
            tmp_path, _rule("r", [{"slot": "role", "expression": "changed_within(60)"}])
        )
        assert "no memory of the last one" in self._reason(result)

    def test_a_raw_clips_test(self, tmp_path: Path) -> None:
        rule = _rule("r", [{"slot": "role", "expression": "equals(admin)"}])
        rule["when"][0]["conditions"].append({"test": "(> 1 0)"})
        assert "raw CLIPS" in self._reason(_export(tmp_path, rule))

    def test_a_bind(self, tmp_path: Path) -> None:
        rule = _rule("r", [{"slot": "role", "expression": "equals(admin)"}])
        rule["when"][0]["conditions"].append({"slot": "path", "bind": "?p"})
        assert "which is a join" in self._reason(_export(tmp_path, rule))

    def test_a_scope_decision(self, tmp_path: Path) -> None:
        result = _export(
            tmp_path,
            _rule(
                "r",
                [{"slot": "role", "expression": "equals(admin)"}],
                action="scope",
                scope="read-only",
            ),
        )
        assert "nowhere to put it" in self._reason(result)

    def test_a_refused_rule_is_not_in_the_output(self, tmp_path: Path) -> None:
        """The failure that matters: a refusal that still emits something."""
        rule = _rule("dropped", [{"slot": "role", "expression": "changed_within(60)"}])
        result = _export(
            tmp_path, rule, _rule("kept", [{"slot": "role", "expression": "equals(admin)"}])
        )
        assert "dropped" not in result.source
        assert "kept" in result.source


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class TestNotes:
    def test_defining_both_allow_and_deny_warns_about_precedence(self, tmp_path: Path) -> None:
        """Fathom picks one decision; Rego evaluates both documents."""
        result = _export(
            tmp_path,
            _rule("a", [{"slot": "role", "expression": "equals(admin)"}]),
            _rule("d", [{"slot": "role", "expression": "equals(guest)"}], action="deny"),
        )
        assert any("precedence" in note for note in result.notes)

    def test_salience_is_flagged_as_lost(self, tmp_path: Path) -> None:
        a = _rule("a", [{"slot": "role", "expression": "equals(admin)"}])
        b = _rule("b", [{"slot": "role", "expression": "equals(guest)"}])
        b["salience"] = 50
        result = _export(tmp_path, a, b)
        assert any("Salience is not exported" in note for note in result.notes)

    def test_one_salience_needs_no_warning(self, tmp_path: Path) -> None:
        result = _export(tmp_path, _rule("r", [{"slot": "role", "expression": "equals(a)"}]))
        assert not any("Salience" in note for note in result.notes)


# ---------------------------------------------------------------------------
# The output is really Rego
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
class TestAgainstOpa:
    @pytest.mark.parametrize("fixture", ["basic", "numeric", "strings_and_sets"])
    def test_the_export_parses_as_rego(self, tmp_path: Path, fixture: str) -> None:
        engine, package = _converted_engine(tmp_path, fixture)
        source = export_engine(engine, package=package).source
        parse_rego(source, filename=f"{fixture}-export.rego")

    @pytest.mark.parametrize("fixture", ["basic", "numeric", "strings_and_sets"])
    def test_a_rego_policy_survives_the_round_trip(self, tmp_path: Path, fixture: str) -> None:
        """Rego -> Fathom -> Rego -> Fathom must land on the same rules."""
        engine, package = _converted_engine(tmp_path, fixture)
        exported = export_engine(engine, package=package)
        reconverted = convert_ast(parse_rego(exported.source, filename="round-trip.rego"))
        assert reconverted.package == package
        assert [r["name"] for r in reconverted.rules] == sorted(
            r["name"] for r in reconverted.rules
        )
        original = {
            (rule.when[0].template, tuple(c.expression for c in rule.when[0].conditions))
            for rule in engine.rule_registry.values()
        }
        round_tripped = {
            ("input", tuple(c["expression"] for c in rule["when"][0]["conditions"]))
            for rule in reconverted.rules
        }
        assert round_tripped == original


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_prints_the_policy(self, tmp_path: Path) -> None:
        _pack(tmp_path, _rules(_rule("r", [{"slot": "role", "expression": "equals(admin)"}])))
        result = CliRunner(mix_stderr=False).invoke(app, ["convert", "to-rego", str(tmp_path)])
        assert result.exit_code == 0
        assert "package gov" in result.stdout

    def test_writes_a_file(self, tmp_path: Path) -> None:
        pack = tmp_path / "pack"
        _pack(pack, _rules(_rule("r", [{"slot": "role", "expression": "equals(admin)"}])))
        out = tmp_path / "policy.rego"
        result = CliRunner(mix_stderr=False).invoke(
            app, ["convert", "to-rego", str(pack), "-o", str(out), "--package", "authz.x"]
        )
        assert result.exit_code == 0
        assert "package authz.x" in out.read_text(encoding="utf-8")

    def test_a_ruleset_with_nothing_exportable_exits_nonzero(self, tmp_path: Path) -> None:
        _pack(tmp_path, _rules(_rule("r", [{"slot": "role", "expression": "changed_within(60)"}])))
        result = CliRunner(mix_stderr=False).invoke(app, ["convert", "to-rego", str(tmp_path)])
        assert result.exit_code != 0

    def test_repeated_refusals_are_grouped_not_repeated(self, tmp_path: Path) -> None:
        """A join-heavy ruleset refuses every rule for one reason; printing it
        once per rule buries anything refused for a different one."""
        rules = []
        for index in range(5):
            rule = _rule(f"r{index}", [{"slot": "role", "expression": "equals(admin)"}])
            rule["when"].append({"template": "request", "conditions": []})
            rules.append(rule)
        rules.append(_rule("ok", [{"slot": "role", "expression": "equals(admin)"}]))
        _pack(tmp_path, _rules(*rules))
        result = CliRunner(mix_stderr=False).invoke(app, ["convert", "to-rego", str(tmp_path)])
        assert result.stderr.count("export skipped") == 1
        assert "+2 more" in result.stderr

    def test_strict_fails_on_a_partial_export(self, tmp_path: Path) -> None:
        _pack(
            tmp_path,
            _rules(
                _rule("kept", [{"slot": "role", "expression": "equals(admin)"}]),
                _rule("dropped", [{"slot": "role", "expression": "changed_within(60)"}]),
            ),
        )
        runner = CliRunner(mix_stderr=False)
        assert runner.invoke(app, ["convert", "to-rego", str(tmp_path)]).exit_code == 0
        assert runner.invoke(app, ["convert", "to-rego", str(tmp_path), "--strict"]).exit_code != 0

    def test_a_missing_directory_is_rejected(self, tmp_path: Path) -> None:
        result = CliRunner(mix_stderr=False).invoke(
            app, ["convert", "to-rego", str(tmp_path / "nope")]
        )
        assert result.exit_code != 0
