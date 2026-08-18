"""Unit tests for MetricsCollector."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from fathom.metrics import MetricsCollector
from fathom.models import EvaluationResult

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from prometheus_client import CollectorRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_eval_result(
    decision: str = "allow",
    duration_us: int = 5000,
    rule_trace: list[str] | None = None,
    reason: str = "",
) -> EvaluationResult:
    """Return a real EvaluationResult with the given fields."""
    return EvaluationResult(
        decision=decision,
        reason=reason,
        rule_trace=rule_trace if rule_trace is not None else [],
        duration_us=duration_us,
    )


# ---------------------------------------------------------------------------
# No-op mode (enabled=False, no env var)
# ---------------------------------------------------------------------------


class TestNoopMode:
    """All methods must be callable without error when disabled."""

    def test_noop_flag_set(self) -> None:
        mc = MetricsCollector(enabled=False)
        assert mc._noop is True

    def test_record_evaluation_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_evaluation(_make_eval_result(), session_id="s1")

    def test_record_fact_asserted_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_fact_asserted("my_template")

    def test_record_rule_fired_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_rule_fired("rule1", "MAIN")

    def test_record_denial_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_denial("deny_rule", "bad request")

    def test_set_working_memory_facts_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.set_working_memory_facts(template="template", count=42)

    def test_inc_dec_sessions_active_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.inc_sessions_active()
        mc.dec_sessions_active()

    def test_record_templates_loaded_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_templates_loaded(3)

    def test_record_modules_loaded_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_modules_loaded(2)

    def test_record_functions_loaded_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_functions_loaded(5)

    def test_record_rules_loaded_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_rules_loaded(10)

    def test_record_facts_retracted_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        mc.record_facts_retracted(1)

    def test_no_prometheus_attributes_in_noop(self) -> None:
        mc = MetricsCollector(enabled=False)
        assert not hasattr(mc, "evaluations_total")
        assert not hasattr(mc, "evaluation_duration")


# ---------------------------------------------------------------------------
# Enabled mode (prometheus_client available)
# ---------------------------------------------------------------------------


class TestEnabledMode:
    """Verify that enabled=True creates real Prometheus objects and records."""

    @pytest.fixture(autouse=True)
    def _isolate_prometheus(self) -> None:  # type: ignore[return]
        """Each test gets a fresh prometheus_client collector registry."""
        # prometheus_client uses a global default registry; wipe metrics
        # between tests by patching the module-level constructors.
        import prometheus_client
        from prometheus_client import CollectorRegistry

        import fathom.metrics as metrics_module

        self._registry = CollectorRegistry()
        reg = self._registry

        def _counter(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Counter:
            return prometheus_client.Counter(name, doc, labelnames=labelnames, registry=reg)

        def _histogram(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Histogram:
            return prometheus_client.Histogram(name, doc, labelnames=labelnames, registry=reg)

        def _gauge(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Gauge:
            return prometheus_client.Gauge(name, doc, labelnames=labelnames, registry=reg)

        self._patches = [
            patch("fathom.metrics.Counter", side_effect=_counter),
            patch("fathom.metrics.Histogram", side_effect=_histogram),
            patch("fathom.metrics.Gauge", side_effect=_gauge),
        ]
        for p in self._patches:
            p.start()
        # Metric families are cached process-wide (so a second Engine cannot
        # re-register them and crash); drop the cache so this test's private
        # registry gets its own freshly-built families.
        metrics_module._reset_families_for_testing()
        yield
        for p in self._patches:
            p.stop()
        metrics_module._reset_families_for_testing()

    def test_enabled_flag(self) -> None:
        mc = MetricsCollector(enabled=True)
        assert mc._noop is False

    def test_prometheus_attributes_created(self) -> None:
        mc = MetricsCollector(enabled=True)
        assert hasattr(mc, "evaluations_total")
        assert hasattr(mc, "evaluation_duration")
        assert hasattr(mc, "facts_asserted")
        assert hasattr(mc, "working_memory_facts")
        assert hasattr(mc, "rules_fired")
        assert hasattr(mc, "denials_total")
        assert hasattr(mc, "sessions_active")
        assert hasattr(mc, "templates_loaded")
        assert hasattr(mc, "modules_loaded")
        assert hasattr(mc, "functions_loaded")
        assert hasattr(mc, "rules_loaded")
        assert hasattr(mc, "facts_retracted")

    def test_record_evaluation_increments(self) -> None:
        mc = MetricsCollector(enabled=True)
        result = _make_eval_result(decision="allow", duration_us=2000)
        mc.record_evaluation(result, session_id="s1", ruleset="test")
        val = self._registry.get_sample_value(
            "fathom_evaluations_total",
            labels={"decision": "allow", "module": "test"},
        )
        assert val == 1.0

    def test_record_evaluation_observes_duration(self) -> None:
        mc = MetricsCollector(enabled=True)
        result = _make_eval_result(duration_us=1_000_000)
        mc.record_evaluation(result, session_id="s1", ruleset="dur")
        val = self._registry.get_sample_value(
            "fathom_evaluation_duration_seconds_sum",
            labels={"ruleset": "dur"},
        )
        assert val == pytest.approx(1.0)

    def test_record_evaluation_zero_duration_skipped(self) -> None:
        mc = MetricsCollector(enabled=True)
        result = _make_eval_result(duration_us=0)
        mc.record_evaluation(result, session_id="s1")
        # duration_us == 0 is falsy, so observe is not called
        val = self._registry.get_sample_value(
            "fathom_evaluation_duration_seconds_sum",
            labels={"ruleset": "default"},
        )
        # Should be None (not observed) or 0
        assert val is None or val == 0.0

    def test_record_fact_asserted(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_fact_asserted("user_action")
        val = self._registry.get_sample_value(
            "fathom_facts_asserted_total",
            labels={"template": "user_action"},
        )
        assert val == 1.0

    def test_record_rule_fired(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_rule_fired("allow_rule", "security")
        val = self._registry.get_sample_value(
            "fathom_rules_fired_total",
            labels={"rule": "allow_rule", "module": "security"},
        )
        assert val == 1.0

    def test_record_rule_fired_default_module(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_rule_fired("r1")
        val = self._registry.get_sample_value(
            "fathom_rules_fired_total",
            labels={"rule": "r1", "module": "MAIN"},
        )
        assert val == 1.0

    def test_record_denial(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_denial("deny_all", "governance")
        val = self._registry.get_sample_value(
            "fathom_denials_total",
            labels={"rule": "deny_all", "module": "governance"},
        )
        assert val == 1.0

    def test_set_working_memory_facts(self) -> None:
        mc = MetricsCollector(enabled=True)
        # session_id label dropped (C5: unbounded cardinality); aggregated by template only
        mc.set_working_memory_facts(template="event", count=7)
        val = self._registry.get_sample_value(
            "fathom_working_memory_facts",
            labels={"template": "event"},
        )
        assert val == 7.0

    def test_sessions_active_inc_dec(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.inc_sessions_active()
        mc.inc_sessions_active()
        mc.dec_sessions_active()
        val = self._registry.get_sample_value("fathom_sessions_active", labels={})
        assert val == 1.0

    def test_record_templates_loaded(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_templates_loaded(5)
        val = self._registry.get_sample_value(
            "fathom_templates_loaded_total",
            labels={},
        )
        assert val == 5.0

    def test_record_modules_loaded(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_modules_loaded(3)
        val = self._registry.get_sample_value(
            "fathom_modules_loaded_total",
            labels={},
        )
        assert val == 3.0

    def test_record_functions_loaded(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_functions_loaded(8)
        val = self._registry.get_sample_value(
            "fathom_functions_loaded_total",
            labels={},
        )
        assert val == 8.0

    def test_record_rules_loaded(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_rules_loaded(12)
        val = self._registry.get_sample_value(
            "fathom_rules_loaded_total",
            labels={},
        )
        assert val == 12.0

    def test_record_facts_retracted(self) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_facts_retracted(4)
        val = self._registry.get_sample_value(
            "fathom_facts_retracted_total",
            labels={},
        )
        assert val == 4.0


# ---------------------------------------------------------------------------
# Env var activation (FATHOM_METRICS=1)
# ---------------------------------------------------------------------------


class TestEnvVarActivation:
    """FATHOM_METRICS=1 should enable metrics even when enabled=False."""

    @pytest.fixture(autouse=True)
    def _isolate_prometheus(self) -> None:  # type: ignore[return]
        import prometheus_client
        from prometheus_client import CollectorRegistry

        import fathom.metrics as metrics_module

        self._registry = CollectorRegistry()
        reg = self._registry

        def _counter(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Counter:
            return prometheus_client.Counter(name, doc, labelnames=labelnames, registry=reg)

        def _histogram(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Histogram:
            return prometheus_client.Histogram(name, doc, labelnames=labelnames, registry=reg)

        def _gauge(
            name: str,
            doc: str,
            labelnames: tuple[str, ...] = (),
            registry: object = None,
            **kw: object,
        ) -> prometheus_client.Gauge:
            return prometheus_client.Gauge(name, doc, labelnames=labelnames, registry=reg)

        self._patches = [
            patch("fathom.metrics.Counter", side_effect=_counter),
            patch("fathom.metrics.Histogram", side_effect=_histogram),
            patch("fathom.metrics.Gauge", side_effect=_gauge),
        ]
        for p in self._patches:
            p.start()
        # Metric families are cached process-wide (so a second Engine cannot
        # re-register them and crash); drop the cache so this test's private
        # registry gets its own freshly-built families.
        metrics_module._reset_families_for_testing()
        yield
        for p in self._patches:
            p.stop()
        metrics_module._reset_families_for_testing()

    def test_env_var_enables_metrics(self) -> None:
        with patch.dict(os.environ, {"FATHOM_METRICS": "1"}):
            mc = MetricsCollector(enabled=False)
        assert mc._noop is False
        assert hasattr(mc, "evaluations_total")

    def test_env_var_not_set_stays_noop(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            mc = MetricsCollector(enabled=False)
        assert mc._noop is True

    def test_env_var_wrong_value_stays_noop(self) -> None:
        with patch.dict(os.environ, {"FATHOM_METRICS": "true"}):
            mc = MetricsCollector(enabled=False)
        assert mc._noop is True

    def test_env_var_zero_stays_noop(self) -> None:
        with patch.dict(os.environ, {"FATHOM_METRICS": "0"}):
            mc = MetricsCollector(enabled=False)
        assert mc._noop is True


# ---------------------------------------------------------------------------
# No prometheus_client installed
# ---------------------------------------------------------------------------


class TestNoPrometheus:
    """When _HAS_PROMETHEUS is False, enabled=True still falls back to noop."""

    def test_enabled_but_no_prometheus_is_noop(self) -> None:
        with patch("fathom.metrics._HAS_PROMETHEUS", False):
            mc = MetricsCollector(enabled=True)
        assert mc._noop is True

    def test_env_var_set_but_no_prometheus_is_noop(self) -> None:
        with (
            patch("fathom.metrics._HAS_PROMETHEUS", False),
            patch.dict(os.environ, {"FATHOM_METRICS": "1"}),
        ):
            mc = MetricsCollector(enabled=False)
        assert mc._noop is True


# ---------------------------------------------------------------------------
# Cardinality safety — working_memory_facts must not carry session_id
# ---------------------------------------------------------------------------


@pytest.fixture()
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a fresh CollectorRegistry so module-level tests don't conflict."""
    import prometheus_client
    from prometheus_client import CollectorRegistry


    reg = CollectorRegistry()

    def _counter(
        name: str,
        doc: str,
        labelnames: tuple[str, ...] = (),
        registry: object = None,
        **kw: object,
    ) -> prometheus_client.Counter:
        return prometheus_client.Counter(name, doc, labelnames=labelnames, registry=reg)

    def _histogram(
        name: str,
        doc: str,
        labelnames: tuple[str, ...] = (),
        registry: object = None,
        **kw: object,
    ) -> prometheus_client.Histogram:
        return prometheus_client.Histogram(name, doc, labelnames=labelnames, registry=reg)

    def _gauge(
        name: str,
        doc: str,
        labelnames: tuple[str, ...] = (),
        registry: object = None,
        **kw: object,
    ) -> prometheus_client.Gauge:
        return prometheus_client.Gauge(name, doc, labelnames=labelnames, registry=reg)

    monkeypatch.setattr("fathom.metrics.Counter", _counter)
    monkeypatch.setattr("fathom.metrics.Histogram", _histogram)
    monkeypatch.setattr("fathom.metrics.Gauge", _gauge)


