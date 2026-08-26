"""End-to-end cover for literals emitted in a slot's declared CLIPS type.

CLIPS is type-strict in the two places that decide whether a rule fires:
a literal restriction on the LHS, and a literal slot value in an ``assert``
on the RHS. It holds a symbol and a string to be unequal, and an integer and
a float to be unequal, so a literal emitted in the wrong type does not error
— it quietly decides every fact the wrong way.

These tests run a real :class:`Engine` because that is the only place the
mismatch is visible. Inspecting the generated CLIPS text cannot tell a
correct literal from an incorrect one; only CLIPS's own matcher can.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES_YAML = """
templates:
  - name: request
    slots:
      - name: level_str
        type: string
        required: true
      - name: level_sym
        type: symbol
        required: true
      - name: score
        type: float
        required: true
      - name: count
        type: integer
        required: true
  - name: alarm
    slots:
      - name: level
        type: symbol
        required: true
      - name: score
        type: integer
        required: true
      - name: note
        type: string
        default: ""
"""

MODULES_YAML = """
modules:
  - name: main
focus_order:
  - main
"""

HIERARCHY_YAML = """
name: clearance
levels: [unclassified, cui, confidential, secret, top-secret]
"""

FUNCTIONS_YAML = """
functions:
  - name: clearance
    type: classification
    params: [a, b]
    hierarchy_ref: clearance.yaml
"""


def _pack(tmp_path: Path, rules_yaml: str) -> str:
    """Write a rule pack carrying *rules_yaml* and return its directory."""
    for subdir, name, content in (
        ("templates", "templates.yaml", TEMPLATES_YAML),
        ("modules", "modules.yaml", MODULES_YAML),
        ("hierarchies", "clearance.yaml", HIERARCHY_YAML),
        ("functions", "functions.yaml", FUNCTIONS_YAML),
        ("rules", "rules.yaml", rules_yaml),
    ):
        (tmp_path / subdir).mkdir(exist_ok=True)
        (tmp_path / subdir / name).write_text(content)
    return str(tmp_path)


def _decide(pack: str, **slots: object) -> str:
    """Evaluate one ``request`` fact and return the decision."""
    engine = Engine.from_rules(pack, default_decision="allow")
    facts = {"level_str": "cui", "level_sym": "cui", "score": 0.0, "count": 0}
    facts.update(slots)
    return engine.evaluate_once([("request", facts)]).decision


# ---------------------------------------------------------------------------
# Classification operators against a string slot
# ---------------------------------------------------------------------------


CLASSIFICATION_RULES = """
module: main
ruleset: typing
version: "1.0"
rules:
  - name: deny-cleared-string
    salience: 10
    when:
      - template: request
        conditions:
          - slot: level_str
            expression: "meets_or_exceeds(secret)"
    then:
      action: deny
      reason: "string slot at or above secret"
  - name: deny-cleared-symbol
    salience: 10
    when:
      - template: request
        conditions:
          - slot: level_sym
            expression: "meets_or_exceeds(secret)"
    then:
      action: deny
      reason: "symbol slot at or above secret"
"""


@pytest.mark.parametrize("slot", ["level_str", "level_sym"])
def test_classification_ranks_both_slot_types(tmp_path: Path, slot: str) -> None:
    """``meets_or_exceeds`` must rank a string slot as it ranks a symbol slot.

    The rank deffunction switched on the raw slot value against unquoted
    case labels. CLIPS ``switch`` compares with ``eq``, so every string slot
    fell to the ``-1`` default, ``meets_or_exceeds`` was always false, and
    the deny rule silently never fired.
    """
    pack = _pack(tmp_path, CLASSIFICATION_RULES)

    assert _decide(pack, **{slot: "top-secret"}) == "deny"
    assert _decide(pack, **{slot: "secret"}) == "deny"
    assert _decide(pack, **{slot: "cui"}) == "allow"


# ---------------------------------------------------------------------------
# Numeric literals against float and integer slots
# ---------------------------------------------------------------------------


NUMERIC_RULES = """
module: main
ruleset: typing
version: "1.0"
rules:
  - name: float-equals-integer-literal
    salience: 10
    when:
      - template: request
        conditions:
          - slot: score
            expression: "equals(5)"
    then:
      action: deny
      reason: "score is 5"
  - name: float-in-integer-list
    salience: 20
    when:
      - template: request
        conditions:
          - slot: score
            expression: "in([1, 2, 9])"
    then:
      action: route
      reason: "score is listed"
  - name: integer-equals-float-literal
    salience: 30
    when:
      - template: request
        conditions:
          - slot: count
            expression: "equals(3.0)"
    then:
      action: escalate
      reason: "count is 3"
  - name: float-not-equals-integer-literal
    salience: 40
    when:
      - template: request
        conditions:
          - slot: score
            expression: "not_equals(7)"
    then:
      action: scope
      reason: "score is not 7"
"""


def test_integer_literal_matches_a_float_slot(tmp_path: Path) -> None:
    """``equals(5)`` on a float slot used to fail the CLIPS build outright."""
    pack = _pack(tmp_path, NUMERIC_RULES)

    assert _decide(pack, score=5.0) == "deny"


def test_integer_list_matches_a_float_slot(tmp_path: Path) -> None:
    """``in([...])`` compiles to type-strict ``eq``; the items need the slot type."""
    pack = _pack(tmp_path, NUMERIC_RULES)

    assert _decide(pack, score=2.0) == "route"


def test_float_literal_matches_an_integer_slot(tmp_path: Path) -> None:
    """An integral float literal narrows to the integer the slot declares."""
    pack = _pack(tmp_path, NUMERIC_RULES)

    assert _decide(pack, score=100.0, count=3) == "escalate"


def test_not_equals_on_a_float_slot_is_not_always_true(tmp_path: Path) -> None:
    """``not_equals(7)`` used to match 7.0 too — ``neq`` is type-strict."""
    pack = _pack(tmp_path, NUMERIC_RULES)

    assert _decide(pack, score=7.0) == "allow"
    assert _decide(pack, score=8.0) == "scope"


# ---------------------------------------------------------------------------
# then.assert slot values
# ---------------------------------------------------------------------------


ASSERT_RULES = """
module: main
ruleset: typing
version: "1.0"
rules:
  - name: raise-alarm
    salience: 10
    when:
      - template: request
        conditions:
          - slot: level_sym
            expression: "equals(cui)"
    then:
      action: deny
      reason: "tripped"
      assert:
        - template: alarm
          slots:
            level: high
            score: "7"
            note: hello world
"""


def test_assert_emits_each_slot_in_its_declared_type(tmp_path: Path) -> None:
    """``then.assert`` used to quote every value, so any non-string slot failed.

    A quoted literal against a ``symbol`` or ``integer`` slot is a CLIPS
    build error, which meant ``then.assert`` only ever worked when every
    target slot happened to be a string.
    """
    pack = _pack(tmp_path, ASSERT_RULES)
    engine = Engine.from_rules(pack, default_decision="allow")

    result = engine.evaluate_once(
        [("request", {"level_str": "cui", "level_sym": "cui", "score": 0.0, "count": 0})]
    )

    assert result.decision == "deny"
    assert engine.query("alarm") == [{"level": "high", "score": 7, "note": "hello world"}]
