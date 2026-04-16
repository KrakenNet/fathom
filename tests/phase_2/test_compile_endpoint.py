# tests/phase_2/test_compile_endpoint.py
"""Phase-2 REST round-trip tests for ``then.assert`` and ``bind`` (US-5).

AC-5.x in ``specs/rule-assertions/requirements.md`` phrase the response schema
as ``success`` and ``rules[].clips``; the currently-shipped ``/v1/compile``
endpoint (``src/fathom/integrations/rest.py``) uses ``{clips, errors}``
(see ``CompileResponse`` in ``src/fathom/models.py``).  The mapping used here:

* ``success == True``        -> ``errors == []`` and HTTP 200
* ``rules[].clips`` contains -> the single concatenated ``clips`` string
  (the endpoint joins all compiled rules with ``\\n``)
* ``success == False``       -> ``errors`` non-empty (the endpoint returns
  HTTP 200 with errors rather than 4xx)

FR-13: round-trip ``then.assert`` and ``ConditionEntry.bind`` through the
REST compile endpoint without schema changes.
"""

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
    session_store._sessions.clear()
    return rules_root


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer testtok"}


def _post_compile(
    client: TestClient, yaml_content: str, headers: dict[str, str]
) -> dict[str, object]:
    resp = client.post(
        "/v1/compile",
        json={"yaml_content": yaml_content},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_round_trip_assert_field(auth_headers: dict[str, str]) -> None:
    """AC-5.1: ``then.assert`` round-trips through /v1/compile."""
    client = TestClient(app)
    yaml_content = (
        "ruleset: rs\n"
        "module: MAIN\n"
        "rules:\n"
        "  - name: emit_fact\n"
        "    when:\n"
        "      - template: source\n"
        "        conditions:\n"
        "          - slot: id\n"
        "            bind: '?sid'\n"
        "    then:\n"
        "      assert:\n"
        "        - template: routing\n"
        "          slots:\n"
        "            source_id: '?sid'\n"
    )
    body = _post_compile(client, yaml_content, auth_headers)
    # success <=> no errors
    assert body["errors"] == []
    # rules[].clips <=> concatenated clips string
    assert "(assert (routing" in body["clips"]
    assert "(source_id ?sid)" in body["clips"]


def test_round_trip_bind_field(auth_headers: dict[str, str]) -> None:
    """AC-5.2: ``ConditionEntry.bind`` round-trips through /v1/compile."""
    client = TestClient(app)
    yaml_content = (
        "ruleset: rs\n"
        "module: MAIN\n"
        "rules:\n"
        "  - name: bind_only\n"
        "    when:\n"
        "      - template: source\n"
        "        conditions:\n"
        "          - slot: id\n"
        "            bind: '?sid'\n"
        "    then:\n"
        "      action: allow\n"
        "      reason: ok\n"
    )
    body = _post_compile(client, yaml_content, auth_headers)
    assert body["errors"] == []
    # Bound variable must appear in emitted LHS
    assert "?sid" in body["clips"]
    assert "(source (id ?sid))" in body["clips"]


def test_invalid_then_block_returns_error(auth_headers: dict[str, str]) -> None:
    """AC-5.3: rule missing both ``action`` and ``assert`` returns an error."""
    client = TestClient(app)
    yaml_content = (
        "ruleset: rs\n"
        "module: MAIN\n"
        "rules:\n"
        "  - name: invalid\n"
        "    when:\n"
        "      - template: source\n"
        "        conditions:\n"
        "          - slot: id\n"
        "            bind: '?sid'\n"
        "    then:\n"
        "      reason: no-action-no-assert\n"
    )
    body = _post_compile(client, yaml_content, auth_headers)
    # success == False
    assert body["errors"], "expected validation error for missing action+assert"
    joined = " ".join(body["errors"]).lower()
    assert "action" in joined or "assert" in joined, (
        f"error should cite 'action' or 'assert': {body['errors']!r}"
    )
