"""Match evidence: which facts, with which slot values, fired each rule.

``rule_trace`` names the rules that fired but not the working memory that
made them fire, so a deny over a hundred asserted facts is unexplainable
after the fact. ``Engine(match_evidence=True)`` records the basis of every
firing. It is opt-in because the evidence is carried by extra CLIPS
constructs the compiler only emits when it is on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from fathom.audit import AuditSink
from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.models import (
    AuditRecord,
    ConditionEntry,
    FactPattern,
    RuleDefinition,
    ThenBlock,
)

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES = """
templates:
  - name: agent
    slots:
      - name: id
        type: string
      - name: clearance
        type: string
  - name: request
    slots:
      - name: agent_id
        type: string
      - name: target
        type: string
"""

RULES = """
module: governance
rules:
  - name: deny-uncleared
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: equals(none)
    then:
      action: deny
      reason: Agent has no clearance
"""


def _write_pack(root: Path, rules_yaml: str = RULES) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "templates.yaml").write_text(TEMPLATES)
    (root / "modules.yaml").write_text(
        "modules:\n  - name: governance\nfocus_order: [governance]\n"
    )
    (root / "rules.yaml").write_text(rules_yaml)
    return root


class _CollectingSink(AuditSink):
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)


class TestEvidenceNamesTheMatchingFact:
    """AC-3: several facts asserted, only one fires the rule."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:
        engine = Engine.from_rules(str(_write_pack(tmp_path / "pack")), match_evidence=True)
        engine.assert_fact("agent", {"id": "alpha", "clearance": "secret"})
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        engine.assert_fact("agent", {"id": "charlie", "clearance": "top-secret"})
        return engine

    def test_the_deny_still_happens(self, engine: Engine) -> None:
        assert engine.evaluate().decision == "deny"

    def test_exactly_one_rule_firing_is_recorded(self, engine: Engine) -> None:
        evidence = engine.evaluate().match_evidence
        assert len(evidence) == 1
        assert evidence[0].rule == "governance::deny-uncleared"

    def test_the_evidence_names_only_the_matching_fact(self, engine: Engine) -> None:
        [firing] = engine.evaluate().match_evidence
        assert [f.template for f in firing.facts] == ["agent"]
        assert firing.facts[0].slots == {"id": "bravo", "clearance": "none"}


class TestEvidenceIsOffByDefault:
    """AC-2: the default path emits no evidence constructs at all."""

    def test_no_evidence_is_recorded(self, tmp_path: Path) -> None:
        engine = Engine.from_rules(str(_write_pack(tmp_path / "pack")))
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        result = engine.evaluate()
        assert result.decision == "deny"
        assert result.match_evidence == []

    def test_the_compiled_rule_is_byte_identical(self) -> None:
        rule = RuleDefinition(
            name="deny-uncleared",
            when=[
                FactPattern(
                    template="agent",
                    conditions=[ConditionEntry(slot="clearance", expression="equals(none)")],
                )
            ],
            then=ThenBlock(action="deny", reason="no clearance"),
        )
        off = Compiler().compile_rule(rule, "governance")
        on = Compiler(match_evidence=True).compile_rule(rule, "governance")
        assert "__fathom_evidence" not in off
        assert "__fathom_evidence" in on
        assert off == "\n".join(
            line for line in on.splitlines() if "__fathom_evidence" not in line
        ).replace("?fathom-ev-0 <- ", "")


class TestMultiPatternRules:
    """Every pattern on the LHS contributes its matching fact."""

    RULES = """
module: governance
rules:
  - name: deny-cross-agent
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: equals(none)
      - template: request
        conditions:
          - slot: target
            expression: equals(payroll)
    then:
      action: deny
      reason: Uncleared agent while a payroll request is open
"""

    @pytest.fixture
    def evidence(self, tmp_path: Path) -> list:
        pack = _write_pack(tmp_path / "pack", self.RULES)
        engine = Engine.from_rules(str(pack), match_evidence=True)
        engine.assert_fact("agent", {"id": "alpha", "clearance": "secret"})
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        engine.assert_fact("request", {"agent_id": "alpha", "target": "hr"})
        engine.assert_fact("request", {"agent_id": "bravo", "target": "payroll"})
        return engine.evaluate().match_evidence

    def test_both_patterns_are_represented(self, evidence: list) -> None:
        [firing] = evidence
        assert [f.template for f in firing.facts] == ["agent", "request"]

    def test_the_joined_pair_is_the_one_recorded(self, evidence: list) -> None:
        [firing] = evidence
        assert firing.facts[0].slots["id"] == "bravo"
        assert firing.facts[1].slots["target"] == "payroll"


class TestEvidenceReachesTheAuditRecord:
    """AC-4: match evidence round-trips through AuditRecord JSON."""

    @pytest.fixture
    def record(self, tmp_path: Path) -> AuditRecord:
        sink = _CollectingSink()
        engine = Engine.from_rules(
            str(_write_pack(tmp_path / "pack")), match_evidence=True, audit_sink=sink
        )
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        engine.evaluate()
        return sink.records[0]

    def test_the_record_carries_the_evidence(self, record: AuditRecord) -> None:
        assert record.match_evidence is not None
        assert record.match_evidence[0].facts[0].slots["id"] == "bravo"

    def test_it_survives_a_json_round_trip(self, record: AuditRecord) -> None:
        restored = AuditRecord.model_validate(json.loads(record.model_dump_json()))
        assert restored.match_evidence == record.match_evidence


class TestEvidenceDoesNotLeakBetweenEvaluations:
    """Evidence facts are retracted with the decision facts."""

    def test_a_second_evaluate_reports_its_own_evidence(self, tmp_path: Path) -> None:
        engine = Engine.from_rules(str(_write_pack(tmp_path / "pack")), match_evidence=True)
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        first = engine.evaluate()
        second = engine.evaluate()
        assert len(first.match_evidence) == 1
        # Refraction: the rule does not re-fire on unchanged working memory.
        assert second.match_evidence == []


class TestAssertOnlyRulesAreCovered:
    """A rule with no ``then.action`` still records why it fired."""

    RULES = """
module: governance
rules:
  - name: flag-uncleared
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: equals(none)
    then:
      assert:
        - template: request
          slots:
            agent_id: flagged
            target: review
"""

    def test_the_assert_only_rule_appears_in_evidence(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path / "pack", self.RULES)
        engine = Engine.from_rules(str(pack), match_evidence=True)
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        result = engine.evaluate()
        assert [e.rule for e in result.match_evidence] == ["governance::flag-uncleared"]
