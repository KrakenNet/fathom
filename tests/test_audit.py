"""Audit log tests -- sinks, records, and engine integration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fathom.audit import AuditLog, AuditSink, FileSink, NullSink
from fathom.engine import Engine
from fathom.models import AuditRecord, EvaluationResult

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(**kwargs: Any) -> EvaluationResult:
    """Build an EvaluationResult with sensible defaults."""
    defaults: dict[str, Any] = {
        "decision": "deny",
        "reason": "test reason",
        "rule_trace": ["rule-a"],
        "module_trace": ["mod-a"],
        "duration_us": 42,
        "metadata": {"k": "v"},
    }
    defaults.update(kwargs)
    return EvaluationResult(**defaults)


class ListSink:
    """Custom sink that collects records in a list for testing."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# 1. FileSink writes valid JSON Lines
# ---------------------------------------------------------------------------


class TestFileSinkJsonLines:
    """FileSink writes one valid JSON object per line."""

    def test_single_record_is_valid_json(self, tmp_path: Path) -> None:
        sink = FileSink(str(tmp_path / "audit.jsonl"))
        record = AuditRecord(
            timestamp="2026-01-01T00:00:00+00:00",
            session_id="sess-1",
            modules_traversed=[],
            rules_fired=[],
            decision="allow",
            reason=None,
            duration_us=10,
        )
        sink.write(record)
        data = json.loads((tmp_path / "audit.jsonl").read_text().strip())
        assert data["decision"] == "allow"

    def test_file_is_created_on_init(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "audit.jsonl"
        FileSink(str(path))
        assert path.exists()

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "c" / "audit.jsonl"
        FileSink(str(path))
        assert path.parent.is_dir()

    def test_each_line_is_independent_json(self, tmp_path: Path) -> None:
        sink = FileSink(str(tmp_path / "audit.jsonl"))
        for i in range(3):
            record = AuditRecord(
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
                session_id=f"sess-{i}",
                modules_traversed=[],
                rules_fired=[],
                decision="deny",
                reason=None,
                duration_us=i,
            )
            sink.write(record)
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "session_id" in parsed


# ---------------------------------------------------------------------------
# 2. Record contains all required fields
# ---------------------------------------------------------------------------


class TestAuditRecordFields:
    """AuditRecord contains all expected fields."""

    def test_required_fields_present(self) -> None:
        record = AuditRecord(
            timestamp="2026-01-01T00:00:00+00:00",
            session_id="s1",
            modules_traversed=["m1"],
            rules_fired=["r1"],
            decision="deny",
            reason="blocked",
            duration_us=100,
        )
        data = json.loads(record.model_dump_json())
        for field in (
            "timestamp",
            "session_id",
            "modules_traversed",
            "rules_fired",
            "decision",
            "reason",
            "duration_us",
        ):
            assert field in data, f"missing field: {field}"

    def test_input_facts_default_none(self) -> None:
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
        )
        assert record.input_facts is None

    def test_input_facts_included_when_set(self) -> None:
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
            input_facts=[{"agent": "a1"}],
        )
        assert record.input_facts == [{"agent": "a1"}]

    def test_metadata_default_empty(self) -> None:
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
        )
        assert record.metadata == {}

    def test_metadata_round_trips(self) -> None:
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
            metadata={"key": "val"},
        )
        data = json.loads(record.model_dump_json())
        assert data["metadata"] == {"key": "val"}


# ---------------------------------------------------------------------------
# 3. NullSink produces no output
# ---------------------------------------------------------------------------


class TestNullSink:
    """NullSink is a no-op."""

    def test_write_does_not_raise(self) -> None:
        sink = NullSink()
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
        )
        sink.write(record)  # should not raise

    def test_no_file_created(self, tmp_path: Path) -> None:
        """NullSink does not create any files."""
        sink = NullSink()
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision=None,
            reason=None,
            duration_us=0,
        )
        sink.write(record)
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# 4. Custom sink protocol implementation
# ---------------------------------------------------------------------------


