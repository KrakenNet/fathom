"""``build_app()`` returns an independent app per call.

It used to mutate and return the module-level ``app``, so a second call
reset the first app's ``state`` (unmounting its Engine) and every app shared
one session store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from fathom.integrations import rest
from fathom.integrations.rest import build_app

if TYPE_CHECKING:
    import pytest


def test_build_app_returns_a_new_app_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    a = build_app(require_signature=False)
    a.state.engine = "MOUNTED"
    b = build_app(require_signature=False)
    assert a is not b
    assert a is not rest.app and b is not rest.app
    assert a.state.engine == "MOUNTED"
    assert b.state.engine is None
    assert a.state.session_store is not b.state.session_store
    assert a.state.session_store is not rest.app.state.session_store


def test_each_built_app_serves_every_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    paths = {r.path for r in rest.app.routes}
    for built in (build_app(require_signature=False), build_app(require_signature=False)):
        assert {r.path for r in built.routes} == paths
        assert TestClient(built).get("/health").json() == {"status": "ok"}
        # Error envelope handlers are registered per app, not only on the module one.
        assert TestClient(built).get("/nope").json()["error"] == "not_found"
