"""Every status a route actually returns is declared in the OpenAPI spec,
with the body model it actually returns.

The spec used to omit ``/v1/evaluate`` 500 and ``/v1/data`` 413, and declared
the ``/v1/data`` 422 as FastAPI's ``HTTPValidationError`` while the server
answered with ``ErrorResponse``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

from fathom.integrations.rest import app

if TYPE_CHECKING:
    import httpx
    import pytest

H = {"Authorization": "Bearer tok"}
ROOT = Path(__file__).resolve().parents[1] / "examples"
HELLO = "01-hello-allow-deny"
_DR = {
    "template": "data_request",
    "data": {"agent_id": "a", "classification": "unclassified", "resource": "r"},
}


def _envelope(body: dict[str, Any]) -> str:
    if set(body) == {"error", "detail", "field"}:
        return "ErrorResponse"
    if set(body) == {"code", "message"}:
        return "OPAErrorResponse"
    return "other"


def _probes(
    c: TestClient, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str, httpx.Response]]:
    out: list[tuple[str, str, httpx.Response]] = []
    big = {"template": "agent", "data": {"id": "x" * 5000, "clearance": "secret"}}
    ev = {"ruleset": HELLO, "facts": [big, _DR]}
    out.append(("post", "/v1/evaluate", c.post("/v1/evaluate", headers=H, json=ev)))
    out.append(("post", "/v1/evaluate", c.post("/v1/evaluate", json=ev)))
    out.append(("post", "/v1/evaluate", c.post("/v1/evaluate", headers=H, json={"facts": 1})))
    out.append(("post", "/v1/data/{path}", c.post("/v1/data/x", headers=H, content=b"{bad")))
    out.append(("post", "/v1/data/{path}", c.post("/v1/data/nope", headers=H, json={})))
    out.append(("get", "/v1/data/{path}", c.get("/v1/data/x", headers=H, params={"input": "{"})))
    out.append(("get", "/v1/templates", c.get("/v1/templates", headers=H)))
    out.append(
        (
            "post",
            "/v1/query",
            c.post("/v1/query", headers=H, json={"session_id": "n", "template": "t"}),
        )
    )

    def _boom(*_: object, **__: object) -> None:
        raise RuntimeError("/srv/secret")

    with monkeypatch.context() as m:
        m.setattr("fathom.engine.Engine.from_rules", _boom)
        out.append(("post", "/v1/evaluate", c.post("/v1/evaluate", headers=H, json=ev)))
    monkeypatch.delenv("FATHOM_RULESET_ROOT")
    out.append(
        (
            "post",
            "/v1/evaluate",
            c.post("/v1/evaluate", headers=H, json={"ruleset": HELLO, "facts": []}),
        )
    )
    out.append(("post", "/v1/data/{path}", c.post("/v1/data/x/allow", headers=H, json={})))
    monkeypatch.setenv("FATHOM_MAX_REQUEST_BYTES", "50")
    pad = {"input": {"x": "y" * 100}}
    out.append(("post", "/v1/data/{path}", c.post("/v1/data/x", headers=H, json=pad)))
    out.append(
        ("post", "/v1/compile", c.post("/v1/compile", headers=H, json={"yaml_content": "y" * 100}))
    )
    out.append(("post", "/v1/evaluate", c.post("/v1/evaluate", headers=H, json=pad)))
    return out


def test_every_live_error_status_is_declared_with_its_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(ROOT))
    spec = app.openapi()
    c = TestClient(app, raise_server_exceptions=False)
    seen = set()
    for method, path, resp in _probes(c, monkeypatch):
        status = str(resp.status_code)
        seen.add(status)
        declared = spec["paths"][path][method]["responses"]
        assert status in declared, (method, path, status, resp.text)
        schema = declared[status]["content"]["application/json"]["schema"]
        assert schema.get("$ref", "").rsplit("/", 1)[-1] == _envelope(resp.json()), (
            method,
            path,
            status,
            schema,
            resp.text,
        )
    assert {"400", "401", "404", "413", "422", "500"} <= seen


def test_evaluation_error_does_not_echo_clips_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(ROOT))
    c = TestClient(app)
    big = {"template": "agent", "data": {"id": "x" * 5000, "clearance": "secret"}}
    ev = c.post("/v1/evaluate", headers=H, json={"ruleset": HELLO, "facts": [big, _DR]})
    data = c.post(
        f"/v1/data/{HELLO}?template=agent",
        headers=H,
        json={"input": {"id": "x" * 5000, "clearance": "secret"}},
    )
    for resp in (ev, data):
        assert resp.status_code == 500, resp.text
        assert "CLIPS" not in resp.text and "4096" not in resp.text, resp.text