def test_working_memory_facts_has_no_session_id_label(
    monkeypatch: pytest.MonkeyPatch,
    _isolated_registry: None,
) -> None:
    """The gauge must only be labeled by template to avoid cardinality bombs."""
    monkeypatch.setenv("FATHOM_METRICS", "1")
    from fathom.metrics import MetricsCollector

    m = MetricsCollector(enabled=True)
    assert m.working_memory_facts._labelnames == ("template",)


def test_cardinality_stable_across_many_sessions(
    monkeypatch: pytest.MonkeyPatch,
    _isolated_registry: None,
) -> None:
    monkeypatch.setenv("FATHOM_METRICS", "1")
    from fathom.metrics import MetricsCollector

    m = MetricsCollector(enabled=True)
    for i in range(1000):
        m.set_working_memory_facts(template="agent", count=i)
    child_count = len(m.working_memory_facts._metrics)
    assert child_count == 1


def test_denials_total_has_no_reason_label(_isolated_registry: None) -> None:
    """A deny reason interpolates runtime fact values — it must never be a label."""
    from fathom.metrics import MetricsCollector

    m = MetricsCollector(enabled=True)
    assert m.denials_total._labelnames == ("rule", "module")
    assert "reason" not in m.denials_total._labelnames


def test_denials_cardinality_stable_across_distinct_reasons(
    monkeypatch: pytest.MonkeyPatch,
    _isolated_registry: None,
) -> None:
    """1000 evaluations whose deny reasons all differ must yield ONE time series.

    Deny reasons are built by `_compile_reason`, which interpolates bound
    slot values, so a caller controls the string. If it reaches a label, a
    remote caller can grow the process's metric registry without bound.
    """
    monkeypatch.setenv("FATHOM_METRICS", "1")
    from fathom.metrics import MetricsCollector

    m = MetricsCollector(enabled=True)
    for i in range(1000):
        m.record_evaluation(
            _make_eval_result(
                decision="deny",
                reason=f"user user{i} may not delete",
                rule_trace=["governance::deny-delete"],
            ),
            session_id="s1",
        )
    assert len(m.denials_total._metrics) == 1


