"""Regression tests for ``validate_document`` on the canonical file shapes.

Before the 1.0 audit fix, ``validate_document`` dispatched on shapes the
compiler never produces, so every canonical templates/modules/rules file fell
through and validated clean even when it failed to compile.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest
import yaml

from fathom.compiler import Compiler
from fathom.errors import CompilationError
from fathom.yaml_utils import validate_document

if TYPE_CHECKING:
    from pathlib import Path


def _doc(text: str) -> dict:
    return yaml.safe_load(textwrap.dedent(text))


class TestCanonicalTemplateFiles:
    def test_valid_template_file_has_no_errors(self, tmp_path: Path) -> None:
        data = _doc("""\
            templates:
              - name: agent
                slots:
                  - name: level
                    type: symbol
        """)
        assert validate_document(data, tmp_path / "templates.yaml") == []

    def test_invalid_template_name_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            templates:
              - name: bad name with spaces!!
                slots:
                  - name: level
                    type: symbol
        """)
        errors = validate_document(data, tmp_path / "templates.yaml")
        assert errors
        assert "templates -> 0 -> name" in errors[0]

    def test_unknown_slot_type_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            templates:
              - name: agent
                slots:
                  - name: level
                    type: bogus
        """)
        assert validate_document(data, tmp_path / "templates.yaml")

    def test_templates_must_be_a_list(self, tmp_path: Path) -> None:
        errors = validate_document({"templates": {"name": "agent"}}, tmp_path / "t.yaml")
        assert errors == [f"{tmp_path / 't.yaml'}: 'templates' must be a list"]


class TestCanonicalModuleFiles:
    def test_valid_module_file_has_no_errors(self, tmp_path: Path) -> None:
        data = _doc("""\
            modules:
              - name: governance
            focus_order: [governance]
        """)
        assert validate_document(data, tmp_path / "modules.yaml") == []

    def test_invalid_module_name_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            modules:
              - name: '!!!invalid'
        """)
        errors = validate_document(data, tmp_path / "modules.yaml")
        assert errors
        assert "modules -> 0 -> name" in errors[0]

    def test_focus_order_must_be_a_list(self, tmp_path: Path) -> None:
        data = _doc("""\
            modules:
              - name: governance
            focus_order: governance
        """)
        errors = validate_document(data, tmp_path / "modules.yaml")
        assert errors == [f"{tmp_path / 'modules.yaml'}: 'focus_order' must be a list"]


class TestCanonicalRuleFiles:
    def test_valid_rule_file_has_no_errors(self, tmp_path: Path) -> None:
        data = _doc("""\
            module: governance
            rules:
              - name: allow-all
                when:
                  - template: agent
                    conditions:
                      - slot: level
                        expression: "equals(secret)"
                then:
                  action: allow
                  reason: ok
        """)
        assert validate_document(data, tmp_path / "rules.yaml") == []

    def test_invalid_ruleset_name_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            ruleset: 'not a ruleset!!'
            module: governance
            rules:
              - name: allow-all
                when:
                  - template: agent
                    conditions:
                      - slot: level
                        expression: "equals(secret)"
                then:
                  action: allow
                  reason: ok
        """)
        assert validate_document(data, tmp_path / "rules.yaml")

    def test_misspelled_salience_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            module: governance
            rules:
              - name: deny-all
                saliance: 100
                when:
                  - template: agent
                    conditions:
                      - slot: level
                        expression: "equals(secret)"
                then:
                  action: deny
                  reason: nope
        """)
        errors = validate_document(data, tmp_path / "rules.yaml")
        assert errors
        assert "saliance" in errors[0]

    def test_empty_when_mapping_is_reported(self, tmp_path: Path) -> None:
        """`when: {}` is a pydantic type error — the easy half."""
        data = _doc("""\
            module: governance
            rules:
              - name: broken
                when: {}
                then:
                  action: allow
                  reason: ok
        """)
        assert validate_document(data, tmp_path / "rules.yaml")


