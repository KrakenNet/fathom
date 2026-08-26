"""Fathom Evaluator — forward-chain evaluation via CLIPS."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from fathom.errors import EvaluationError, EvaluationLimitError
from fathom.models import AssertedFact, EvaluationResult, LogLevel, MatchEvidence

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
        match_evidence: bool = False,
    ) -> None:
        self._env_provider = env_provider
        self._default_decision = default_decision
        self._focus_order = focus_order
        self._fact_manager = fact_manager
        self._run_limit = run_limit
        self._match_evidence = match_evidence

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
                    match_evidence=self._capture_match_evidence(env),
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
            if self._match_evidence:
                for fact in list(self._iter_evidence_facts(env)):
                    fact.retract()

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
        """Give the modules the focus in the order the author wrote them.

        ``(focus A B C)`` focuses A first and queues B and C behind it, so
        ``focus_order`` maps straight through. This used to emit the list
        reversed on the belief that a later name ended up on top of the
        stack; it does not, so ``focus_order: [A, B]`` ran B first -- the
        opposite of what the key documents. Since the last rule to fire
        writes the decision, the module listed *first* got the final say.
        """
        if not self._focus_order:
            return
        modules = " ".join(self._focus_order)
        env.eval(f"(focus {modules})")

    def _capture_trace(self, env: clips.Environment) -> tuple[list[str], list[str]]:
        """Capture rule trace and module trace from decision facts.

        Every compiled rule asserts one ``__fathom_decision`` per firing --
        a forward-chaining rule with ``action none``, a deciding rule with
        its own action -- so reading them in assertion order replays the
        firings in order.

        Assert-only rules used to emit nothing here, which left the rule
        that derived the fact a later rule decided on missing from the trace
        and from the signed audit record: the one step that explains the
        decision.

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
        # ``action none`` is a rule that fired without rendering a decision;
        # it belongs in the trace but is not a candidate to win here.
        facts = [f for f in self._iter_decision_facts(env) if str(f["action"]) != "none"]

        if not facts:
            if self._default_decision is not None:
                return (
                    self._default_decision,
                    "default decision (no rule rendered a decision)",
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
            raise EvaluationError(f"invalid log-level in __fathom_decision: {exc}") from exc

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

    def _iter_evidence_facts(self, env: clips.Environment) -> Any:
        """Iterate over all ``__fathom_evidence`` facts in working memory."""
        return env.find_template("__fathom_evidence").facts()

    def _capture_match_evidence(self, env: clips.Environment) -> list[MatchEvidence]:
        """Resolve each firing's recorded fact indices back to fact snapshots.

        The compiler asserts one ``__fathom_evidence`` fact per firing,
        holding the rule name and the ``fact-index`` of every fact that
        matched its LHS. Nothing retracts during a run, so every index still
        resolves against working memory here.
        """
        if not self._match_evidence:
            return []
        firings = list(self._iter_evidence_facts(env))
        if not firings:
            return []
        by_index = {fact.index: fact for fact in env.facts()}
        return [
            MatchEvidence(
                rule=firing["rule"],
                facts=[
                    AssertedFact(template=matched.template.name, slots=dict(matched))
                    for index in firing["facts"]
                    if (matched := by_index.get(index)) is not None
                ],
            )
            for firing in firings
        ]
