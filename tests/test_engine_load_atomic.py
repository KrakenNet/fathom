"""A failed ``load_rules`` leaves no rule from that call behind.

A file whose second rule fails to build used to leave the first rule built
and registered. An embedder that caught the error and kept serving then ran
half the policy: the allow without the deny that was meant to outrank it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from pathlib import Path

_RULES = """
ruleset: rs
module: m
rules:
  - name: allow_admin
    when:
      - template: req
        conditions:
          - {slot: role, expression: equals(admin)}
    then: {action: allow}
  - name: deny_big
    salience: -10
    when:
      - template: req
        conditions:
          - {slot: amount, expression: greater_than(oops)}
    then: {action: deny}
"""


def test_a_failed_load_leaves_no_rule_behind(tmp_path: Path) -> None:
    (tmp_path / "t.yaml").write_text(
        "templates:\n  - name: req\n    slots:\n"
        "      - {name: role, type: symbol}\n      - {name: amount, type: integer}\n"
    )
    (tmp_path / "m.yaml").write_text("modules:\n  - name: m\n")
    (tmp_path / "r.yaml").write_text(_RULES)
    engine = Engine()
    engine.load_templates(str(tmp_path / "t.yaml"))
    engine.load_modules(str(tmp_path / "m.yaml"))

    with pytest.raises(CompilationError):
        engine.load_rules(str(tmp_path / "r.yaml"))

    assert dict(engine.rule_registry) == {}
    result = engine.evaluate_once([("req", {"role": "admin", "amount": 5})])
    assert result.decision != "allow"
    assert result.rule_trace == []
