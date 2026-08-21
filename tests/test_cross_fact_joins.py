"""Cross-fact references must compile to a real CLIPS join.

``equals($a.id)`` emits ``?a-id`` in the pattern that references it. CLIPS
binds a variable on first occurrence, so unless the pattern aliased ``$a``
also mentions ``?a-id``, the variable binds there and constrains nothing —
the rule matches the cartesian product of its patterns and fires on facts
the author never joined. Silent: no CLIPS error, no warning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.models import (
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
  - name: deny-uncleared-request
    when:
      - template: agent
        alias: $a
        conditions:
          - slot: clearance
            expression: equals(none)
      - template: request
        conditions:
          - slot: agent_id
            expression: equals($a.id)
    then:
      action: deny
      reason: Uncleared agent made a request
"""


def _write_pack(root: Path, rules_yaml: str = RULES) -> str:
    root.mkdir(parents=True, exist_ok=True)
    (root / "templates.yaml").write_text(TEMPLATES)
    (root / "modules.yaml").write_text(
        "modules:\n  - name: governance\nfocus_order: [governance]\n"
    )
    (root / "rules.yaml").write_text(rules_yaml)
    return str(root)


def _rule(*conditions: tuple[str, str, str | None]) -> RuleDefinition:
    """Build a two-pattern rule: agent (aliased ``$a``) then request."""
    return RuleDefinition(
        name="joined",
        when=[
            FactPattern(
                template="agent",
                alias="$a",
                conditions=[ConditionEntry(slot="clearance", expression="equals(none)")],
            ),
            FactPattern(
                template="request",
                conditions=[
                    ConditionEntry(slot=slot, expression=expr, bind=bind)
                    for slot, expr, bind in conditions
                ],
            ),
        ],
        then=ThenBlock(action="deny", reason="joined"),
    )


class TestTheJoinActuallyJoins:
    """Two agents, two requests: only the matching pair may fire.

    The engine is built with ``default_decision=None`` so a ``deny`` can
    only have come from the rule, never from the fail-closed default.
    """

    def _engine(self, tmp_path: Path, request_agent: str) -> Engine:
        engine = Engine.from_rules(_write_pack(tmp_path / "pack"), default_decision=None)
        engine.assert_fact("agent", {"id": "alpha", "clearance": "secret"})
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        engine.assert_fact("request", {"agent_id": request_agent, "target": "payroll"})
        return engine

    def test_it_fires_on_the_joined_pair(self, tmp_path: Path) -> None:
        assert self._engine(tmp_path, "bravo").evaluate().decision == "deny"

    def test_it_does_not_fire_across_the_pair(self, tmp_path: Path) -> None:
        """The only uncleared agent is bravo; the only request is alpha's."""
        assert self._engine(tmp_path, "alpha").evaluate().decision is None


class TestTheAliasedPatternBindsTheVariable:
    """The referenced slot has to appear on the pattern that owns it."""

    def test_an_otherwise_unconstrained_slot_gains_a_binding(self) -> None:
        clips = Compiler().compile_rule(_rule(("agent_id", "equals($a.id)", None)), "governance")
        assert "(agent (clearance none) (id ?a-id))" in clips

    def test_an_existing_constraint_on_that_slot_survives(self) -> None:
        clips = Compiler().compile_rule(
            _rule(("agent_id", "equals($a.clearance)", None)), "governance"
        )
        assert "(agent (clearance ?a-clearance&none))" in clips

    def test_a_classification_op_is_not_bound_twice(self) -> None:
        rule = RuleDefinition(
            name="joined",
            when=[
                FactPattern(
                    template="agent",
                    alias="$a",
                    conditions=[
                        ConditionEntry(slot="clearance", expression="meets_or_exceeds(secret)")
                    ],
                ),
                FactPattern(
                    template="request",
                    conditions=[ConditionEntry(slot="target", expression="equals($a.clearance)")],
                ),
            ],
            then=ThenBlock(action="deny", reason="joined"),
        )
        clips = Compiler().compile_rule(rule, "governance")
        assert clips.count("?a-clearance&") == 0
        assert "(agent (clearance ?a-clearance))" in clips

    def test_a_pattern_with_no_conditions_still_binds(self) -> None:
        rule = RuleDefinition(
            name="joined",
            when=[
                FactPattern(template="agent", alias="$a", conditions=[]),
                FactPattern(
                    template="request",
                    conditions=[ConditionEntry(slot="agent_id", expression="equals($a.id)")],
                ),
            ],
            then=ThenBlock(action="deny", reason="joined"),
        )
        assert "(agent (id ?a-id))" in Compiler().compile_rule(rule, "governance")

    def test_a_user_bind_on_the_same_slot_is_kept(self) -> None:
        rule = RuleDefinition(
            name="joined",
            when=[
                FactPattern(
                    template="agent",
                    alias="$a",
                    conditions=[ConditionEntry(slot="id", bind="?who")],
                ),
                FactPattern(
                    template="request",
                    conditions=[ConditionEntry(slot="agent_id", expression="equals($a.id)")],
                ),
            ],
            then=ThenBlock(action="deny", reason="joined"),
        )
        clips = Compiler().compile_rule(rule, "governance")
        assert "?a-id" in clips
        assert "?who" in clips


