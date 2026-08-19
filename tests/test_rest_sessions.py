"""REST session/ruleset binding, session bounds, and request-size bounds.

Covers the S2 reproduction end-to-end: a request naming a strict ruleset
must never be answered out of a session seeded with a permissive one.
"""

from __future__ import annotations

import inspect
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fathom.engine import Engine
from fathom.integrations import rest
from fathom.integrations.rest import app, session_store
from fathom.integrations.sessions import _Session

if TYPE_CHECKING:
    from collections.abc import Iterator

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "01-hello-allow-deny"

_ALLOW_EVERYTHING = """
module: governance
ruleset: loose
version: "1.0"

rules:
  - name: allow-everything
    salience: 1
    when:
      - template: agent
        conditions:
          - slot: id
            expression: "matches(.+)"
    then:
      action: allow
      reason: "LOOSE-POLICY-FIRED"
"""

_CONFIDENTIAL_READS_TOP_SECRET = [
    {"template": "agent", "data": {"id": "a1", "clearance": "confidential"}},
    {
        "template": "data_request",
        "data": {"agent_id": "a1", "classification": "top-secret", "resource": "r1"},
    },
]


_NONTERMINATING = """
module: gov
ruleset: loop
version: "1.0"

rules:
  - name: spin
    when:
      - template: tick
        conditions:
          - slot: id
            expression: "matches(.+)"
    then:
      assert:
        - template: tick
          slots:
            id: "(gensym)"
      action: allow
      reason: spin
"""