# ---------------------------------------------------------------------------
# Evaluation wiring — rules_fired and denials_total must actually move
# ---------------------------------------------------------------------------


@pytest.fixture()
def prom_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[CollectorRegistry]:
    """Point the metrics module at a fresh registry and return it."""
    import prometheus_client
    from prometheus_client import CollectorRegistry

    import fathom.metrics as fathom_metrics

    reg = CollectorRegistry()

    def _factory(ctor: Any) -> Any:
        def _make(name: str, doc: str, labelnames: Any = (), **kw: Any) -> Any:
            return ctor(name, doc, labelnames=labelnames, registry=reg)

        return _make

    monkeypatch.setattr("fathom.metrics.Counter", _factory(prometheus_client.Counter))
    monkeypatch.setattr("fathom.metrics.Histogram", _factory(prometheus_client.Histogram))
    monkeypatch.setattr("fathom.metrics.Gauge", _factory(prometheus_client.Gauge))
    # Metric families are cached process-wide (so a second Engine cannot
    # re-register them and crash); drop the cache so the collector built in
    # this test uses ``reg`` rather than families from an earlier test.
    fathom_metrics._reset_families_for_testing()
    yield reg
    fathom_metrics._reset_families_for_testing()


def _write_deny_pack(tmp_path: Path) -> Path:
    """Write a minimal on-disk rule pack whose only rule denies deletes."""
    pack = tmp_path / "pack"
    for sub in ("templates", "modules", "rules"):
        (pack / sub).mkdir(parents=True)
    (pack / "templates" / "request.yaml").write_text(
        "templates:\n"
        "  - name: request\n"
        "    slots:\n"
        "      - name: action\n"
        "        type: symbol\n"
        "      - name: user\n"
        "        type: symbol\n",
        encoding="utf-8",
    )
    (pack / "modules" / "modules.yaml").write_text(
        "modules:\n  - name: governance\nfocus_order:\n  - governance\n",
        encoding="utf-8",
    )
    (pack / "rules" / "access.yaml").write_text(
        "module: governance\n"
        "rules:\n"
        "  - name: deny-delete\n"
        "    when:\n"
        "      - template: request\n"
        "        conditions:\n"
        "          - slot: action\n"
        "            expression: equals(delete)\n"
        "    then:\n"
        "      action: deny\n"
        "      reason: deletes are not permitted\n",
        encoding="utf-8",
    )
    return pack


