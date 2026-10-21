"""Temporal operators decide on the fact *set*, not on assertion order.

A temporal operator compiles to a ``test`` CE that queries working memory.
CLIPS evaluates a test CE once, when the patterns before it match, and never
again. A request fact asserted before the history it is judged against was
therefore judged against an empty history: the same facts gave ``deny`` in
one order and ``allow`` in the other.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import pytest

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES = """
templates:
  - name: req
    slots:
      - {name: user, type: string}
      - {name: ts, type: float}
  - name: ev
    slots:
      - {name: user, type: string}
      - {name: action, type: string}
      - {name: ts, type: float}
"""

MODULES = """
modules:
  - name: m
focus_order: [m]
"""

_SEQUENCE = json.dumps(
    [
        {"template": "ev", "slot": "action", "value": "a0"},
        {"template": "ev", "slot": "action", "value": "a1"},
        {"template": "ev", "slot": "action", "value": "a2"},
    ]
)

# Each expression holds for the three ``ev`` facts below and not without them.
OPERATORS = {
    "count_exceeds": "count_exceeds(ev, user, $p0.user, 2)",
    "rate_exceeds": "rate_exceeds(ev, user, $p0.user, 2, 600)",
    "last_n": "last_n(ev, user, $p0.user, 3)",
    "schema_frequency_exceeds": "schema_frequency_exceeds(ev, user, $p0.user, 3)",
    "distinct_count": "distinct_count(ev, user, action, 2)",
    "sequence_detected": f"sequence_detected({_SEQUENCE}, 600)",
    "changed_within": "changed_within(600)",
}


def _engine(tmp_path: Path, op: str) -> Engine:
    slot = "ts" if op == "changed_within" else "user"
    rules = f"""
ruleset: rs
module: m
rules:
  - name: hit
    when:
      - template: req
        conditions:
          - slot: {slot}
            expression: '{OPERATORS[op]}'
    then: {{action: allow}}
"""
    for name, content in (("templates", TEMPLATES), ("modules", MODULES), ("rules", rules)):
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / f"{name}.yaml").write_text(content)
    return Engine.from_rules(str(tmp_path), default_decision="deny")


def _facts() -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
    now = time.time()
    req = [("req", {"user": "mallory", "ts": now})]
    events = [("ev", {"user": "mallory", "action": f"a{i}", "ts": now - 3 + i}) for i in range(3)]
    return req, events


@pytest.mark.parametrize("op", sorted(OPERATORS))
@pytest.mark.parametrize("req_first", [True, False], ids=["req-first", "events-first"])
def test_evaluate_once_ignores_assert_order(tmp_path: Path, op: str, req_first: bool) -> None:
    req, events = _facts()
    facts = req + events if req_first else events + req
    assert _engine(tmp_path, op).evaluate_once(facts).decision == "allow"


@pytest.mark.parametrize("op", sorted(OPERATORS))
@pytest.mark.parametrize("req_first", [True, False], ids=["req-first", "events-first"])
def test_evaluate_ignores_assert_order(tmp_path: Path, op: str, req_first: bool) -> None:
    req, events = _facts()
    engine = _engine(tmp_path, op)
    for batch in (req, events) if req_first else (events, req):
        engine.assert_facts(batch)
    assert engine.evaluate().decision == "allow"


@pytest.mark.parametrize("op", sorted(set(OPERATORS) - {"changed_within"}))
def test_history_still_required(tmp_path: Path, op: str) -> None:
    """Re-matching at run time must not make the operators vacuously true."""
    req, _ = _facts()
    assert _engine(tmp_path, op).evaluate_once(req).decision == "deny"


def test_history_arriving_after_a_run_is_seen(tmp_path: Path) -> None:
    """A later evaluate() re-judges a standing request against new history."""
    req, events = _facts()
    engine = _engine(tmp_path, "count_exceeds")
    engine.assert_facts(req)
    assert engine.evaluate().decision == "deny"
    engine.assert_facts(events)
    assert engine.evaluate().decision == "allow"
