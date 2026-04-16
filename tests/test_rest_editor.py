# tests/test_rest_editor.py
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fathom.integrations.rest import app, session_store

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _rest_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    rules_root = tmp_path / "rules"
    rules_root.mkdir()
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(rules_root))
    # Reset session_store between tests
    session_store._sessions.clear()
    return rules_root


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer testtok"}


@pytest.fixture
def seeded_session(
    _rest_env: Path, auth_headers: dict[str, str]
) -> tuple[TestClient, str]:
    """Build a small rule pack, create a session via /v1/evaluate, return id."""
    (_rest_env / "templates.yaml").write_text(
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: string\n"
    )
    (_rest_env / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    (_rest_env / "rules.yaml").write_text(
        "ruleset: gov\nmodule: gov\nrules:\n"
        "  - name: ok\n    when:\n"
        "      - template: agent\n        alias: $a\n        conditions: []\n"
        "    then:\n      action: allow\n      reason: ok\n"
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/evaluate",
        json={"session_id": "sess1", "ruleset": ".", "facts": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    return client, "sess1"


class TestListTemplatesReal:
    def test_rejects_missing_session_id(
        self, _rest_env: Path, auth_headers: dict[str, str]
    ) -> None:
        c = TestClient(app)
        r = c.get("/v1/templates", headers=auth_headers)
        # Session ID is now a required X-Session-Id header (400, not 422).
        assert r.status_code == 400

    def test_returns_templates_for_session(
        self, seeded_session: tuple[TestClient, str], auth_headers: dict[str, str]
    ) -> None:
        client, sid = seeded_session
        r = client.get(
            "/v1/templates",
            headers={**auth_headers, "X-Session-Id": sid},
        )
        assert r.status_code == 200
        names = {item["name"] for item in r.json()["items"]}
        assert "agent" in names

    def test_404_for_missing_session(
        self, _rest_env: Path, auth_headers: dict[str, str]
    ) -> None:
        c = TestClient(app)
        r = c.get(
            "/v1/templates",
            headers={**auth_headers, "X-Session-Id": "nope"},
        )
        assert r.status_code == 404


class TestListRulesReal:
    def test_returns_rules_for_session(
        self, seeded_session: tuple[TestClient, str], auth_headers: dict[str, str]
    ) -> None:
        client, sid = seeded_session
        r = client.get(
            "/v1/rules",
            headers={**auth_headers, "X-Session-Id": sid},
        )
        assert r.status_code == 200
        names = {item["name"] for item in r.json()["items"]}
        assert "ok" in names


class TestListModulesReal:
    def test_returns_modules_for_session(
        self, seeded_session: tuple[TestClient, str], auth_headers: dict[str, str]
    ) -> None:
        client, sid = seeded_session
        r = client.get(
            "/v1/modules",
            headers={**auth_headers, "X-Session-Id": sid},
        )
        assert r.status_code == 200
        names = {item["name"] for item in r.json()["items"]}
        assert "gov" in names


class TestCompileYaml:
    """Preserve existing /v1/compile tests — these endpoints were not broken."""

    def test_compile_template_returns_clips(
        self, _rest_env: Path, auth_headers: dict[str, str]
    ) -> None:
        c = TestClient(app)
        yaml_content = (
            "templates:\n  - name: sensor\n    slots:\n"
            "      - name: value\n        type: float\n"
        )
        r = c.post("/v1/compile", json={"yaml_content": yaml_content}, headers=auth_headers)
        assert r.status_code == 200
        assert "deftemplate" in r.json()["clips"]