class TestEvaluationWiring:
    """``record_evaluation`` must feed rules_fired and denials_total."""

    def test_rule_trace_increments_rules_fired(self, prom_registry: CollectorRegistry) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_evaluation(
            _make_eval_result(rule_trace=["governance::allow-read"]),
            session_id="s1",
        )
        val = prom_registry.get_sample_value(
            "fathom_rules_fired_total",
            labels={"rule": "allow-read", "module": "governance"},
        )
        assert val == 1.0

    def test_unqualified_rule_ref_uses_main_module(self, prom_registry: CollectorRegistry) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_evaluation(_make_eval_result(rule_trace=["bare-rule"]), session_id="s1")
        val = prom_registry.get_sample_value(
            "fathom_rules_fired_total",
            labels={"rule": "bare-rule", "module": "MAIN"},
        )
        assert val == 1.0

    def test_deny_increments_denials_total(self, prom_registry: CollectorRegistry) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_evaluation(
            _make_eval_result(
                decision="deny",
                reason="deletes are not permitted",
                rule_trace=["governance::allow-read", "governance::deny-delete"],
            ),
            session_id="s1",
        )
        val = prom_registry.get_sample_value(
            "fathom_denials_total",
            labels={"rule": "deny-delete", "module": "governance"},
        )
        assert val == 1.0

    def test_allow_does_not_increment_denials_total(
        self, prom_registry: CollectorRegistry
    ) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_evaluation(
            _make_eval_result(rule_trace=["governance::allow-read"]),
            session_id="s1",
        )
        assert prom_registry.get_sample_value("fathom_denials_total", labels={}) is None

    def test_default_deny_without_rule_trace(self, prom_registry: CollectorRegistry) -> None:
        mc = MetricsCollector(enabled=True)
        mc.record_evaluation(
            _make_eval_result(decision="deny", reason="default decision (no rules fired)"),
            session_id="s1",
        )
        val = prom_registry.get_sample_value(
            "fathom_denials_total",
            labels={"rule": "<default>", "module": "<default>"},
        )
        assert val == 1.0


