"""A successful reload must change what the data plane decides.

``POST /v1/rules/reload`` swaps the ruleset on ``app.state.engine``. Every
stateless request used to compile its own Engine off disk instead, so a
reload returned a fresh ``ruleset_hash_after``, emitted its audit event, and
changed nothing a caller could observe — traffic kept being decided by the
ruleset the reload had just replaced. The reload suite only ever asserted on
the reload response, never on a decision taken afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from fathom.attestation import AttestationService
from fathom.engine import Engine
from fathom.integrations.rest import build_app, session_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

AUTH = {"Authorization": "Bearer testtok"}


def _ruleset_yaml(rule_name: str, action: str, reason: str) -> str:
    """A ruleset deciding ``agent(id=alice)`` with *action*."""
    return yaml.safe_dump(
        {
            "ruleset": f"rs-{rule_name}",
            "module": "gov",
            "rules": [
                {
                    "name": rule_name,
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [{"slot": "id", "expression": "equals(alice)"}],
                        }
                    ],
                    "then": {"action": action, "reason": reason},
                }
            ],
        }
    )


def _pack(tmp_path: Path) -> Path:
    """Write an on-disk rule pack that allows alice, and return its path."""
    pack = tmp_path / "rules" / "pack"
    for subdir in ("templates", "modules", "rules"):
        (pack / subdir).mkdir(parents=True)
    (pack / "templates" / "templates.yaml").write_text(
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    )
    (pack / "modules" / "modules.yaml").write_text("modules:\n  - name: gov\nfocus_order: [gov]\n")
    (pack / "rules" / "rules.yaml").write_text(_ruleset_yaml("allow-alice", "allow", "alice ok"))
    return pack


@pytest.fixture
def mounted_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """A server that mounts its Engine — the deployment reload is built for."""
    pack = _pack(tmp_path)
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path / "rules"))

    app = build_app(require_signature=False)
    app.state.engine = Engine.from_rules(str(pack))
    app.state.attestation = AttestationService.generate_keypair()
    session_store.clear()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def unmounted_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """A server with no Engine mounted — the shipped uvicorn deployment."""
    _pack(tmp_path)
    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_ALLOW_UNSIGNED_RULESETS", "1")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path / "rules"))

    app = build_app(require_signature=False)
    app.state.attestation = AttestationService.generate_keypair()
    session_store.clear()
    with TestClient(app) as client:
        yield client


def _evaluate(client: TestClient, ruleset: str = "pack", **extra: object) -> dict:
    """POST one ``agent(id=alice)`` fact and return the decoded response."""
    body: dict[str, object] = {
        "ruleset": ruleset,
        "facts": [{"template": "agent", "data": {"id": "alice"}}],
    }
    body.update(extra)
    response = client.post("/v1/evaluate", json=body, headers=AUTH)
    return {"status": response.status_code, "body": response.json()}


def test_reload_changes_the_decision_the_data_plane_returns(
    mounted_client: TestClient,
) -> None:
    """The whole point of hot-reload, and the thing nothing asserted."""
    before = _evaluate(mounted_client)
    assert before["body"]["decision"] == "allow"

    reload_response = mounted_client.post(
        "/v1/rules/reload",
        json={"ruleset_yaml": _ruleset_yaml("deny-alice", "deny", "alice banned")},
        headers=AUTH,
    )
    assert reload_response.status_code == 200, reload_response.text

    after = _evaluate(mounted_client)
    assert after["body"]["decision"] == "deny"
    assert after["body"]["reason"] == "alice banned"


def test_a_mounted_server_refuses_a_session_rather_than_compiling_the_callers_ruleset(
    mounted_client: TestClient,
) -> None:
    """A session's Engine is not the mounted one, so the caller would pick it.

    This used to answer ``allow`` out of an Engine compiled from whatever
    ``ruleset`` the request named — the policy the server mounts decided
    nothing, and the reload below could not reach that traffic either.
    """
    refused = _evaluate(mounted_client, session_id="s-1")

    assert refused["status"] == 400
    assert refused["body"]["error"] == "sessions_unavailable"
    assert session_store.get("s-1") is None


def test_mounted_engine_still_signs_decisions(mounted_client: TestClient) -> None:
    """The signing service is injected onto app.state after the Engine is built."""
    assert _evaluate(mounted_client)["body"]["attestation_token"]


def test_unmounted_server_serves_the_named_ruleset_from_disk(
    unmounted_client: TestClient,
) -> None:
    """The path-addressed data plane is unchanged when no Engine is mounted."""
    assert _evaluate(unmounted_client)["body"]["decision"] == "allow"


def test_unmounted_server_reports_reload_as_not_ready(
    unmounted_client: TestClient,
) -> None:
    """Reload has no Engine to swap, and says so rather than reporting success."""
    response = unmounted_client.post(
        "/v1/rules/reload",
        json={"ruleset_yaml": _ruleset_yaml("deny-alice", "deny", "alice banned")},
        headers=AUTH,
    )

    assert response.status_code == 503
    assert response.json()["error"] == "not_ready"


def test_unloadable_ruleset_is_a_400_that_names_no_server_path(
    unmounted_client: TestClient,
    tmp_path: Path,
) -> None:
    """An unknown ruleset raised CompilationError straight out of the handler.

    That is a 500 carrying a traceback, and the exception text carries the
    resolved server-side absolute path.
    """
    result = _evaluate(unmounted_client, ruleset="nope")

    assert result["status"] == 400
    assert result["body"]["error"] == "invalid_ruleset"
    assert result["body"]["detail"] == "ruleset could not be loaded"
    assert str(tmp_path) not in str(result["body"])


def test_opa_data_api_does_not_leak_the_resolved_path(
    unmounted_client: TestClient,
    tmp_path: Path,
) -> None:
    """``/v1/data`` echoed the loader's message, absolute server path and all."""
    response = unmounted_client.get("/v1/data/nope/allow", headers=AUTH)

    assert response.status_code == 400
    assert str(tmp_path) not in response.text
    assert response.json()["message"] == "ruleset 'nope' could not be loaded"
