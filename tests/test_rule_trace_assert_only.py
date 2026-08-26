"""Every rule that fires belongs in the trace, decision or no decision.

``rule_trace`` was read off ``__fathom_decision`` facts, which only a rule
with a ``then.action`` asserts. A forward-chaining rule -- one whose ``then``
is nothing but ``assert:`` -- fired, wrote the working-memory fact the next
rule matched on, and left no mark on the trace or on the signed audit record.
An auditor reading that record saw the conclusion with the step that produced
it missing.

The rule packs shipped in ``src/fathom/rule_packs`` are built almost entirely
out of such rules, so for those packs the audit record recorded nothing at
all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml

from fathom.engine import Engine

if TYPE_CHECKING:
    from pathlib import Path

    from fathom.audit import AuditRecord

TEMPLATES = {
    "templates": [
        {
            "name": "request",
            "slots": [
                {"name": "actor", "type": "symbol"},
                {"name": "amount", "type": "float"},
            ],
        },
        {
            "name": "flagged",
            "slots": [
                {"name": "actor", "type": "symbol"},
                {"name": "why", "type": "string"},
            ],
        },
    ]
}

# `infer` derives, `gov` decides. Two modules so module_trace is exercised
# too: the deriving module used to be missing from it for the same reason.
MODULES = {"modules": [{"name": "infer"}, {"name": "gov"}], "focus_order": ["infer", "gov"]}

INFER_RULES = {
    "ruleset": "trace-infer",
    "module": "infer",
    "rules": [
        {
            "name": "flag-large-transfer",
            "when": [
                {
                    "template": "request",
                    "conditions": [
                        {"slot": "amount", "expression": "greater_than(10000)"},
                        {"slot": "actor", "bind": "?who"},
                    ],
                }
            ],
            # No `action` — this is the rule the trace used to lose.
            "then": {
                "assert": [
                    {
                        "template": "flagged",
                        "slots": {"actor": "?who", "why": "amount over limit"},
                    }
                ]
            },
        }
    ],
}

GOV_RULES = {
    "ruleset": "trace-gov",
    "module": "gov",
    "rules": [
        {
            "name": "deny-flagged",
            "when": [{"template": "flagged", "conditions": [{"slot": "why", "bind": "?why"}]}],
            "then": {"action": "deny", "reason": "flagged"},
        }
    ],
}


class _ListSink:
    """Audit sink that keeps every record for inspection."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: Any) -> None:
        self.records.append(record)


@pytest.fixture
def pack(tmp_path: Path) -> str:
    """An on-disk rule pack: one assert-only rule, one deciding rule."""
    root = tmp_path / "pack"
    for subdir in ("templates", "modules", "rules"):
        (root / subdir).mkdir(parents=True)
    (root / "templates" / "t.yaml").write_text(yaml.safe_dump(TEMPLATES))
    (root / "modules" / "m.yaml").write_text(yaml.safe_dump(MODULES))
    (root / "rules" / "infer.yaml").write_text(yaml.safe_dump(INFER_RULES))
    (root / "rules" / "gov.yaml").write_text(yaml.safe_dump(GOV_RULES))
    return str(root)


def test_assert_only_rule_appears_in_the_trace(pack: str) -> None:
    """The derivation step is the part of the trace worth having."""
    engine = Engine.from_rules(pack)

    result = engine.evaluate_once([("request", {"actor": "alice", "amount": 25000.0})])

    assert result.decision == "deny"
    assert result.rule_trace == [
        "infer::flag-large-transfer",
        "gov::deny-flagged",
    ]


def test_the_deriving_module_appears_in_the_module_trace(pack: str) -> None:
    """`infer` never rendered a decision, so it was absent from module_trace."""
    engine = Engine.from_rules(pack)

    result = engine.evaluate_once([("request", {"actor": "alice", "amount": 25000.0})])

    assert result.module_trace == ["infer", "gov"]


def test_the_audit_record_carries_the_assert_only_rule(pack: str) -> None:
    """`rules_fired` is `rule_trace`, so the record inherited the same hole."""
    sink = _ListSink()
    engine = Engine.from_rules(pack, audit_sink=sink)

    engine.evaluate_once([("request", {"actor": "alice", "amount": 25000.0})])

    assert len(sink.records) == 1
    assert "infer::flag-large-transfer" in sink.records[0].rules_fired


def test_a_rule_that_fires_twice_is_traced_twice(pack: str) -> None:
    """CLIPS drops a duplicate assert, so identical decisions collapsed to one.

    ``evaluate_once`` withdraws the caller's facts but leaves rule-asserted
    ones, so the second call sees alice's ``flagged`` fact alongside bob's and
    ``deny-flagged`` fires on each.
    """
    engine = Engine.from_rules(pack)

    engine.evaluate_once([("request", {"actor": "alice", "amount": 25000.0})])
    second = engine.evaluate_once([("request", {"actor": "bob", "amount": 99999.0})])

    assert second.rule_trace.count("gov::deny-flagged") == 2


def test_a_rule_that_did_not_fire_is_not_traced(pack: str) -> None:
    """The marker is asserted on the RHS, so only an actual firing records one."""
    engine = Engine.from_rules(pack)

    result = engine.evaluate_once([("request", {"actor": "bob", "amount": 5.0})])

    assert result.rule_trace == []
    assert result.reason == "default decision (no rule rendered a decision)"


def test_the_trace_does_not_survive_into_the_next_evaluation(pack: str) -> None:
    """Markers are retracted in the evaluator's finally block, like decisions."""
    engine = Engine.from_rules(pack)

    engine.evaluate_once([("request", {"actor": "alice", "amount": 25000.0})])
    second = engine.evaluate_once([("request", {"actor": "carol", "amount": 3.0})])

    assert "infer::flag-large-transfer" not in second.rule_trace