class TestCustomSinkProtocol:
    """Custom sinks implementing AuditSink protocol work correctly."""

    def test_list_sink_receives_record(self) -> None:
        sink = ListSink()
        record = AuditRecord(
            timestamp="t",
            session_id="s",
            modules_traversed=[],
            rules_fired=[],
            decision="allow",
            reason=None,
            duration_us=0,
        )
        sink.write(record)
        assert len(sink.records) == 1
        assert sink.records[0].decision == "allow"

    def test_custom_sink_satisfies_protocol(self) -> None:
        assert isinstance(ListSink(), AuditSink)

    def test_null_sink_satisfies_protocol(self) -> None:
        assert isinstance(NullSink(), AuditSink)

    def test_file_sink_satisfies_protocol(self, tmp_path: Path) -> None:
        assert isinstance(FileSink(str(tmp_path / "a.jsonl")), AuditSink)

    def test_custom_sink_with_audit_log(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        result = _make_result()
        log.record(result, session_id="sess-1")
        assert len(sink.records) == 1
        assert sink.records[0].session_id == "sess-1"


# ---------------------------------------------------------------------------
# 5. AuditLog.record() creates correct AuditRecord
# ---------------------------------------------------------------------------


class TestAuditLogRecord:
    """AuditLog.record() maps EvaluationResult to AuditRecord correctly."""

    def test_decision_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(decision="allow"), session_id="s")
        assert sink.records[0].decision == "allow"

    def test_reason_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(reason="policy violated"), session_id="s")
        assert sink.records[0].reason == "policy violated"

    def test_rule_trace_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(rule_trace=["r1", "r2"]), session_id="s")
        assert sink.records[0].rules_fired == ["r1", "r2"]

    def test_module_trace_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(module_trace=["m1"]), session_id="s")
        assert sink.records[0].modules_traversed == ["m1"]

    def test_duration_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(duration_us=999), session_id="s")
        assert sink.records[0].duration_us == 999

    def test_metadata_mapped(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(metadata={"a": "b"}), session_id="s")
        assert sink.records[0].metadata == {"a": "b"}

    def test_timestamp_is_iso_format(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(), session_id="s")
        ts = sink.records[0].timestamp
        # ISO format contains 'T' separator and timezone info
        assert "T" in ts
        assert "+" in ts or "Z" in ts

    def test_input_facts_passed_through(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        facts = [{"agent": "a1", "action": "read"}]
        log.record(_make_result(), session_id="s", input_facts=facts)
        assert sink.records[0].input_facts == facts

    def test_input_facts_none_by_default(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(), session_id="s")
        assert sink.records[0].input_facts is None

    def test_modules_traversed_override(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(
            _make_result(module_trace=["from-result"]),
            session_id="s",
            modules_traversed=["override"],
        )
        assert sink.records[0].modules_traversed == ["override"]

    def test_modules_traversed_fallback_to_result(self) -> None:
        sink = ListSink()
        log = AuditLog(sink)
        log.record(_make_result(module_trace=["from-result"]), session_id="s")
        assert sink.records[0].modules_traversed == ["from-result"]


# ---------------------------------------------------------------------------
# 6. Append-only (multiple records in one file)
# ---------------------------------------------------------------------------


class TestAppendOnly:
    """FileSink appends records; never overwrites."""

    def test_three_records_three_lines(self, tmp_path: Path) -> None:
        sink = FileSink(str(tmp_path / "audit.jsonl"))
        for i in range(3):
            record = AuditRecord(
                timestamp=f"t{i}",
                session_id=f"s{i}",
                modules_traversed=[],
                rules_fired=[],
                decision="deny",
                reason=None,
                duration_us=i,
            )
            sink.write(record)
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3

    def test_records_preserve_order(self, tmp_path: Path) -> None:
        sink = FileSink(str(tmp_path / "audit.jsonl"))
        for i in range(3):
            record = AuditRecord(
                timestamp=f"t{i}",
                session_id=f"s{i}",
                modules_traversed=[],
                rules_fired=[],
                decision="deny",
                reason=None,
                duration_us=i,
            )
            sink.write(record)
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        for i, line in enumerate(lines):
            assert json.loads(line)["session_id"] == f"s{i}"


# ---------------------------------------------------------------------------
# 7. Engine integration with audit
# ---------------------------------------------------------------------------


class TestEngineAuditIntegration:
    """Engine writes audit records on evaluate()."""

    def test_evaluate_writes_audit_record(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        e = Engine(audit_sink=FileSink(str(audit_file)))
        e.evaluate()
        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["decision"] == "deny"  # default
        assert "timestamp" in record
        assert "session_id" in record

    def test_multiple_evaluations_append(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        e = Engine(audit_sink=FileSink(str(audit_file)))
        e.evaluate()
        e.evaluate()
        e.evaluate()
        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_session_id_in_audit(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        e = Engine(
            audit_sink=FileSink(str(audit_file)),
            session_id="my-session",
        )
        e.evaluate()
        record = json.loads(audit_file.read_text().strip())
        assert record["session_id"] == "my-session"

    def test_null_sink_no_file(self, tmp_path: Path) -> None:
        """Engine with NullSink (default) creates no audit file."""
        e = Engine()  # default is NullSink
        e.evaluate()
        assert not (tmp_path / "audit.jsonl").exists()

    def test_custom_sink_with_engine(self) -> None:
        sink = ListSink()
        e = Engine(audit_sink=sink)  # type: ignore[arg-type]
        e.evaluate()
        assert len(sink.records) == 1
        assert sink.records[0].decision == "deny"


# ---------------------------------------------------------------------------
# 8. AuditRecord.asserted_facts capture (Phase 3 / UQ-6)
# ---------------------------------------------------------------------------


_TEMPLATES_YAML = """\
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
  - name: routing_decision
    slots:
      - name: source_id
        type: string
        required: true
"""

_MODULES_YAML = """\
modules:
  - name: governance
    description: "test module"
focus_order:
  - governance
"""

_RULE_WITH_ASSERT_YAML = """\
module: governance
rules:
  - name: emit-routing
    description: "Emit a routing_decision fact for every agent"
    when:
      - template: agent
        conditions:
          - slot: id
            bind: "?sid"
    then:
      action: allow
      reason: "routed"
      assert:
        - template: routing_decision
          slots:
            source_id: "?sid"
"""

_RULE_NO_ASSERT_YAML = """\
module: governance
rules:
  - name: allow-agent
    description: "Allow when an agent is present"
    when:
      - template: agent
        conditions:
          - slot: id
            bind: "?sid"
    then:
      action: allow
      reason: "ok"
"""


def _make_engine_with_assert_rule(tmp_path: Path) -> Engine:
    """Engine with an agent template and a rule whose RHS asserts routing_decision."""
    (tmp_path / "templates.yaml").write_text(_TEMPLATES_YAML)
    (tmp_path / "modules.yaml").write_text(_MODULES_YAML)
    (tmp_path / "rules.yaml").write_text(_RULE_WITH_ASSERT_YAML)
    e = Engine()
    e.load_templates(str(tmp_path / "templates.yaml"))
    e.load_modules(str(tmp_path / "modules.yaml"))
    e.load_rules(str(tmp_path / "rules.yaml"))
    return e


def _make_engine_no_assert_rule(tmp_path: Path) -> Engine:
    """Engine with an agent template and a rule whose RHS has no asserts."""
    (tmp_path / "templates.yaml").write_text(_TEMPLATES_YAML)
    (tmp_path / "modules.yaml").write_text(_MODULES_YAML)
    (tmp_path / "rules.yaml").write_text(_RULE_NO_ASSERT_YAML)
    e = Engine()
    e.load_templates(str(tmp_path / "templates.yaml"))
    e.load_modules(str(tmp_path / "modules.yaml"))
    e.load_rules(str(tmp_path / "rules.yaml"))
    return e


class TestAuditAssertedFacts:
    """AuditRecord.asserted_facts captures user facts newly asserted by rules."""

    def test_no_assert_no_asserted_facts_field(self, tmp_path: Path) -> None:
        """Additivity: when no loaded rule declares `then.assert`, the audit
        record's `asserted_facts` stays ``None`` (AC: additive, no regression)."""
        sink = ListSink()
        e = _make_engine_no_assert_rule(tmp_path)
        e._audit_log = AuditLog(sink)  # swap sink after construction
        e.assert_fact("agent", {"id": "alpha"})
        e.evaluate()
        assert len(sink.records) == 1
        assert sink.records[0].asserted_facts is None

    def test_assert_captured_in_audit_record(self, tmp_path: Path) -> None:
        """UQ-6: after evaluating a rule with `then.assert`, the audit record
        contains a matching AssertedFact."""
        from fathom.models import AssertedFact

        sink = ListSink()
        e = _make_engine_with_assert_rule(tmp_path)
        e._audit_log = AuditLog(sink)
        e.assert_fact("agent", {"id": "alpha"})
        e.evaluate()
        assert len(sink.records) == 1
        asserted = sink.records[0].asserted_facts
        assert asserted is not None
        # Exactly one fact was newly asserted by the rule
        matches = [
            f
            for f in asserted
            if isinstance(f, AssertedFact)
            and f.template == "routing_decision"
            and f.slots.get("source_id") == "alpha"
        ]
        assert len(matches) == 1, f"expected routing_decision(source_id=alpha), got {asserted!r}"

    def test_decision_facts_excluded_from_audit(self, tmp_path: Path) -> None:
        """Exclusion semantics: the internal `__fathom_decision` fact emitted
        by action rules must NOT appear in `asserted_facts`."""
        sink = ListSink()
        e = _make_engine_with_assert_rule(tmp_path)
        e._audit_log = AuditLog(sink)
        e.assert_fact("agent", {"id": "alpha"})
        e.evaluate()
        assert len(sink.records) == 1
        asserted = sink.records[0].asserted_facts or []
        assert all(f.template != "__fathom_decision" for f in asserted), (
            f"__fathom_decision leaked into asserted_facts: {asserted!r}"
        )

    def test_preexisting_facts_not_double_counted(self, tmp_path: Path) -> None:
        """Diff semantics: a user fact asserted BEFORE `evaluate()` must NOT
        appear in that evaluate's `asserted_facts`."""
        sink = ListSink()
        e = _make_engine_with_assert_rule(tmp_path)
        e._audit_log = AuditLog(sink)
        # Pre-assert a routing_decision directly (simulates a fact set up by
        # the caller). The rule will also fire and assert a fact for the
        # agent — but only the NEW one should show up in the diff.
        e.assert_fact("routing_decision", {"source_id": "preexisting"})
        e.assert_fact("agent", {"id": "alpha"})
        e.evaluate()
        assert len(sink.records) == 1
        asserted = sink.records[0].asserted_facts or []
        preexisting_matches = [
            f
            for f in asserted
            if f.template == "routing_decision" and f.slots.get("source_id") == "preexisting"
        ]
        assert preexisting_matches == [], (
            f"pre-existing fact leaked into diff: {preexisting_matches!r}"
        )
