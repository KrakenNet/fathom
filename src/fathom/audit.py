"""Audit logging with pluggable sink protocol."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fathom.models import AssertedFact, AuditRecord, EvaluationResult, LogLevel

#: What a sink may be handed. Evaluation writes an :class:`AuditRecord`;
#: the REST and gRPC hot-reload handlers write a plain mapping describing a
#: ``ruleset_reloaded`` / ``ruleset_reload_rejected`` event, which has no
#: evaluation shape to fit into.
AuditPayload = AuditRecord | Mapping[str, Any]


__all__ = ["AuditLog", "AuditPayload", "AuditSink", "FileSink", "NullSink"]


@runtime_checkable
class AuditSink(Protocol):
    """Protocol for audit record sinks."""

    def write(self, record: AuditPayload) -> None: ...


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

    def write(self, record: AuditPayload) -> None:
        if isinstance(record, AuditRecord):
            payload = record.model_dump_json()
        else:
            # Non-evaluation events (hot reload) arrive as plain mappings.
            # ``default=str`` keeps a stray datetime or Path from making a
            # reload unwritable.
            payload = json.dumps(dict(record), default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(payload + "\n")


class NullSink:
    """No-op audit sink."""

    def write(self, record: AuditPayload) -> None:
        pass


class AuditLog:
    """Records audit entries from evaluation results via a pluggable sink."""

    def __init__(self, sink: AuditSink) -> None:
        """Create an audit log backed by the given sink.

        Args:
            sink: Pluggable sink that receives serialised audit records.
        """
        self._sink = sink

    @property
    def is_recording(self) -> bool:
        """True when the configured sink actually persists records.

        Lets :meth:`fathom.engine.Engine.evaluate` skip the working-memory
        snapshot that only a real sink would ever consume.
        """
        return not isinstance(self._sink, NullSink)

    def record(
        self,
        result: EvaluationResult,
        session_id: str,
        input_facts: list[dict[str, object]] | None = None,
        modules_traversed: list[str] | None = None,
        *,
        asserted_facts: list[AssertedFact] | None = None,
        log_level: LogLevel = LogLevel.SUMMARY,
    ) -> None:
        """Write one audit record, honouring the winning rule's ``then.log``.

        Args:
            result: The evaluation result being recorded.
            session_id: Session the evaluation ran under.
            input_facts: Working-memory snapshot taken before inference.
                Written only at :attr:`LogLevel.FULL`.
            modules_traversed: Overrides ``result.module_trace``.
            asserted_facts: Facts the rules themselves asserted.
            log_level: The ``then.log`` level of the winning decision.
                :attr:`LogLevel.NONE` writes nothing at all;
                :attr:`LogLevel.SUMMARY` omits *input_facts*;
                :attr:`LogLevel.FULL` includes them.
        """
        if log_level is LogLevel.NONE:
            return
        if log_level is not LogLevel.FULL:
            input_facts = None
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