class TestValidateMatchesTheLoader:
    """`fathom validate` must not pass files `Engine.from_rules` rejects.

    Re-deriving the shape from the pydantic models alone missed every check
    that lives outside them, so `validate` exited 0 on rulesets that fail to
    load — worse than no validation, because it tells an author the ruleset
    is fine.
    """

    def test_empty_when_list_is_reported(self, tmp_path: Path) -> None:
        """`when: []` satisfies pydantic; only `compile_rule` rejects it."""
        data = _doc("""\
            module: governance
            rules:
              - name: broken
                when: []
                then:
                  action: deny
                  reason: nope
        """)
        errors = validate_document(data, tmp_path / "rules.yaml")
        assert errors
        assert "no conditions" in errors[0]

    def test_unknown_operator_is_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            module: governance
            rules:
              - name: broken
                when:
                  - template: agent
                    conditions:
                      - slot: id
                        expression: "bogusop(a)"
                then:
                  action: deny
                  reason: nope
        """)
        errors = validate_document(data, tmp_path / "rules.yaml")
        assert errors
        assert "unsupported condition operator" in errors[0]

    def test_missing_module_key_is_reported(self, tmp_path: Path) -> None:
        """A rule file with no `module:` matched no branch and returned []."""
        data = _doc("""\
            rules:
              - name: r
                when:
                  - template: agent
                    conditions:
                      - slot: id
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: nope
        """)
        errors = validate_document(data, tmp_path / "rules.yaml")
        assert errors
        assert "module" in errors[0]

    def test_duplicate_rule_names_are_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            module: governance
            rules:
              - name: r
                when:
                  - template: agent
                    conditions:
                      - slot: id
                        expression: "equals(a)"
                then:
                  action: deny
                  reason: nope
              - name: r
                when:
                  - template: agent
                    conditions:
                      - slot: id
                        expression: "equals(b)"
                then:
                  action: deny
                  reason: nope
        """)
        errors = validate_document(data, tmp_path / "rules.yaml")
        assert errors
        assert "duplicate rule name" in errors[0]

    @pytest.mark.parametrize(
        "ruleset",
        [
            "examples/01-hello-allow-deny",
            "examples/02-rbac-modules",
            "examples/03-classification-blp",
            "examples/04-temporal-anomaly",
            "examples/05-langchain-guardrails",
        ],
    )
    def test_shipped_rulesets_still_validate_clean(self, ruleset: str) -> None:
        """The stricter check must not produce false positives on real packs."""
        import pathlib

        import yaml

        root = pathlib.Path(ruleset)
        for yaml_file in sorted(root.rglob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            assert validate_document(data, yaml_file) == [], yaml_file


class TestOtherCanonicalFiles:
    def test_function_file_errors_are_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            functions:
              - name: 'bad name'
                params: [a, b]
                hierarchy_ref: classification.yaml
        """)
        errors = validate_document(data, tmp_path / "functions.yaml")
        assert errors
        assert "functions -> 0 -> name" in errors[0]

    def test_hierarchy_file_errors_are_reported(self, tmp_path: Path) -> None:
        data = _doc("""\
            name: clearance
            levels:
              - 'low then (system "boom")) (case zzz'
              - high
        """)
        assert validate_document(data, tmp_path / "clearance.yaml")

    def test_valid_hierarchy_file_has_no_errors(self, tmp_path: Path) -> None:
        data = _doc("""\
            name: clearance
            levels: [low, high]
        """)
        assert validate_document(data, tmp_path / "clearance.yaml") == []


class TestValidationAgreesWithTheCompiler:
    """Every file the compiler rejects must also be rejected by validation."""

    @pytest.mark.parametrize(
        "filename,body",
        [
            (
                "templates.yaml",
                "templates:\n  - name: bad name with spaces!!\n"
                "    slots:\n      - name: x\n        type: string\n",
            ),
            ("modules.yaml", "modules:\n  - name: '!!!invalid'\n"),
            (
                "rules.yaml",
                "ruleset: 'not a ruleset!!'\nmodule: governance\nrules:\n"
                "  - name: r\n    when:\n      - template: agent\n"
                '        conditions:\n          - slot: x\n            expression: "equals(a)"\n'
                "    then:\n      action: allow\n      reason: ok\n",
            ),
        ],
    )
    def test_compiler_failure_is_a_validation_failure(
        self, tmp_path: Path, filename: str, body: str
    ) -> None:
        path = tmp_path / filename
        path.write_text(body)
        compiler = Compiler()
        parse = {
            "templates.yaml": compiler.parse_template_file,
            "modules.yaml": compiler.parse_module_file,
            "rules.yaml": compiler.parse_rule_file,
        }[filename]

        with pytest.raises(CompilationError):
            parse(path)

        assert validate_document(yaml.safe_load(body), path)
