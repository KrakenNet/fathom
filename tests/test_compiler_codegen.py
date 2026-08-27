"""End-to-end cover for CLIPS shapes the compiler used to emit incorrectly.

Each case here is a rule an author can reasonably write that either failed
the CLIPS build outright or, worse, compiled to something that matched the
wrong facts. All of them run through a real :class:`Engine`: the generated
text looked plausible in every one, so only CLIPS itself could tell.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES_YAML = """
templates:
  - name: metric
    slots:
      - name: score
        type: float
        required: true
      - name: label
        type: symbol
        required: true
  - name: subject
    slots:
      - name: name
        type: symbol
        required: true
      - name: level
        type: symbol
        required: true
  - name: resource
    slots:
      - name: level
        type: symbol
        required: true
  - name: event
    slots:
      - name: action
        type: symbol
        required: true
      - name: ts
        type: float
        default: 0.0
  - name: probe
    slots:
      - name: id
        type: symbol
        required: true
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


# ---------------------------------------------------------------------------
# One-member in([...]) — CLIPS `or` needs two arguments
# ---------------------------------------------------------------------------


SINGLE_MEMBER_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: single-member-in
    salience: 10
    when:
      - template: metric
        conditions:
          - slot: label
            expression: "in([alpha])"
    then:
      action: deny
      reason: "label is alpha"
"""


def test_single_member_in_list_compiles_and_matches(tmp_path: Path) -> None:
    """``in([x])`` emitted ``(or (eq ...))``, and CLIPS `or` needs two args."""
    engine = Engine.from_rules(_pack(tmp_path, SINGLE_MEMBER_RULES), default_decision="allow")

    matched = engine.evaluate_once([("metric", {"score": 0.0, "label": "alpha"})])
    other = engine.evaluate_once([("metric", {"score": 0.0, "label": "beta"})])

    assert matched.decision == "deny"
    assert other.decision == "allow"


# ---------------------------------------------------------------------------
# bind: alongside an operator that emits its own variable
# ---------------------------------------------------------------------------


BIND_CLASSIFICATION_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: bind-with-classification
    salience: 10
    when:
      - template: subject
        alias: $s
        conditions:
          - slot: level
            bind: "?lvl"
            expression: "meets_or_exceeds(secret)"
    then:
      action: deny
      reason: "cleared to {lvl}"
"""


def test_bind_rewrites_the_test_ce_it_shares_a_variable_with(tmp_path: Path) -> None:
    """A bind on a classification condition left the test CE unbound.

    Classification and temporal operators bind the slot to their own
    variable and reference it from a ``(test ...)``. Injecting the author's
    bind renamed it in the pattern only, so CLIPS rejected the rule with
    ``ANALYSIS4 ... referenced before being defined``.
    """
    engine = Engine.from_rules(
        _pack(tmp_path, BIND_CLASSIFICATION_RULES), default_decision="allow"
    )

    cleared = engine.evaluate_once([("subject", {"name": "u", "level": "top-secret"})])
    uncleared = engine.evaluate_once([("subject", {"name": "u", "level": "cui"})])

    assert cleared.decision == "deny"
    assert cleared.reason == "cleared to top-secret"
    assert uncleared.decision == "allow"


BIND_CROSSREF_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: bind-with-crossref
    salience: 10
    when:
      - template: subject
        alias: $s
        conditions:
          - slot: level
            expression: "equals(secret)"
      - template: resource
        conditions:
          - slot: level
            bind: "?rlvl"
            expression: "equals($s.level)"
    then:
      action: deny
      reason: "levels match at {rlvl}"
"""


def test_bind_does_not_delete_a_cross_fact_join(tmp_path: Path) -> None:
    """A bind used to overwrite the join variable, so the rule matched everything.

    ``equals($s.level)`` compiles the slot down to the *other* pattern's join
    variable. Renaming that to the author's bind removed the only thing
    tying the two patterns together — the rule then fired on every pair.
    """
    engine = Engine.from_rules(_pack(tmp_path, BIND_CROSSREF_RULES), default_decision="allow")

    matching = engine.evaluate_once(
        [("subject", {"name": "u", "level": "secret"}), ("resource", {"level": "secret"})]
    )
    mismatched = engine.evaluate_once(
        [("subject", {"name": "u", "level": "secret"}), ("resource", {"level": "cui"})]
    )

    assert matching.decision == "deny"
    assert mismatched.decision == "allow"


# ---------------------------------------------------------------------------
# Two conditions on one slot
# ---------------------------------------------------------------------------


RANGE_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: band
    salience: 10
    when:
      - template: metric
        conditions:
          - slot: score
            expression: "greater_than(5)"
          - slot: score
            expression: "less_than(10)"
    then:
      action: deny
      reason: "score in band"
"""