class TestEngineEvaluationRecordsMetrics:
    """A real Engine evaluation must leave non-zero samples in the exposition."""

    def test_real_denial_moves_rules_fired_and_denials(
        self,
        tmp_path: Path,
        prom_registry: CollectorRegistry,
    ) -> None:
        from fathom.engine import Engine

        engine = Engine.from_rules(str(_write_deny_pack(tmp_path)), metrics=True)
        engine.assert_fact("request", {"action": "delete", "user": "mallory"})
        result = engine.evaluate()

        assert result.decision == "deny"
        assert prom_registry.get_sample_value(
            "fathom_rules_fired_total",
            labels={"rule": "deny-delete", "module": "governance"},
        ) == 1.0
        assert prom_registry.get_sample_value(
            "fathom_denials_total",
            labels={"rule": "deny-delete", "module": "governance"},
        ) == 1.0


class TestCollectorIsProcessSafe:
    """A second MetricsCollector must not blow up on the shared registry.

    ``prometheus_client`` refuses duplicate family names, and every Engine
    builds its own collector, so with ``FATHOM_METRICS=1`` the second session
    Engine a SessionStore created used to die with ``ValueError: Duplicated
    timeseries in CollectorRegistry`` before it ever served a request.
    """

    def test_many_collectors_construct(self, prom_registry: CollectorRegistry) -> None:
        collectors = [MetricsCollector(enabled=True) for _ in range(5)]
        assert all(c._noop is False for c in collectors)

    def test_collectors_share_one_family(self, prom_registry: CollectorRegistry) -> None:
        first, second = MetricsCollector(enabled=True), MetricsCollector(enabled=True)
        assert first.evaluations_total is second.evaluations_total

    def test_counts_from_two_collectors_aggregate(
        self, prom_registry: CollectorRegistry
    ) -> None:
        """Two Engines in one process report into the same exposition series."""
        MetricsCollector(enabled=True).record_fact_asserted("request")
        MetricsCollector(enabled=True).record_fact_asserted("request")
        val = prom_registry.get_sample_value(
            "fathom_facts_asserted_total", labels={"template": "request"}
        )
        assert val == 2.0

    def test_two_engines_with_metrics_enabled_both_build(
        self, prom_registry: CollectorRegistry
    ) -> None:
        """The end-to-end shape of the crash: two Engines, metrics on."""
        from fathom import Engine

        assert Engine(metrics=True) is not None
        assert Engine(metrics=True) is not None


