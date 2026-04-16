"""Integration tests for the /metrics endpoint (Prometheus exposition format)."""

from __future__ import annotations

import contextlib

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
        assert "fathom_evaluations_total" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_facts_asserted(self, metrics_app) -> None:
        """Engine-level metric: fathom_facts_asserted_total (recorded in fixture)."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "fathom_facts_asserted_total" in body

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
        assert "fathom_rules_fired_total" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_denials_total(self, metrics_app) -> None:
        """Engine-level metric: fathom_denials_total."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "fathom_denials_total" in body

    @pytest.mark.asyncio()
    async def test_metrics_contains_sessions_active(self, metrics_app) -> None:
        """Engine-level metric: fathom_sessions_active."""
        import httpx

        transport = httpx.ASGITransport(app=metrics_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        body = response.text
        assert "fathom_sessions_active" in body