def test_two_conditions_on_one_slot_become_one_constraint(tmp_path: Path) -> None:
    """A range check named the slot twice, which CLIPS rejects outright."""
    engine = Engine.from_rules(_pack(tmp_path, RANGE_RULES), default_decision="allow")

    assert engine.evaluate_once([("metric", {"score": 7.0, "label": "a"})]).decision == "deny"
    assert engine.evaluate_once([("metric", {"score": 1.0, "label": "a"})]).decision == "allow"
    assert engine.evaluate_once([("metric", {"score": 20.0, "label": "a"})]).decision == "allow"


RANGE_WITH_BIND_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: band-with-bind
    salience: 10
    when:
      - template: metric
        conditions:
          - slot: score
            expression: "greater_than(5)"
          - slot: score
            bind: "?sc"
            expression: "less_than(10)"
    then:
      action: deny
      reason: "score {sc} in band"
"""


def test_merged_slot_constraint_keeps_the_authors_bind(tmp_path: Path) -> None:
    """The merged constraint binds the author's name, not a generated one."""
    engine = Engine.from_rules(_pack(tmp_path, RANGE_WITH_BIND_RULES), default_decision="allow")

    result = engine.evaluate_once([("metric", {"score": 7.0, "label": "a"})])

    assert result.decision == "deny"
    assert result.reason == "score 7.0 in band"


MIXED_MERGE_RULES = """
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: mid-clearance
    salience: 10
    when:
      - template: subject
        conditions:
          - slot: level
            expression: "meets_or_exceeds(cui)"
          - slot: level
            expression: "not_equals(top-secret)"
    then:
      action: deny
      reason: "mid clearance"
"""


def test_merge_joins_a_test_ce_operator_with_a_literal_one(tmp_path: Path) -> None:
    """Merging must carry the classification test CE onto the shared variable."""
    engine = Engine.from_rules(_pack(tmp_path, MIXED_MERGE_RULES), default_decision="allow")

    assert engine.evaluate_once([("subject", {"name": "u", "level": "secret"})]).decision == "deny"
    assert (
        engine.evaluate_once([("subject", {"name": "u", "level": "top-secret"})]).decision
        == "allow"
    )
    assert (
        engine.evaluate_once([("subject", {"name": "u", "level": "unclassified"})]).decision
        == "allow"
    )


# ---------------------------------------------------------------------------
# sequence_detected — a JSON argument full of commas
# ---------------------------------------------------------------------------


def _sequence_rules() -> str:
    """A rule using ``sequence_detected`` with a real JSON event list."""
    events = json.dumps(
        [
            {"template": "event", "slot": "action", "value": "login"},
            {"template": "event", "slot": "action", "value": "escalate"},
            {"template": "event", "slot": "action", "value": "download"},
        ]
    )
    return f"""
module: main
ruleset: codegen
version: "1.0"
rules:
  - name: detect-sequence
    salience: 10
    when:
      - template: probe
        conditions:
          - slot: id
            expression: 'sequence_detected({events}, 60)'
    then:
      action: deny
      reason: "sequence detected"
"""


def _run_sequence(tmp_path: Path, actions: list[str]) -> str:
    """Assert *actions* one second apart, then evaluate the probe."""
    engine = Engine.from_rules(_pack(tmp_path, _sequence_rules()), default_decision="allow")
    now = time.time()
    for index, action in enumerate(actions):
        engine.assert_fact("event", {"action": action, "ts": now - len(actions) + index})
    return engine.evaluate_once([("probe", {"id": "p"})]).decision


def test_sequence_detected_accepts_a_json_argument(tmp_path: Path) -> None:
    """Arguments were split on every comma, so the JSON list was shredded.

    ``sequence_detected`` was only ever exercised as a raw CLIPS function in
    the test suite; from YAML — its only documented use — it could not
    compile at all.
    """
    assert _run_sequence(tmp_path, ["login", "escalate", "download"]) == "deny"


def test_sequence_detected_still_rejects_the_wrong_order(tmp_path: Path) -> None:
    """Parsing the JSON correctly must not turn the operator into a tautology."""
    assert _run_sequence(tmp_path, ["login", "download", "escalate"]) == "allow"
