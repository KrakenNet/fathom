"""Unit tests for :mod:`fathom.models`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fathom.models import ActionType, AssertSpec, AuditRecord, ConditionEntry, ThenBlock


class TestAssertSpec:
    """Unit tests for :class:`AssertSpec`."""

    def test_construct_minimal(self) -> None:
        """AssertSpec constructs with ``template`` and ``slots`` fields (FR-1, AC-6.2)."""
        spec = AssertSpec(template="routing_decision", slots={"source_id": "?sid"})

        assert spec.template == "routing_decision"
        assert spec.slots == {"source_id": "?sid"}

    def test_default_slots_is_empty_dict(self) -> None:
        """``slots`` defaults to an empty dict when omitted (AC-6.2)."""
        spec = AssertSpec(template="routing_decision")

        assert spec.slots == {}


class TestThenBlock:
    """Unit tests for :class:`ThenBlock`."""

    def test_assert_alias_accepts_yaml_key_assert(self) -> None:
        """The YAML key ``assert`` maps via alias to the ``asserts`` field (FR-2, UQ-1)."""
        block = ThenBlock(**{"assert": [AssertSpec(template="routing_decision")]})

        assert len(block.asserts) == 1
        assert block.asserts[0].template == "routing_decision"

    def test_action_optional_when_assert_present(self) -> None:
        """``action`` is optional when a non-empty ``asserts`` list is provided (FR-3, AC-6.3)."""
        block = ThenBlock(asserts=[AssertSpec(template="routing_decision")])

        assert block.action is None
        assert len(block.asserts) == 1

    def test_rejects_missing_action_and_assert(self) -> None:
        """``ThenBlock`` without ``action`` or ``assert`` raises (FR-4, AC-1.4, NFR-4)."""
        with pytest.raises(ValidationError) as exc_info:
            ThenBlock()

        message = str(exc_info.value)
        assert "action" in message
        assert "assert" in message

    def test_empty_asserts_list_with_action(self) -> None:
        """An empty ``asserts`` list is accepted when ``action`` is provided (FR-15)."""
        block = ThenBlock(action=ActionType.ALLOW)

        assert block.action is ActionType.ALLOW
        assert block.asserts == []


class TestConditionEntry:
    """Unit tests for :class:`ConditionEntry`."""

    def test_bind_accepts_question_prefix(self) -> None:
        """``bind`` values starting with ``?`` validate (FR-10)."""
        entry = ConditionEntry(slot="id", bind="?sid")

        assert entry.slot == "id"
        assert entry.bind == "?sid"
        assert entry.expression == ""

    def test_bind_rejects_no_question_prefix(self) -> None:
        """``bind`` values missing the ``?`` prefix raise ``ValidationError`` (FR-10)."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(slot="id", bind="sid")

        assert "must start with '?'" in str(exc_info.value)

    def test_bind_with_expression_validates(self) -> None:
        """``bind`` and ``expression`` coexist on one entry (AC-2.3)."""
        entry = ConditionEntry(slot="id", bind="?sid", expression="equals(x)")

        assert entry.bind == "?sid"
        assert entry.expression == "equals(x)"

    def test_requires_bind_or_expression(self) -> None:
        """Omitting ``bind``, ``expression``, and ``test`` raises ``ValidationError``."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(slot="id")

        assert "requires 'expression', 'bind', or 'test'" in str(exc_info.value)

    def test_test_field_accepts_parenthesized_expression(self) -> None:
        """``test`` accepts a parenthesized CLIPS expression (raw-CLIPS escape)."""
        entry = ConditionEntry(test="(my-fn ?sid)")

        assert entry.test == "(my-fn ?sid)"
        assert entry.slot == ""
        assert entry.expression == ""
        assert entry.bind is None

    def test_test_field_rejects_unwrapped_expression(self) -> None:
        """``test`` must start with ``(`` and end with ``)``."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(test="my-fn ?sid")

        assert "parenthesized CLIPS expression" in str(exc_info.value)

    def test_test_field_rejects_empty_string(self) -> None:
        """``test`` rejects whitespace-only values."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(test="   ")

        assert "must not be empty" in str(exc_info.value)

    def test_slot_required_when_expression_set(self) -> None:
        """``slot`` is required when ``expression`` or ``bind`` is set."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(expression="equals(x)")

        assert "requires 'slot'" in str(exc_info.value)

    def test_test_with_expression_coexist(self) -> None:
        """``test`` may be combined with ``expression`` to add a raw test CE."""
        entry = ConditionEntry(
            slot="id", expression="equals(x)", test="(my-fn ?sid)"
        )

        assert entry.expression == "equals(x)"
        assert entry.test == "(my-fn ?sid)"

    def test_slot_with_test_alone_rejected(self) -> None:
        """``slot`` alongside ``test`` alone is rejected: the compiler's
        test-only fast path would silently drop the slot constraint, so we
        fail loudly at load time instead."""
        with pytest.raises(ValidationError) as exc_info:
            ConditionEntry(slot="id", test="(my-fn)")

        assert "'slot' has no effect with 'test' alone" in str(exc_info.value)


class TestAuditRecord:
    """Unit tests for :class:`AuditRecord`."""

    def test_asserted_facts_optional_default_none(self) -> None:
        """``asserted_facts`` defaults to ``None`` when only required fields are set (FR-12)."""
        record = AuditRecord(
            timestamp="2026-04-14T00:00:00Z",
            session_id="sess-1",
            modules_traversed=["MAIN"],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
        )

        assert record.asserted_facts is None
