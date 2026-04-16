"""Audit logging with pluggable sink protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from fathom.models import AssertedFact, AuditRecord, EvaluationResult


@runtime_checkable
class AuditSink(Protocol):
    """Protocol for audit record sinks."""

    def write(self, record: AuditRecord) -> None: ...


class FileSink:
    """Writes audit records as JSON Lines to a file (append mode)."""

    def __init__(self, path: str | Path) -> None:
        """Create a file sink.

        Args:
            path: Path to the JSON Lines audit file (created if missing).
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def write(self, record: AuditRecord) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


class NullSink:
    """No-op audit sink."""

    def write(self, record: AuditRecord) -> None:
        pass


class AuditLog:
    """Records audit entries from evaluation results via a pluggable sink."""

    def __init__(self, sink: AuditSink) -> None:
        """Create an audit log backed by the given sink.

        Args:
            sink: Pluggable sink that receives serialised audit records.
        """
        self._sink = sink

    def record(
        self,
        result: EvaluationResult,
        session_id: str,
        input_facts: list[dict[str, object]] | None = None,
        modules_traversed: list[str] | None = None,
        *,
        asserted_facts: list[AssertedFact] | None = None,
    ) -> None:
        audit = AuditRecord(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            input_facts=input_facts,
            modules_traversed=modules_traversed or result.module_trace,
            rules_fired=result.rule_trace,
            decision=result.decision,
            reason=result.reason,
            duration_us=result.duration_us,
            metadata=result.metadata,
            asserted_facts=asserted_facts,
        )
        self._sink.write(audit)
