"""Unit tests for MetricsCollector."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from fathom.metrics import MetricsCollector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_eval_result(
    decision: str = "allow",
    duration_us: int = 5000,
) -> MagicMock:
    """Return a mock EvaluationResult with the given fields."""
    result = MagicMock()
    result.decision = decision
    result.duration_us = duration_us
    return result


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
        yield
        for p in self._patches:
            p.stop()

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
        mc.record_denial("deny_all", "policy violation")
        val = self._registry.get_sample_value(
            "fathom_denials_total",
            labels={"rule": "deny_all", "reason": "policy violation"},
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
        yield
        for p in self._patches:
            p.stop()

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
