"""Fathom Evaluator — forward-chain evaluation via CLIPS."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from fathom.errors import EvaluationError, EvaluationLimitError
from fathom.models import EvaluationResult, LogLevel

if TYPE_CHECKING:
    from collections.abc import Callable

    import clips

    from fathom.facts import FactManager


class Evaluator:
    """Runs CLIPS forward-chain evaluation and returns structured results.

    Implements the evaluation sequence from design.md Section 2.4:
    set up focus stack, run to quiescence, read decisions, capture traces,
    clean up decision facts, and return EvaluationResult.
    """

    def __init__(
        self,
        env_provider: Callable[[], clips.Environment],
        default_decision: str | None,
        focus_order: list[str],
        fact_manager: FactManager | None = None,
        run_limit: int | None = None,
    ) -> None:
        self._env_provider = env_provider
        self._default_decision = default_decision
        self._focus_order = focus_order
        self._fact_manager = fact_manager
        self._run_limit = run_limit

    def set_focus_order(self, modules: list[str]) -> None:
        """Replace the evaluator's focus order."""
        self._focus_order = list(modules)

    def evaluate(self) -> tuple[EvaluationResult, LogLevel]:
        """Run the full evaluation sequence.

        Returns:
            Tuple of the :class:`EvaluationResult` and the winning
            decision's ``then.log`` level, which the caller uses to decide
            how much of the evaluation to write to the audit sink.
        """
        start_ns = time.perf_counter_ns()

        # Snapshot env once at evaluation entry for atomic-swap safety (design D1).
        env = self._env_provider()

        try:
            self._setup_focus_stack(env)
            if self._fact_manager is not None:
                self._fact_manager.cleanup_expired()
            self._run(env)

            decision, reason, metadata, log_level = self._read_decision(env)
            rule_trace, module_trace = self._capture_trace(env)

            end_ns = time.perf_counter_ns()
            duration_us = (end_ns - start_ns) // 1000

            return (
                EvaluationResult(
                    decision=decision,
                    reason=reason,
                    rule_trace=rule_trace,
                    module_trace=module_trace,
                    duration_us=duration_us,
                    metadata=metadata,
                ),
                log_level,
            )
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationError(
                f"Evaluation failed: {exc}",
            ) from exc
        finally:
            # Always retract decision facts, including on the error paths
            # above: a leftover ``__fathom_decision`` fact wedges every
            # later evaluate() with a stale or unparseable decision.
            self._cleanup_decision_facts(env)

    def _run(self, env: clips.Environment) -> None:
        """Run the agenda to quiescence, honouring the activation budget."""
        if self._run_limit is None:
            env.run()
            return
        fired = env.run(self._run_limit)
        if fired >= self._run_limit and next(env.activations(), None) is not None:
            raise EvaluationLimitError(
                f"evaluation exceeded run_limit of {self._run_limit} activations "
                "with activations still pending (non-terminating ruleset?)"
            )

    def _setup_focus_stack(self, env: clips.Environment) -> None:
        """Push modules onto the CLIPS focus stack in reverse order.

        focus_order=[A, B, C] → ``(focus C B A)`` so A gets focus first.
        """
        if not self._focus_order:
            return
        reversed_modules = " ".join(reversed(self._focus_order))
        env.eval(f"(focus {reversed_modules})")

    def _capture_trace(self, env: clips.Environment) -> tuple[list[str], list[str]]:
        """Capture rule trace and module trace from decision facts.

        Each ``__fathom_decision`` fact has a ``rule`` slot with
        ``"module::rule_name"`` format. Collects all in assertion order.

        Returns:
            Tuple of (rule_trace, module_trace).
        """
        rule_trace: list[str] = []
        module_trace: list[str] = []
        seen_modules: set[str] = set()

        for fact in self._iter_decision_facts(env):
            rule_ref = str(fact["rule"])
            if rule_ref:
                rule_trace.append(rule_ref)
                # Extract module from "module::rule_name"
                if "::" in rule_ref:
                    module = rule_ref.split("::")[0]
                    if module not in seen_modules:
                        seen_modules.add(module)
                        module_trace.append(module)

        return rule_trace, module_trace

    def _read_decision(
        self, env: clips.Environment
    ) -> tuple[str | None, str | None, dict[str, str], LogLevel]:
        """Read the winning decision from ``__fathom_decision`` facts.

        Last-write-wins: the last fact in the list is the winning decision.
        Falls back to ``default_decision`` if no decision facts exist.

        Returns:
            Tuple of (decision, reason, metadata, log_level). ``log_level``
            is the winning rule's ``then.log`` value; a default decision
            (no rule fired) reports :attr:`LogLevel.SUMMARY`.
        """
        facts = list(self._iter_decision_facts(env))

        if not facts:
            if self._default_decision is not None:
                return (
                    self._default_decision,
                    "default decision (no rules fired)",
                    {},
                    LogLevel.SUMMARY,
                )
            return None, None, {}, LogLevel.SUMMARY

        # Last fact wins
        winner = facts[-1]
        action = str(winner["action"])
        reason = str(winner["reason"])
        metadata_raw = str(winner["metadata"])
        try:
            log_level = LogLevel(str(winner["log-level"]))
        except ValueError as exc:
            raise EvaluationError(
                f"invalid log-level in __fathom_decision: {exc}"
            ) from exc

        # Parse metadata (stored as JSON string in CLIPS). The only producer
        # is ThenBlock.metadata, which is dict[str, str], and the public
        # EvaluationResult/AuditRecord models declare the same — so validate
        # the shape here rather than letting a pydantic ValidationError escape
        # from inside the error boundary as an unrelated-looking failure.
        metadata: dict[str, str] = {}
        if metadata_raw:
            try:
                parsed = json.loads(metadata_raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise EvaluationError(
                    f"invalid metadata encoding in __fathom_decision: {exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise EvaluationError(
                    "invalid metadata in __fathom_decision: expected a JSON "
                    f"object, got {type(parsed).__name__}"
                )
            for key, value in parsed.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise EvaluationError(
                        "invalid metadata in __fathom_decision: every key and "
                        f"value must be a string, got {key!r}: {value!r}"
                    )
            metadata = parsed

        return action, reason, metadata, log_level

    def _cleanup_decision_facts(self, env: clips.Environment) -> None:
        """Retract all ``__fathom_decision`` facts from working memory."""
        for fact in list(self._iter_decision_facts(env)):
            fact.retract()

    def _iter_decision_facts(self, env: clips.Environment) -> Any:
        """Iterate over all ``__fathom_decision`` facts in working memory."""
        template = env.find_template("__fathom_decision")
        return template.facts()
