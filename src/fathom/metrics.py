"""Prometheus metrics for the Fathom runtime.

Provides :class:`MetricsCollector` which wraps ``prometheus_client``
counters, histograms, and gauges.  When the library is not installed
or metrics are disabled, all methods become no-ops with zero overhead.

Enable via ``FATHOM_METRICS=1`` environment variable or
``Engine(metrics=True)``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

try:
    from prometheus_client import Counter, Gauge, Histogram

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

if TYPE_CHECKING:
    from fathom.models import EvaluationResult


class MetricsCollector:
    """Collects Prometheus metrics. No-op if prometheus_client not installed."""

    def __init__(self, enabled: bool = False) -> None:
        # Also honour the FATHOM_METRICS env var.
        if not enabled and os.environ.get("FATHOM_METRICS") != "1":
            self._noop = True
            return
        if not _HAS_PROMETHEUS:
            self._noop = True
            return

        self._noop = False

        self.evaluations_total: Counter = Counter(
            "fathom_evaluations_total",
            "Total number of rule evaluations",
            ["decision", "module"],
        )
        self.evaluation_duration: Histogram = Histogram(
            "fathom_evaluation_duration_seconds",
            "Duration of rule evaluations in seconds",
            ["ruleset"],
        )
        self.facts_asserted: Counter = Counter(
            "fathom_facts_asserted_total",
            "Total number of facts asserted",
            ["template"],
        )
        self.working_memory_facts: Gauge = Gauge(
            "fathom_working_memory_facts",
            "Current number of facts in working memory (aggregated across sessions)",
            ["template"],
        )
        self.rules_fired: Counter = Counter(
            "fathom_rules_fired_total",
            "Total number of rule firings",
            ["rule", "module"],
        )
        self.denials_total: Counter = Counter(
            "fathom_denials_total",
            "Total number of denial decisions",
            ["rule", "reason"],
        )
        self.sessions_active: Gauge = Gauge(
            "fathom_sessions_active",
            "Number of currently active sessions",
        )
        self.templates_loaded: Counter = Counter(
            "fathom_templates_loaded_total",
            "Total number of templates loaded",
        )
        self.modules_loaded: Counter = Counter(
            "fathom_modules_loaded_total",
            "Total number of modules loaded",
        )
        self.functions_loaded: Counter = Counter(
            "fathom_functions_loaded_total",
            "Total number of functions loaded",
        )
        self.rules_loaded: Counter = Counter(
            "fathom_rules_loaded_total",
            "Total number of rules loaded",
        )
        self.facts_retracted: Counter = Counter(
            "fathom_facts_retracted_total",
            "Total number of facts retracted",
        )

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_evaluation(
        self,
        result: EvaluationResult,
        session_id: str,
        *,
        ruleset: str = "default",
    ) -> None:
        """Record a completed evaluation."""
        if self._noop:
            return
        self.evaluations_total.labels(
            decision=result.decision,
            module=ruleset,
        ).inc()
        if result.duration_us:
            self.evaluation_duration.labels(ruleset=ruleset).observe(
                result.duration_us / 1_000_000,
            )

    def record_fact_asserted(self, template: str) -> None:
        """Record a fact assertion."""
        if self._noop:
            return
        self.facts_asserted.labels(template=template).inc()

    def record_rule_fired(self, rule: str, module: str = "MAIN") -> None:
        """Record a rule firing."""
        if self._noop:
            return
        self.rules_fired.labels(rule=rule, module=module).inc()

    def record_denial(self, rule: str, reason: str) -> None:
        """Record a denial decision."""
        if self._noop:
            return
        self.denials_total.labels(rule=rule, reason=reason).inc()

    def set_working_memory_facts(
        self,
        template: str,
        count: int,
    ) -> None:
        """Set the working-memory fact count for a template across all sessions."""
        if self._noop:
            return
        self.working_memory_facts.labels(template=template).set(count)

    def inc_sessions_active(self) -> None:
        """Increment active session count."""
        if self._noop:
            return
        self.sessions_active.inc()

    def dec_sessions_active(self) -> None:
        """Decrement active session count."""
        if self._noop:
            return
        self.sessions_active.dec()

    def record_templates_loaded(self, count: int) -> None:
        """Record templates loaded."""
        if self._noop:
            return
        self.templates_loaded.inc(count)

    def record_modules_loaded(self, count: int) -> None:
        """Record modules loaded."""
        if self._noop:
            return
        self.modules_loaded.inc(count)

    def record_functions_loaded(self, count: int) -> None:
        """Record functions loaded."""
        if self._noop:
            return
        self.functions_loaded.inc(count)

    def record_rules_loaded(self, count: int) -> None:
        """Record rules loaded."""
        if self._noop:
            return
        self.rules_loaded.inc(count)

    def record_facts_retracted(self, count: int) -> None:
        """Record facts retracted."""
        if self._noop:
            return
        self.facts_retracted.inc(count)