class TestDeadGaugesAreWired:
    """``fathom_working_memory_facts`` and ``fathom_sessions_active`` used to
    be registered, exported on /metrics, and never recorded — so a working-set
    leak and a session leak both read as healthy forever.
    """

    def test_working_memory_gauge_follows_asserts(
        self, prom_registry: CollectorRegistry, tmp_path: Path
    ) -> None:
        from fathom.engine import Engine

        engine = Engine.from_rules(str(_write_deny_pack(tmp_path)), metrics=True)
        engine.assert_fact("request", {"action": "read", "user": "alice"})
        engine.assert_fact("request", {"action": "write", "user": "bob"})
        val = prom_registry.get_sample_value(
            "fathom_working_memory_facts", labels={"template": "request"}
        )
        assert val == 2.0

    def test_working_memory_gauge_follows_retracts(
        self, prom_registry: CollectorRegistry, tmp_path: Path
    ) -> None:
        from fathom.engine import Engine

        engine = Engine.from_rules(str(_write_deny_pack(tmp_path)), metrics=True)
        engine.assert_fact("request", {"action": "read", "user": "alice"})
        engine.retract("request")
        val = prom_registry.get_sample_value(
            "fathom_working_memory_facts", labels={"template": "request"}
        )
        assert val == 0.0

    def test_working_memory_gauge_returns_to_zero_after_evaluate_once(
        self, prom_registry: CollectorRegistry, tmp_path: Path
    ) -> None:
        """evaluate_once withdraws its facts, so the gauge must come back down."""
        from fathom.engine import Engine

        engine = Engine.from_rules(str(_write_deny_pack(tmp_path)), metrics=True)
        engine.evaluate_once([("request", {"action": "delete", "user": "mallory"})])
        val = prom_registry.get_sample_value(
            "fathom_working_memory_facts", labels={"template": "request"}
        )
        assert val == 0.0

    def test_working_memory_gauge_cleared_by_clear_facts(
        self, prom_registry: CollectorRegistry, tmp_path: Path
    ) -> None:
        from fathom.engine import Engine

        engine = Engine.from_rules(str(_write_deny_pack(tmp_path)), metrics=True)
        engine.assert_fact("request", {"action": "read", "user": "alice"})
        engine.clear_facts()
        val = prom_registry.get_sample_value(
            "fathom_working_memory_facts", labels={"template": "request"}
        )
        assert val == 0.0

    def test_sessions_active_follows_the_store(
        self, prom_registry: CollectorRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fathom.integrations.sessions import SessionStore

        monkeypatch.setenv("FATHOM_METRICS", "1")
        store = SessionStore()
        store.get_or_create("a")
        store.get_or_create("b")
        assert prom_registry.get_sample_value("fathom_sessions_active") == 2.0

    def test_sessions_active_drops_on_clear(
        self, prom_registry: CollectorRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fathom.integrations.sessions import SessionStore

        monkeypatch.setenv("FATHOM_METRICS", "1")
        store = SessionStore()
        store.get_or_create("a")
        store.clear()
        assert prom_registry.get_sample_value("fathom_sessions_active") == 0.0

    def test_sessions_active_drops_on_ttl_expiry(
        self, prom_registry: CollectorRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fathom.integrations.sessions import SessionStore

        monkeypatch.setenv("FATHOM_METRICS", "1")
        store = SessionStore(ttl_seconds=0)
        store.get_or_create("a")
        time.sleep(0.01)
        store.get_or_create("b")  # any access reclaims the expired one
        assert prom_registry.get_sample_value("fathom_sessions_active") == 1.0
