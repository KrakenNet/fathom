"""Integration tests for the /metrics endpoint (Prometheus exposition format)."""

from __future__ import annotations

import contextlib
import re

import pytest

try:
    import prometheus_client
    from prometheus_client import REGISTRY
    from prometheus_fastapi_instrumentator import Instrumentator

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

pytestmark = pytest.mark.skipif(
    not _HAS_PROMETHEUS,
    reason="prometheus_client or prometheus_fastapi_instrumentator not installed",
)


@pytest.fixture()
def _clean_registry():
    """Unregister fathom collectors after test to avoid duplication errors."""
    yield
    # Clean up any fathom-specific collectors registered during the test
    collectors_to_remove = []
    for collector in list(REGISTRY._names_to_collectors.values()):
        desc = getattr(collector, "_name", "") or ""
        if desc.startswith("fathom_"):
            collectors_to_remove.append(collector)
    for c in collectors_to_remove:
        with contextlib.suppress(Exception):
            REGISTRY.unregister(c)
    # The families are cached process-wide, so unregistering them from the
    # REGISTRY is only half the cleanup: drop the cache too, or the next
    # collector hands back families no exposition will ever see.
    import fathom.metrics as fathom_metrics

    fathom_metrics._reset_families_for_testing()


def _nonzero_sample(body: str, family: str) -> bool:
    """True if *body* carries a sample of *family* with a value above zero.

    ``family in body`` is not enough: an engine-level metric that is
    registered but never recorded still contributes its ``# HELP`` and
    ``# TYPE`` lines to the exposition, so a name-only assertion is green on
    a metric that is permanently stuck at nothing.
    """
    pattern = re.compile(
        rf"^{re.escape(family)}(?:\{{[^}}]*\}})? ([0-9.eE+-]+)$",
        re.MULTILINE,
    )
    return any(float(m) > 0 for m in pattern.findall(body))


def _deny_engine():
    """An Engine with metrics on whose only rule denies deletes."""
    import tempfile
    from pathlib import Path

    from fathom.engine import Engine

    pack = Path(tempfile.mkdtemp()) / "pack"
    for sub in ("templates", "modules", "rules"):
        (pack / sub).mkdir(parents=True)
    (pack / "templates" / "request.yaml").write_text(
        "templates:\n"
        "  - name: request\n"
        "    slots:\n"
        "      - name: action\n"
        "        type: symbol\n"
        "      - name: user\n"
        "        type: symbol\n"
    )
    (pack / "modules" / "governance.yaml").write_text(
        "modules:\n  - name: governance\nfocus_order:\n  - governance\n"
    )
    (pack / "rules" / "deny.yaml").write_text(
        "module: governance\n"
        "rules:\n"
        "  - name: deny-delete\n"
        "    salience: 10\n"
        "    when:\n"
        "      - template: request\n"
        "        conditions:\n"
        "          - slot: action\n"
        '            expression: "equals(delete)"\n'
        "    then:\n"
        "      action: deny\n"
        '      reason: "deletes are not permitted"\n'
    )
    return Engine.from_rules(str(pack), metrics=True)


@pytest.fixture()
def metrics_app(_clean_registry):
    """Create a FastAPI app with metrics enabled."""
    from fastapi import FastAPI
    from fastapi.responses import Response

    app = FastAPI()

    # Instrument HTTP metrics (same as rest.py)
    Instrumentator().instrument(app).expose(app)

    # Register engine-level metrics via MetricsCollector
    from fathom.metrics import MetricsCollector

    collector = MetricsCollector(enabled=True)
    # Record some sample data so metrics appear in output
    collector.record_fact_asserted("agent")
    collector.record_templates_loaded(2)

    # Drive a REAL evaluation that fires a deny rule. Recording nothing here
    # left fathom_rules_fired_total and fathom_denials_total as empty families,
    # whose HELP/TYPE lines still appear in the exposition — which is how the
    # never-incremented metrics shipped past a name-only assertion.
    engine = _deny_engine()
    engine.assert_fact("request", {"action": "delete", "user": "mallory"})
    engine.evaluate()

    @app.get("/metrics")
    async def metrics() -> Response:
        body = prometheus_client.generate_latest()
        return Response(
            content=body,
            media_type=prometheus_client.CONTENT_TYPE_LATEST,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """GET /metrics endpoint tests."""

    @pytest.mark.asyncio()
    async def test_metrics_returns_200(self, metrics_app) -> None:
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio()
    async def test_metrics_content_type(self, metrics_app) -> None:
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        content_type = response.headers["content-type"]
        assert "text/plain" in content_type or "text/openmetrics" in content_type

    @pytest.mark.asyncio()
    async def test_metrics_prometheus_format(self, metrics_app) -> None:
        """Response body uses Prometheus exposition format (# HELP, # TYPE lines)."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "# HELP" in body
        assert "# TYPE" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_http_request_metrics(self, metrics_app) -> None:
        """Instrumentator adds HTTP request duration/count metrics."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Hit another endpoint first so HTTP metrics are populated
            await client.get("/health")
            response = await client.get("/metrics")
        body = response.text
        # prometheus-fastapi-instrumentator registers http_request_duration or similar
        assert "http_request" in body or "http_requests" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_evaluations_total(self, metrics_app) -> None:
        """Engine-level metric: fathom_evaluations_total."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert _nonzero_sample(body, "fathom_evaluations_total"), body

    @pytest.mark.asyncio()
    async def test_metrics_contains_facts_asserted(self, metrics_app) -> None:
        """Engine-level metric: fathom_facts_asserted_total (recorded in fixture)."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert _nonzero_sample(body, "fathom_facts_asserted_total"), body

    @pytest.mark.asyncio()
    async def test_metrics_contains_templates_loaded(self, metrics_app) -> None:
        """Engine-level metric: fathom_templates_loaded_total (recorded in fixture)."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "fathom_templates_loaded_total" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_rules_fired(self, metrics_app) -> None:
        """Engine-level metric: fathom_rules_fired_total."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        # A name-only assertion passes on an EMPTY family: prometheus_client
        # still emits HELP/TYPE for a labelled counter with no samples. Assert
        # a real non-zero sample instead.
        assert _nonzero_sample(body, "fathom_rules_fired_total"), body

    @pytest.mark.asyncio()
    async def test_metrics_contains_denials_total(self, metrics_app) -> None:
        """Engine-level metric: fathom_denials_total."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert _nonzero_sample(body, "fathom_denials_total"), body

    @pytest.mark.asyncio()
    async def test_metrics_contains_sessions_active(self, metrics_app) -> None:
        """Engine-level metric: fathom_sessions_active."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "fathom_sessions_active" in body
