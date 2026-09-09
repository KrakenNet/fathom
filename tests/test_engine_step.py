"""Incremental evaluation — ``Engine.step`` (#242).

``evaluate()`` clears CLIPS refraction on every call, so a decision is a
function of working memory rather than of how often the engine has been
asked. A step does not: each rule fires once per *new* match. That is the
difference a stream needs, and every test here is about it or about what a
step deliberately does not do — sign, or audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fathom.attestation import AttestationService
from fathom.engine import Engine

if TYPE_CHECKING:
    from fathom.audit import AuditPayload

RULES = "examples/01-hello-allow-deny"

AGENT = ("agent", {"id": "a1", "clearance": "secret"})
REQ_TOP_SECRET = (
    "data_request",
    {"agent_id": "a1", "classification": "top-secret", "resource": "x"},
)


class ListSink:
    """Audit sink that keeps what it is handed."""

    def __init__(self) -> None:
        self.records: list[AuditPayload] = []

    def write(self, record: AuditPayload) -> None:
        self.records.append(record)


class TestRefractionIsKept:
    def test_a_step_fires_the_rules_a_batch_activates(self) -> None:
        engine = Engine.from_rules(RULES)
        result = engine.step([AGENT, REQ_TOP_SECRET])
        assert result.decision == "deny"
        assert result.rule_trace

    def test_a_second_step_over_the_same_facts_fires_nothing(self) -> None:
        """The whole point: a rule fires once per match, not once per call."""
        engine = Engine.from_rules(RULES)
        engine.step([AGENT, REQ_TOP_SECRET])
        assert engine.step().rule_trace == []

    def test_evaluate_over_the_same_facts_fires_again(self) -> None:
        """Contrast, and the behaviour step() must not change."""
        engine = Engine.from_rules(RULES)
        engine.step([AGENT, REQ_TOP_SECRET])
        assert engine.evaluate().rule_trace

    def test_a_new_fact_activates_the_rule_again(self) -> None:
        engine = Engine.from_rules(RULES)
        engine.step([AGENT, REQ_TOP_SECRET])
        second = engine.step(
            [
                (
                    "data_request",
                    {"agent_id": "a1", "classification": "top-secret", "resource": "y"},
                )
            ]
        )
        assert second.rule_trace

    def test_facts_persist_across_steps(self) -> None:
        engine = Engine.from_rules(RULES)
        engine.step([AGENT])
        engine.step([REQ_TOP_SECRET])
        assert engine.count("agent") == 1
        assert engine.count("data_request") == 1

    def test_the_second_batch_decides_on_the_first_batch_facts(self) -> None:
        """A step joins new facts against working memory, not just its batch."""
        engine = Engine.from_rules(RULES)
        engine.step([AGENT])
        assert engine.step([REQ_TOP_SECRET]).decision == "deny"

    def test_step_with_no_facts_on_an_empty_engine_is_harmless(self) -> None:
        assert Engine.from_rules(RULES).step().rule_trace == []


class TestStepIsNotADecisionBoundary:
    """A step is never signed and never audited, and the docstring says so."""

    def test_no_attestation_token_even_with_a_service_configured(self) -> None:
        engine = Engine.from_rules(RULES)
        engine.attestation_service = AttestationService.generate_keypair()
        result = engine.step([AGENT, REQ_TOP_SECRET])
        assert result.decision == "deny"
        assert result.attestation_token is None

    def test_evaluate_still_signs(self) -> None:
        """Contrast: the guarantee step() opts out of is still there."""
        engine = Engine.from_rules(RULES)
        engine.attestation_service = AttestationService.generate_keypair()
        engine.assert_fact(*AGENT)
        engine.assert_fact(*REQ_TOP_SECRET)
        assert engine.evaluate().attestation_token is not None

    def test_no_audit_record(self) -> None:
        sink = ListSink()
        engine = Engine.from_rules(RULES, audit_sink=sink)
        engine.step([AGENT, REQ_TOP_SECRET])
        assert sink.records == []

    def test_evaluate_still_records(self) -> None:
        sink = ListSink()
        engine = Engine.from_rules(RULES, audit_sink=sink)
        engine.assert_fact(*AGENT)
        engine.assert_fact(*REQ_TOP_SECRET)
        engine.evaluate()
        assert len(sink.records) == 1
