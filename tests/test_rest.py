"""REST API tests for the FastAPI server."""

from __future__ import annotations

import os
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fathom.integrations.rest import SessionStore, app, session_store

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def _reset_session_store() -> None:
    """Clear the module-level session store between tests."""
    session_store._sessions.clear()


@pytest.fixture(autouse=True)
def _configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure auth and the ruleset root for every REST test.

    The fixtures directory doubles as the ruleset root — tests pass
    ``ruleset=""`` (resolving to the root itself) so ``Engine.from_rules``
    discovers the pre-existing templates/rules/modules subdirectories.
    """
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", FIXTURES_DIR)


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer-token header used by every authenticated request."""
    return {"Authorization": "Bearer testtok"}


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------


class TestHealth:
    """GET /health endpoint tests."""

    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json() == {"status": "ok"}

    def test_health_content_type_json(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# 2. Stateless evaluation (no session_id)
# ---------------------------------------------------------------------------


class TestStatelessEvaluate:
    """POST /v1/evaluate without session_id."""

    def test_evaluate_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_evaluate_returns_decision(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["decision"] == "deny"

    def test_evaluate_returns_reason(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert data["reason"] is not None
        assert "clearance" in data["reason"].lower()

    def test_evaluate_returns_rule_trace(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert isinstance(data["rule_trace"], list)
        assert len(data["rule_trace"]) > 0

    def test_evaluate_returns_module_trace(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert isinstance(data["module_trace"], list)

    def test_evaluate_returns_duration_us(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert isinstance(data["duration_us"], int)
        assert data["duration_us"] >= 0

    def test_evaluate_returns_attestation_token_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert "attestation_token" in data

    def test_evaluate_no_rules_fire_default_decision(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """When no rules match, the default decision is returned."""
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        # Only one fact, no data_request => deny rule won't fire
        assert data["rule_trace"] == []

    def test_evaluate_stateless_no_session_leak(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Stateless calls should not create entries in the session store."""
        client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert len(session_store._sessions) == 0


# ---------------------------------------------------------------------------
# 3. Request validation (422 errors)
# ---------------------------------------------------------------------------


class TestValidation:
    """POST /v1/evaluate with invalid inputs."""

    def test_missing_facts_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={"ruleset": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_missing_ruleset_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={"facts": []},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_empty_body(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_invalid_json(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            content="not valid json",
            headers={**auth_headers, "content-type": "application/json"},
        )
        assert response.status_code == 422

    def test_facts_wrong_type(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={"facts": "not-a-list", "ruleset": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_missing_required_slot(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Agent template requires 'id' slot."""
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"clearance": "secret"}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"

    def test_invalid_allowed_values(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Clearance slot only allows specific values."""
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {
                        "template": "agent",
                        "data": {"id": "a1", "clearance": "mega-secret"},
                    },
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "validation_error"
        assert data["field"] == "clearance"

    def test_unknown_template(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "nonexistent", "data": {"x": 1}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert "nonexistent" in data["detail"]

    def test_bad_ruleset_path(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Absolute paths escape the ruleset jail and are rejected with 400."""
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "/nonexistent/path/to/rules",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# 4. Stateful evaluation (with session_id)
# ---------------------------------------------------------------------------


class TestStatefulEvaluate:
    """POST /v1/evaluate with session_id."""

    def test_session_created_on_first_request(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
                "session_id": "sess-1",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "sess-1" in session_store._sessions

    def test_session_reuses_engine(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Second request with same session_id reuses the Engine."""
        client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
                "session_id": "sess-reuse",
            },
            headers=auth_headers,
        )
        engine1, _ = session_store._sessions["sess-reuse"]

        client.post(
            "/v1/evaluate",
            json={
                "facts": [],
                "ruleset": "",
                "session_id": "sess-reuse",
            },
            headers=auth_headers,
        )
        engine2, _ = session_store._sessions["sess-reuse"]
        assert engine1 is engine2

    def test_facts_persist_across_requests(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Facts from the first request remain in the session Engine."""
        client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
                "session_id": "sess-persist",
            },
            headers=auth_headers,
        )
        # Second request adds data_request; agent fact persists from first
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {
                        "template": "data_request",
                        "data": {
                            "agent_id": "a1",
                            "classification": "top-secret",
                            "resource": "doc-1",
                        },
                    },
                ],
                "ruleset": "",
                "session_id": "sess-persist",
            },
            headers=auth_headers,
        )
        data = response.json()
        assert response.status_code == 200
        assert data["decision"] == "deny"

    def test_different_sessions_are_isolated(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Different session_ids have independent Engines."""
        client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
                "session_id": "sess-A",
            },
            headers=auth_headers,
        )
        client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a2", "clearance": "cui"}},
                ],
                "ruleset": "",
                "session_id": "sess-B",
            },
            headers=auth_headers,
        )
        engine_a, _ = session_store._sessions["sess-A"]
        engine_b, _ = session_store._sessions["sess-B"]
        assert engine_a is not engine_b

    def test_stateful_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
                "session_id": "sess-ok",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 5. SessionStore unit tests
# ---------------------------------------------------------------------------


class TestSessionStore:
    """Direct tests for SessionStore behavior."""

    def test_default_ttl(self) -> None:
        store = SessionStore()
        assert store._ttl_seconds == 1800

    def test_default_max_sessions(self) -> None:
        store = SessionStore()
        assert store._max_sessions == 1000

    def test_custom_ttl(self) -> None:
        store = SessionStore(ttl_seconds=60)
        assert store._ttl_seconds == 60

    def test_custom_max_sessions(self) -> None:
        store = SessionStore(max_sessions=5)
        assert store._max_sessions == 5

    def test_session_expiry(self) -> None:
        store = SessionStore(ttl_seconds=0)
        engine1 = store.get_or_create("test-session", FIXTURES_DIR)
        time.sleep(0.01)
        engine2 = store.get_or_create("test-session", FIXTURES_DIR)
        assert engine1 is not engine2

    def test_session_not_expired(self) -> None:
        store = SessionStore(ttl_seconds=3600)
        engine1 = store.get_or_create("test-session", FIXTURES_DIR)
        engine2 = store.get_or_create("test-session", FIXTURES_DIR)
        assert engine1 is engine2

    def test_max_sessions_limit(self) -> None:
        store = SessionStore(max_sessions=2)
        store.get_or_create("s1", FIXTURES_DIR)
        store.get_or_create("s2", FIXTURES_DIR)
        with pytest.raises(HTTPException) as exc_info:
            store.get_or_create("s3", FIXTURES_DIR)
        assert exc_info.value.status_code == 503

    def test_max_sessions_after_expiry_allows_new(self) -> None:
        """After expired sessions are cleaned, new sessions can be created."""
        store = SessionStore(ttl_seconds=0, max_sessions=1)
        store.get_or_create("s1", FIXTURES_DIR)
        time.sleep(0.01)
        # s1 is expired, cleanup should free the slot
        engine = store.get_or_create("s2", FIXTURES_DIR)
        assert engine is not None

    def test_cleanup_removes_expired_sessions(self) -> None:
        store = SessionStore(ttl_seconds=0)
        store.get_or_create("s1", FIXTURES_DIR)
        store.get_or_create("s2", FIXTURES_DIR)
        time.sleep(0.01)
        store._cleanup_expired()
        assert len(store._sessions) == 0

    def test_get_or_create_updates_access_time(self) -> None:
        store = SessionStore(ttl_seconds=3600)
        store.get_or_create("s1", FIXTURES_DIR)
        _, t1 = store._sessions["s1"]
        time.sleep(0.01)
        store.get_or_create("s1", FIXTURES_DIR)
        _, t2 = store._sessions["s1"]
        assert t2 > t1


# ---------------------------------------------------------------------------
# 6. Response schema validation
# ---------------------------------------------------------------------------


class TestResponseSchema:
    """Verify response shapes match the EvaluateResponse model."""

    def test_all_response_fields_present(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [
                    {"template": "agent", "data": {"id": "a1", "clearance": "secret"}},
                ],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        data = response.json()
        expected_keys = {
            "decision",
            "reason",
            "rule_trace",
            "module_trace",
            "duration_us",
            "attestation_token",
        }
        assert set(data.keys()) == expected_keys

    def test_empty_facts_returns_valid_response(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [],
                "ruleset": "",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "decision" in data
        assert "duration_us" in data


# ---------------------------------------------------------------------------
# 7. Working-memory endpoints: POST /v1/facts, /v1/query, DELETE /v1/facts
# ---------------------------------------------------------------------------


def _create_session(
    client: TestClient, auth_headers: dict[str, str], session_id: str
) -> None:
    """Helper: create a session via POST /v1/evaluate."""
    response = client.post(
        "/v1/evaluate",
        json={
            "facts": [],
            "ruleset": "",
            "session_id": session_id,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200


class TestAssertFactEndpoint:
    """POST /v1/facts tests."""

    def test_assert_fact_returns_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_session(client, auth_headers, "sess-assert-1")
        response = client.post(
            "/v1/facts",
            json={
                "session_id": "sess-assert-1",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}

    def test_assert_fact_unknown_session_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/facts",
            json={
                "session_id": "does-not-exist",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_assert_fact_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/v1/facts",
            json={
                "session_id": "whatever",
                "template": "agent",
                "data": {"id": "a1"},
            },
        )
        assert response.status_code == 401

    def test_assert_fact_invalid_slot_returns_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Bad slot value is surfaced via the FathomValidationError handler."""
        _create_session(client, auth_headers, "sess-assert-bad")
        response = client.post(
            "/v1/facts",
            json={
                "session_id": "sess-assert-bad",
                "template": "agent",
                "data": {"id": "a1", "clearance": "mega-secret"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestQueryFactsEndpoint:
    """POST /v1/query tests."""

    def test_query_facts_returns_matching_facts(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_session(client, auth_headers, "sess-query-1")
        # Assert two agent facts.
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-query-1",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-query-1",
                "template": "agent",
                "data": {"id": "a2", "clearance": "cui"},
            },
            headers=auth_headers,
        )
        response = client.post(
            "/v1/query",
            json={
                "session_id": "sess-query-1",
                "template": "agent",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "facts" in data
        assert len(data["facts"]) == 2

    def test_query_facts_with_filter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_session(client, auth_headers, "sess-query-filter")
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-query-filter",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-query-filter",
                "template": "agent",
                "data": {"id": "a2", "clearance": "cui"},
            },
            headers=auth_headers,
        )
        response = client.post(
            "/v1/query",
            json={
                "session_id": "sess-query-filter",
                "template": "agent",
                "filter": {"id": "a1"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["facts"]) == 1

    def test_query_facts_unknown_session_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/query",
            json={
                "session_id": "nope",
                "template": "agent",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_query_facts_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/v1/query",
            json={"session_id": "x", "template": "agent"},
        )
        assert response.status_code == 401


class TestRetractFactsEndpoint:
    """DELETE /v1/facts tests."""

    def test_retract_facts_removes_and_returns_count(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_session(client, auth_headers, "sess-retract")
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-retract",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-retract",
                "template": "agent",
                "data": {"id": "a2", "clearance": "cui"},
            },
            headers=auth_headers,
        )
        response = client.request(
            "DELETE",
            "/v1/facts",
            json={
                "session_id": "sess-retract",
                "template": "agent",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == {"retracted_count": 2}

        # Verify facts are gone.
        q = client.post(
            "/v1/query",
            json={"session_id": "sess-retract", "template": "agent"},
            headers=auth_headers,
        )
        assert q.json()["facts"] == []

    def test_retract_facts_with_filter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _create_session(client, auth_headers, "sess-retract-filter")
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-retract-filter",
                "template": "agent",
                "data": {"id": "a1", "clearance": "secret"},
            },
            headers=auth_headers,
        )
        client.post(
            "/v1/facts",
            json={
                "session_id": "sess-retract-filter",
                "template": "agent",
                "data": {"id": "a2", "clearance": "cui"},
            },
            headers=auth_headers,
        )
        response = client.request(
            "DELETE",
            "/v1/facts",
            json={
                "session_id": "sess-retract-filter",
                "template": "agent",
                "filter": {"id": "a1"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == {"retracted_count": 1}

    def test_retract_facts_unknown_session_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.request(
            "DELETE",
            "/v1/facts",
            json={"session_id": "nope", "template": "agent"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_retract_facts_requires_auth(self, client: TestClient) -> None:
        response = client.request(
            "DELETE",
            "/v1/facts",
            json={"session_id": "x", "template": "agent"},
        )
        assert response.status_code == 401
