"""Prometheus metrics for the Fathom runtime.

Provides :class:`MetricsCollector` which wraps ``prometheus_client``
counters, histograms, and gauges.  When the library is not installed
or metrics are disabled, all methods become no-ops with zero overhead.

Enable via ``FATHOM_METRICS=1`` environment variable or
``Engine(metrics=True)``.
"""

from __future__ import annotations

import contextlib
import os
import threading
from typing import TYPE_CHECKING, Any

try:
    from prometheus_client import Counter, Gauge, Histogram

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

if TYPE_CHECKING:
    from fathom.models import EvaluationResult


# ---------------------------------------------------------------------------
# Metric families are process-wide
# ---------------------------------------------------------------------------
#
# ``prometheus_client`` refuses to register two families with the same name on
# the default REGISTRY, so building the families inside ``__init__`` made the
# *second* ``MetricsCollector`` in a process raise ``ValueError: Duplicated
# timeseries in CollectorRegistry``. Every Engine builds its own collector, so
# with ``FATHOM_METRICS=1`` the second session engine a SessionStore created
# crashed at construction.
#
# The families are process-global by nature — a Prometheus exposition has one
# ``fathom_evaluations_total``, not one per Engine — so they are built once and
# shared. Collectors stay per-Engine; only the underlying families are shared.

_FAMILY_CACHE: dict[str, Any] | None = None
_FAMILY_LOCK = threading.Lock()


def _build_families() -> dict[str, Any]:
    """Construct every Fathom metric family. Called at most once per process."""
    return {
        "evaluations_total": Counter(
            "fathom_evaluations_total",
            "Total number of rule evaluations",
            ["decision", "module"],
        ),
        "evaluation_duration": Histogram(
            "fathom_evaluation_duration_seconds",
            "Duration of rule evaluations in seconds",
            ["ruleset"],
        ),
        "facts_asserted": Counter(
            "fathom_facts_asserted_total",
            "Total number of facts asserted",
            ["template"],
        ),
        "working_memory_facts": Gauge(
            "fathom_working_memory_facts",
            "Current number of facts in working memory (aggregated across sessions)",
            ["template"],
        ),
        "rules_fired": Counter(
            "fathom_rules_fired_total",
            "Total number of rule firings",
            ["rule", "module"],
        ),
        "denials_total": Counter(
            "fathom_denials_total",
            "Total number of denial decisions",
            # Labelled by rule identity only. The rendered deny *reason*
            # was tried here and is unusable: `_compile_reason` interpolates
            # bound slot values into the reason string, so a caller-supplied
            # fact value becomes a label value and every distinct request
            # mints a permanent time series (prometheus_client never evicts
            # Counter children). That is an unbounded memory-growth vector
            # in the REST/gRPC servers and a cardinality bomb on the scraper.
            # `rule` and `module` are bounded by the loaded ruleset.
            ["rule", "module"],
        ),
        "sessions_active": Gauge(
            "fathom_sessions_active",
            "Number of currently active sessions",
        ),
        "templates_loaded": Counter(
            "fathom_templates_loaded_total",
            "Total number of templates loaded",
        ),
        "modules_loaded": Counter(
            "fathom_modules_loaded_total",
            "Total number of modules loaded",
        ),
        "functions_loaded": Counter(
            "fathom_functions_loaded_total",
            "Total number of functions loaded",
        ),
        "rules_loaded": Counter(
            "fathom_rules_loaded_total",
            "Total number of rules loaded",
        ),
        "facts_retracted": Counter(
            "fathom_facts_retracted_total",
            "Total number of facts retracted",
        ),
    }


def _families() -> dict[str, Any]:
    """Return the shared metric families, building them on first use."""
    global _FAMILY_CACHE
    with _FAMILY_LOCK:
        if _FAMILY_CACHE is None:
            _FAMILY_CACHE = _build_families()
        return _FAMILY_CACHE


def _reset_families_for_testing() -> None:
    """Drop the cached families so the next collector rebuilds them.

    Also unregisters them from the default ``REGISTRY``. Dropping the cache
    alone would leave the old families registered, so the *next* build would
    raise ``Duplicated timeseries`` — which makes the whole thing sensitive to
    test ordering. Families built against a private registry are simply not in
    ``REGISTRY``, and unregistering those is a no-op.

    Tests only: calling this in production orphans the families already handed
    to live Engines.
    """
    global _FAMILY_CACHE
    with _FAMILY_LOCK:
        if _FAMILY_CACHE is not None and _HAS_PROMETHEUS:
            from prometheus_client import REGISTRY

            for family in _FAMILY_CACHE.values():
                with contextlib.suppress(Exception):
                    REGISTRY.unregister(family)
        _FAMILY_CACHE = None


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

        families = _families()
        self.evaluations_total: Counter = families["evaluations_total"]
        self.evaluation_duration: Histogram = families["evaluation_duration"]
        self.facts_asserted: Counter = families["facts_asserted"]
        self.working_memory_facts: Gauge = families["working_memory_facts"]
        self.rules_fired: Counter = families["rules_fired"]
        self.denials_total: Counter = families["denials_total"]
        self.sessions_active: Gauge = families["sessions_active"]
        self.templates_loaded: Counter = families["templates_loaded"]
        self.modules_loaded: Counter = families["modules_loaded"]
        self.functions_loaded: Counter = families["functions_loaded"]
        self.rules_loaded: Counter = families["rules_loaded"]
        self.facts_retracted: Counter = families["facts_retracted"]

    @property
    def enabled(self) -> bool:
        """True when this collector actually records.

        Lets callers skip work that only exists to feed a metric — counting
        working-memory facts means querying CLIPS, which is not free.
        """
        return not self._noop

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_rule_ref(rule_ref: str) -> tuple[str, str]:
        """Split a ``"module::rule"`` trace entry into ``(module, rule)``."""
        module, sep, rule = rule_ref.partition("::")
        if not sep:
            return "MAIN", rule_ref
        return module, rule

    def record_evaluation(
        self,
        result: EvaluationResult,
        session_id: str,
        *,
        ruleset: str = "default",
    ) -> None:
        """Record a completed evaluation, its rule firings, and any denial."""
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
        for rule_ref in result.rule_trace:
            module, rule = self._split_rule_ref(rule_ref)
            self.record_rule_fired(rule, module)
        if result.decision == "deny":
            # Last-write-wins: the final decision fact carries the winning rule.
            if result.rule_trace:
                module, rule = self._split_rule_ref(result.rule_trace[-1])
            else:
                module, rule = "<default>", "<default>"
            self.record_denial(rule, module)

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

    def record_denial(self, rule: str, module: str = "MAIN") -> None:
        """Record a denial decision.

        Deliberately does NOT take the rendered deny reason: reasons
        interpolate runtime fact values, so using one as a label value lets
        a caller mint unbounded Prometheus time series. Both labels here are
        bounded by the loaded ruleset.
        """
        if self._noop:
            return
        self.denials_total.labels(rule=rule, module=module).inc()

    def set_working_memory_facts(
        self,
        template: str,
        count: int,
    ) -> None:
        """Set the working-memory fact count for a template across all sessions."""
        if self._noop:
            return
        self.working_memory_facts.labels(template=template).set(count)

    def set_sessions_active(self, count: int) -> None:
        """Set the live session count.

        Preferred over :meth:`inc_sessions_active` /
        :meth:`dec_sessions_active`: the store publishes ``len(self._sessions)``
        directly, so a missed decrement on an eviction path cannot leave the
        gauge permanently wrong.
        """
        if self._noop:
            return
        self.sessions_active.set(count)

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