class TestUnknownAliasIsRejected:
    """A typo'd alias used to fail open exactly like a missing binding."""

    def test_it_raises_rather_than_compiling(self) -> None:
        with pytest.raises(CompilationError, match="undeclared alias"):
            Compiler().compile_rule(_rule(("agent_id", "equals($nope.id)", None)), "governance")

    def test_the_message_names_the_rule_and_the_alias(self) -> None:
        with pytest.raises(CompilationError) as exc:
            Compiler().compile_rule(_rule(("agent_id", "equals($nope.id)", None)), "governance")
        assert "$nope" in str(exc.value)
        assert "joined" in str(exc.value)


class TestTheShippedBellLaPadulaExample:
    """The example exists to demonstrate no-read-up; it has to hold."""

    @pytest.fixture
    def engine(self) -> Engine:
        engine = Engine.from_rules("examples/03-classification-blp")
        engine.assert_fact("subject", {"id": "alice", "clearance": "secret"})
        engine.assert_fact("subject", {"id": "bob", "clearance": "unclassified"})
        engine.assert_fact("resource", {"id": "doc1", "classification": "top-secret"})
        engine.assert_fact("resource", {"id": "doc2", "classification": "unclassified"})
        return engine

    def test_a_cleared_subject_may_read_down(self, engine: Engine) -> None:
        engine.assert_fact(
            "access_request", {"subject_id": "alice", "object_id": "doc2", "mode": "read"}
        )
        assert engine.evaluate().decision == "allow"

    def test_an_uncleared_subject_still_may_not_read_up(self, engine: Engine) -> None:
        engine.assert_fact(
            "access_request", {"subject_id": "bob", "object_id": "doc1", "mode": "read"}
        )
        result = engine.evaluate()
        assert result.decision == "deny"
        assert "Read-up" in (result.reason or "")


class TestABindLoadsIntoClips:
    """Same root cause: only one variable may bind a slot.

    ``bind:`` used to be chained in front of the generated constraint
    variable, which reads back as text just fine — and is why a text-only
    assertion let it pass — but CLIPS rejects the rule at load time.
    """

    RULES = """
module: governance
rules:
  - name: flag-non-bravo
    when:
      - template: agent
        conditions:
          - slot: id
            bind: "?who"
            # Quoted by hand: on this branch `not_equals` does not yet quote a
            # literal for a string slot (fixed separately in #206).
            expression: not_equals("bravo")
    then:
      action: deny
      reason: "not bravo: {who}"
"""

    def test_the_rule_builds(self, tmp_path: Path) -> None:
        engine = Engine.from_rules(_write_pack(tmp_path / "pack", self.RULES))
        engine.assert_fact("agent", {"id": "alpha", "clearance": "secret"})
        result = engine.evaluate()
        assert result.decision == "deny"
        assert result.reason == "not bravo: alpha"

    def test_it_does_not_fire_on_the_excluded_value(self, tmp_path: Path) -> None:
        engine = Engine.from_rules(
            _write_pack(tmp_path / "pack", self.RULES), default_decision=None
        )
        engine.assert_fact("agent", {"id": "bravo", "clearance": "secret"})
        assert engine.evaluate().decision is None


class TestJoinsUnderMatchEvidence:
    """The two features touch the same patterns and must compose.

    Match evidence prefixes each condition element with a pattern address,
    and the join fix adds a slot binding to the pattern that owns the alias.
    Nothing covered both at once until they landed in the same tree.
    """

    @pytest.fixture
    def evidence(self, tmp_path: Path) -> list:
        engine = Engine.from_rules(_write_pack(tmp_path / "pack"), match_evidence=True)
        engine.assert_fact("agent", {"id": "alpha", "clearance": "secret"})
        engine.assert_fact("agent", {"id": "bravo", "clearance": "none"})
        engine.assert_fact("request", {"agent_id": "alpha", "target": "hr"})
        engine.assert_fact("request", {"agent_id": "bravo", "target": "payroll"})
        return engine.evaluate().match_evidence

    def test_the_rule_fires_once(self, evidence: list) -> None:
        assert len(evidence) == 1

    def test_the_evidence_names_the_joined_pair(self, evidence: list) -> None:
        [firing] = evidence
        assert [f.template for f in firing.facts] == ["agent", "request"]
        assert firing.facts[0].slots["id"] == "bravo"
        assert firing.facts[1].slots["agent_id"] == "bravo"

    def test_the_pattern_address_wraps_the_bound_pattern(self) -> None:
        clips = Compiler(match_evidence=True).compile_rule(
            _rule(("agent_id", "equals($a.id)", None)), "governance"
        )
        assert "?fathom-ev-0 <- (agent (clearance none) (id ?a-id))" in clips