def _write_nonterminating_ruleset(root: Path) -> Path:
    """A ruleset whose rule re-asserts its own trigger — never quiesces."""
    loop = root / "loop"
    (loop / "templates").mkdir(parents=True)
    (loop / "modules").mkdir()
    (loop / "rules").mkdir()
    (loop / "templates" / "t.yaml").write_text(
        "templates:\n  - name: tick\n    slots:\n"
        "      - name: id\n        type: symbol\n        required: true\n"
    )
    (loop / "modules" / "m.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    (loop / "rules" / "r.yaml").write_text(_NONTERMINATING)
    return loop


@pytest.fixture
def ruleset_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A jail root holding a `strict` ruleset and a `loose` superset of it."""
    strict = tmp_path / "strict"
    shutil.copytree(EXAMPLE_DIR / "modules", strict / "modules")
    shutil.copytree(EXAMPLE_DIR / "templates", strict / "templates")
    shutil.copytree(EXAMPLE_DIR / "rules", strict / "rules")

    loose = tmp_path / "loose"
    shutil.copytree(strict, loose)
    (loose / "rules" / "loose.yaml").write_text(_ALLOW_EVERYTHING)

    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_session_store() -> Iterator[None]:
    session_store.clear()
    yield
    session_store.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer testtok"}


class TestSessionRulesetConfusion:
    """A live session may not be reused under a different ruleset."""

    def test_strict_request_is_not_answered_by_loose_session(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        loose = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "loose", "session_id": "S"},
            headers=auth_headers,
        )
        assert loose.status_code == 200

        strict = client.post(
            "/v1/evaluate",
            json={
                "facts": _CONFIDENTIAL_READS_TOP_SECRET,
                "ruleset": "strict",
                "session_id": "S",
            },
            headers=auth_headers,
        )
        assert strict.status_code == 409
        body = strict.json()
        assert body["error"] == "session_ruleset_mismatch"
        assert body.get("decision") is None

    def test_fresh_session_under_strict_denies(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={
                "facts": _CONFIDENTIAL_READS_TOP_SECRET,
                "ruleset": "strict",
                "session_id": "T",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "deny"

    def test_same_ruleset_still_reuses_the_session(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        for _ in range(2):
            response = client.post(
                "/v1/evaluate",
                json={"facts": [], "ruleset": "strict", "session_id": "U"},
                headers=auth_headers,
            )
            assert response.status_code == 200
        assert len(session_store) == 1


class TestRequestScopedEvaluation:
    """`/v1/evaluate` is request-scoped: no fact of a past request leaks in."""

    def test_repeated_identical_request_is_stable(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The C5 fail-open: the second identical call must not go allow."""
        decisions = []
        for _ in range(2):
            response = client.post(
                "/v1/evaluate",
                json={
                    "facts": _CONFIDENTIAL_READS_TOP_SECRET,
                    "ruleset": "strict",
                    "session_id": "repeat",
                },
                headers=auth_headers,
            )
            assert response.status_code == 200
            decisions.append(response.json()["decision"])
        assert decisions == ["deny", "deny"]

    def test_earlier_facts_do_not_leak_into_later_requests(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.post(
            "/v1/evaluate",
            json={
                "facts": _CONFIDENTIAL_READS_TOP_SECRET,
                "ruleset": "strict",
                "session_id": "scoped",
            },
            headers=auth_headers,
        )
        facts = client.post(
            "/v1/query",
            json={"session_id": "scoped", "template": "data_request"},
            headers=auth_headers,
        )
        assert facts.status_code == 200
        assert facts.json()["facts"] == []


class TestEvaluationBudget:
    """A ruleset that exhausts its activation budget is a 503, not a hang."""

    def test_exhausted_run_limit_is_503(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        loop = _write_nonterminating_ruleset(ruleset_root)
        engine = Engine.from_rules(str(loop), run_limit=20)
        session_store._sessions["budget"] = _Session(engine, str(loop), time.time())

        response = client.post(
            "/v1/evaluate",
            json={
                "facts": [{"template": "tick", "data": {"id": "x"}}],
                "ruleset": "loop",
                "session_id": "budget",
            },
            headers=auth_headers,
        )
        assert response.status_code == 503
        assert response.json()["error"] == "evaluation_failed"


class TestSessionCeiling:
    """The session ceiling is a 503, in the one error envelope."""

    def test_ceiling_returns_503(
        self,
        ruleset_root: Path,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(session_store, "_max_sessions", 1)
        first = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "strict", "session_id": "one"},
            headers=auth_headers,
        )
        assert first.status_code == 200

        second = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "strict", "session_id": "two"},
            headers=auth_headers,
        )
        assert second.status_code == 503
        assert second.json()["error"] == "session_limit_exceeded"

    def test_expired_session_is_evicted_over_the_wire(
        self,
        ruleset_root: Path,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(session_store, "_ttl_seconds", 0)
        client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "strict", "session_id": "ttl"},
            headers=auth_headers,
        )
        response = client.post(
            "/v1/query",
            json={"session_id": "ttl", "template": "agent"},
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["error"] == "not_found"


class TestRequestBodyCap:
    """POST bodies are capped on the bytes actually received."""

    def test_oversized_body_is_413(
        self,
        ruleset_root: Path,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FATHOM_MAX_REQUEST_BYTES", "512")
        facts = [
            {"template": "agent", "data": {"id": f"a{i}", "clearance": "secret"}}
            for i in range(200)
        ]
        response = client.post(
            "/v1/evaluate",
            json={"facts": facts, "ruleset": "strict"},
            headers=auth_headers,
        )
        assert response.status_code == 413
        assert response.json()["error"] == "payload_too_large"

    def test_body_under_the_cap_is_served(
        self,
        ruleset_root: Path,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FATHOM_MAX_REQUEST_BYTES", "4096")
        response = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "strict"},
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestHandlersRunInThreadpool:
    """Blocking CLIPS handlers must not be coroutines (S3)."""

    @pytest.mark.parametrize(
        "handler",
        [
            rest.evaluate,
            rest.assert_fact,
            rest.query_facts,
            rest.retract_facts,
            rest.compile_yaml,
        ],
    )
    def test_blocking_handler_is_not_a_coroutine(self, handler: object) -> None:
        assert not inspect.iscoroutinefunction(handler)


class TestErrorEnvelope:
    """Every error body is {"error", "detail", "field"} (ErrorResponse)."""

    def test_unauthorized_uses_the_envelope(self, ruleset_root: Path, client: TestClient) -> None:
        response = client.post("/v1/evaluate", json={"facts": [], "ruleset": "strict"})
        assert response.status_code == 401
        assert set(response.json()) == {"error", "detail", "field"}
        assert response.json()["error"] == "unauthorized"

    def test_path_jail_rejection_uses_the_envelope(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "../etc/passwd"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert set(response.json()) == {"error", "detail", "field"}
        assert response.json()["detail"] == "invalid ruleset path"

    def test_body_validation_error_uses_the_envelope(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post("/v1/evaluate", json={"facts": []}, headers=auth_headers)
        assert response.status_code == 422
        assert set(response.json()) == {"error", "detail", "field"}
        assert response.json()["error"] == "validation_error"
        assert response.json()["field"] == "ruleset"

    def test_session_limit_error_is_flat_not_nested(
        self,
        ruleset_root: Path,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The 503 used to nest the envelope inside ``detail``."""
        monkeypatch.setattr(session_store, "_max_sessions", 0)
        response = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "strict", "session_id": "x"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        assert set(response.json()) == {"error", "detail", "field"}
        assert isinstance(response.json()["detail"], str)

    def test_null_byte_in_ruleset_is_400_not_500(
        self, ruleset_root: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/v1/evaluate",
            json={"facts": [], "ruleset": "a\x00b"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid ruleset path"
