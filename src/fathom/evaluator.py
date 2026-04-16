"""Fathom Evaluator — forward-chain evaluation via CLIPS."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from fathom.errors import EvaluationError
from fathom.models import EvaluationResult

if TYPE_CHECKING:
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
        env: clips.Environment,
        default_decision: str | None,
        focus_order: list[str],
        fact_manager: FactManager | None = None,
    ) -> None:
        self._env = env
        self._default_decision = default_decision
        self._focus_order = focus_order
        self._fact_manager = fact_manager

    def set_focus_order(self, modules: list[str]) -> None:
        """Replace the evaluator's focus order."""
        self._focus_order = list(modules)

    def evaluate(self) -> EvaluationResult:
        """Run the full evaluation sequence and return the result."""
        start_ns = time.perf_counter_ns()

        try:
            self._setup_focus_stack()
            if self._fact_manager is not None:
                self._fact_manager.cleanup_expired()
            self._env.run()

            decision, reason, metadata = self._read_decision()
            rule_trace, module_trace = self._capture_trace()
            self._cleanup_decision_facts()
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationError(
                f"Evaluation failed: {exc}",
            ) from exc

        end_ns = time.perf_counter_ns()
        duration_us = (end_ns - start_ns) // 1000

        return EvaluationResult(
            decision=decision,
            reason=reason,
            rule_trace=rule_trace,
            module_trace=module_trace,
            duration_us=duration_us,
            metadata=metadata,
        )

    def _setup_focus_stack(self) -> None:
        """Push modules onto the CLIPS focus stack in reverse order.

        focus_order=[A, B, C] → ``(focus C B A)`` so A gets focus first.
        """
        if not self._focus_order:
            return
        reversed_modules = " ".join(reversed(self._focus_order))
        self._env.eval(f"(focus {reversed_modules})")

    def _capture_trace(self) -> tuple[list[str], list[str]]:
        """Capture rule trace and module trace from decision facts.

        Each ``__fathom_decision`` fact has a ``rule`` slot with
        ``"module::rule_name"`` format. Collects all in assertion order.

        Returns:
            Tuple of (rule_trace, module_trace).
        """
        rule_trace: list[str] = []
        module_trace: list[str] = []
        seen_modules: set[str] = set()

        for fact in self._iter_decision_facts():
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

    def _read_decision(self) -> tuple[str | None, str | None, dict[str, Any]]:
        """Read the winning decision from ``__fathom_decision`` facts.

        Last-write-wins: the last fact in the list is the winning decision.
        Falls back to ``default_decision`` if no decision facts exist.

        Returns:
            Tuple of (decision, reason, metadata).
        """
        facts = list(self._iter_decision_facts())

        if not facts:
            if self._default_decision is not None:
                return self._default_decision, "default decision (no rules fired)", {}
            return None, None, {}

        # Last fact wins
        winner = facts[-1]
        action = str(winner["action"])
        reason = str(winner["reason"])
        metadata_raw = str(winner["metadata"])

        # Parse metadata (stored as JSON string in CLIPS)
        metadata: dict[str, Any] = {}
        if metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except (json.JSONDecodeError, ValueError) as exc:
                raise EvaluationError(
                    f"invalid metadata encoding in __fathom_decision: {exc}"
                ) from exc

        return action, reason, metadata

    def _cleanup_decision_facts(self) -> None:
        """Retract all ``__fathom_decision`` facts from working memory."""
        for fact in list(self._iter_decision_facts()):
            fact.retract()

    def _iter_decision_facts(self) -> Any:
        """Iterate over all ``__fathom_decision`` facts in working memory."""
        template = self._env.find_template("__fathom_decision")
        return template.facts()
