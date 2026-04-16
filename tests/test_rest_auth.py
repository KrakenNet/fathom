"""Tests for auth + path jailing on the REST server."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fathom.integrations.rest import app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    rules_root = tmp_path / "rules"
    rules_root.mkdir()
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(rules_root))
    return TestClient(app)


class TestAuthRequired:
    def test_evaluate_rejects_missing_token(self, client: TestClient) -> None:
        r = client.post("/v1/evaluate", json={"ruleset": "x.yaml", "facts": []})
        assert r.status_code == 401

    def test_evaluate_rejects_wrong_token(self, client: TestClient) -> None:
        r = client.post(
            "/v1/evaluate",
            json={"ruleset": "x.yaml", "facts": []},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401

    def test_templates_rejects_missing_token(self, client: TestClient) -> None:
        r = client.get("/v1/templates")
        assert r.status_code == 401

    def test_rules_rejects_missing_token(self, client: TestClient) -> None:
        r = client.get("/v1/rules")
        assert r.status_code == 401

    def test_modules_rejects_missing_token(self, client: TestClient) -> None:
        r = client.get("/v1/modules")
        assert r.status_code == 401

    def test_compile_rejects_missing_token(self, client: TestClient) -> None:
        r = client.post("/v1/compile", json={"yaml_content": "templates: []"})
        assert r.status_code == 401

    def test_health_open(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200


class TestPathJailing:
    def test_rejects_parent_traversal(self, client: TestClient) -> None:
        r = client.post(
            "/v1/evaluate",
            json={"ruleset": "../../etc/passwd", "facts": []},
            headers={"Authorization": "Bearer testtok"},
        )
        assert r.status_code == 400
        assert "invalid ruleset path" in r.json()["detail"]

    def test_rejects_absolute(self, client: TestClient) -> None:
        r = client.post(
            "/v1/evaluate",
            json={"ruleset": "/etc/passwd", "facts": []},
            headers={"Authorization": "Bearer testtok"},
        )
        assert r.status_code == 400
