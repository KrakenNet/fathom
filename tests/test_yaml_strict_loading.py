"""Strict YAML loading: a typo in a policy file must fail the load.

Each case here used to load silently and change what the policy decides:
a rule pattern on a misspelled template that can never match, an unknown
top-level key that drops ``focus_order``, a duplicate mapping key that
keeps the last value, and a ``hierarchies:`` block that was never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from fathom.cli import app
from fathom.engine import Engine
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES = """\
templates:
  - name: req
    slots:
      - {name: role, type: symbol}
"""
MODULES = "modules:\n  - name: m\n"
RULES = """\
ruleset: rs
module: m
rules:
  - name: allow_admin
    when:
      - template: req
        conditions:
          - {slot: role, expression: equals(admin)}
    then: {action: allow}
"""
TYPO_TEMPLATE_RULES = """\
ruleset: rs
module: m
rules:
  - name: deny_alert
    when:
      - template: req
        conditions: []
      - template: alertt
        conditions:
          - test: (eq 1 1)
    then: {action: deny}
"""
DUP_KEY_RULES = """\
ruleset: rs
module: m
rules:
  - name: deny_non_admin
    when:
      - template: req
        conditions:
          - slot: role
            expression: not_equals(admin)
            expression: equals(admin)
    then: {action: deny}
"""


def _pack(root: Path, rules: str = RULES, **overrides: str) -> Path:
    files = {"templates": TEMPLATES, "modules": MODULES, "rules": rules, **overrides}
    for kind, text in files.items():
        (root / kind).mkdir(parents=True, exist_ok=True)
        (root / kind / "a.yaml").write_text(text)
    return root


# --- 1. rule pattern on an unregistered template --------------------------


def test_bare_pattern_on_unregistered_template_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CompilationError, match="'alertt', which is not registered"):
        Engine.from_rules(str(_pack(tmp_path, TYPO_TEMPLATE_RULES)))


def test_reload_rules_rejects_unregistered_template(tmp_path: Path) -> None:
    engine = Engine.from_rules(str(_pack(tmp_path)))
    with pytest.raises(CompilationError, match="'alertt', which is not registered"):
        engine.reload_rules(TYPO_TEMPLATE_RULES.encode())


def test_validate_rejects_unregistered_template(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path, TYPO_TEMPLATE_RULES))])
    assert result.exit_code != 0
    assert "alertt" in result.output


def test_validate_single_rule_file_uses_sibling_templates(tmp_path: Path) -> None:
    pack = _pack(tmp_path, TYPO_TEMPLATE_RULES)
    result = CliRunner().invoke(app, ["validate", str(pack / "rules" / "a.yaml")])
    assert result.exit_code != 0
    assert "alertt" in result.output


def test_validate_accepts_registered_templates(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path))])
    assert result.exit_code == 0, result.output
