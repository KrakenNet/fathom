"""Request-contract checks for the REST surface: unknown keys, auth in the
OpenAPI document, and the session id length cap."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from fathom.integrations.rest import build_app
from fathom.integrations.sessions import MAX_SESSION_ID_LENGTH

if TYPE_CHECKING:
    from fastapi import FastAPI

H = {"Authorization": "Bearer tok"}
ROOT = Path(__file__).resolve().parents[1] / "examples"
HELLO = "01-hello-allow-deny"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(ROOT))
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    return build_app(require_signature=False)


_EXTRA: list[tuple[str, str, dict[str, Any]]] = [
    ("post", "/v1/evaluate", {"ruleset": HELLO, "facts": [], "sesion_id": "s"}),
    (
        "post",
        "/v1/evaluate",
        {
            "ruleset": HELLO,
            "facts": [{"template": "agent", "data": {"id": "a", "clearance": "secret"}, "x": 1}],
        },
    ),
    ("post", "/v1/facts", {"session_id": "s", "template": "agent", "data": {}, "x": 1}),
    ("post", "/v1/query", {"session_id": "s", "template": "agent", "x": 1}),
    ("delete", "/v1/facts", {"session_id": "s", "template": "agent", "x": 1}),
    ("post", "/v1/compile", {"yaml_content": "templates: []", "x": 1}),
]


@pytest.mark.parametrize(("method", "path", "body"), _EXTRA)
def test_unknown_request_keys_are_refused(
    app: FastAPI, method: str, path: str, body: dict[str, Any]
) -> None:
    resp = TestClient(app).request(method, path, headers=H, json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "validation_error"


def test_openapi_declares_bearer_auth(app: FastAPI) -> None:
    spec = app.openapi()
    schemes = spec["components"]["securitySchemes"]
    assert [s["scheme"] for s in schemes.values()] == ["bearer"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            names = [p["name"].lower() for p in op.get("parameters", [])]
            assert "authorization" not in names, (method, path)
            public = path in ("/health", "/v1/status")
            assert bool(op.get("security")) is not public, (method, path)


def test_auth_still_refuses_bad_tokens(app: FastAPI) -> None:
    c = TestClient(app)
    for hdr in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "bearer tok"}):
        assert c.get("/v1/templates", headers=hdr).status_code == 401
    assert c.get("/v1/templates", headers=H).status_code != 401


def test_session_id_length_is_capped(app: FastAPI) -> None:
    c = TestClient(app)
    long_id = "s" * (MAX_SESSION_ID_LENGTH + 1)
    ev = c.post(
        "/v1/evaluate", headers=H, json={"ruleset": HELLO, "facts": [], "session_id": long_id}
    )
    assert ev.status_code == 422, ev.text
    q = c.post("/v1/query", headers=H, json={"session_id": long_id, "template": "agent"})
    assert q.status_code == 422, q.text
    g = c.get("/v1/templates", headers={**H, "X-Session-Id": long_id})
    assert g.status_code == 400 and "X-Session-Id" in g.text, g.text
    ok = "s" * MAX_SESSION_ID_LENGTH
    ev = c.post("/v1/evaluate", headers=H, json={"ruleset": HELLO, "facts": [], "session_id": ok})
    assert ev.status_code == 200, ev.text
    props = app.openapi()["components"]["schemas"]["EvaluateRequest"]["properties"]
    assert props["session_id"]["anyOf"][0]["maxLength"] == MAX_SESSION_ID_LENGTH
