"""Studio panel + scenario-seed regression tests (FR-8, AC-7.2–7.4).

Exercises the Studio over a :class:`~fastapi.testclient.TestClient` built from
:func:`fathom.studio.app.create_app`. The REST app mounted at ``/api`` reads
``FATHOM_API_TOKEN`` (per-request, via :mod:`fathom.integrations.auth`) and
``FATHOM_RULESET_ROOT`` (per-request, in the evaluate path), so a
``monkeypatch.setenv`` before each request is sufficient — no module reload.

Coverage:

* all eight GET panels (``/`` plus the seven panel routes) return 200;
* the ``fathom_sid`` session cookie is minted on the first request;
* ``/packs`` lists the five real on-disk rule packs;
* ``POST /eval`` (Playground) evaluates against the mounted REST app and
  renders a real decision plus its ``rule_trace``;
* one scenario seed (``01-hello-allow-deny``) loads its ruleset and renders a
  real ``deny`` decision card with a non-empty ``rule_trace``;
* with no ``FATHOM_API_TOKEN`` the Playground shows a configuration notice
  rather than a fabricated decision;
* the scripted guardrail run is deterministic: three allows, two denies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fathom.studio.app import create_app
from fathom.studio.panels import (
    _SCRIPTED_CALLS,
    _list_rule_packs,
    _run_scripted_guardrail,
)
from fathom.studio.sessions import SESSION_COOKIE

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Bearer token wired into the mounted REST app for the configured fixtures.
_TOKEN = "demo-token"

#: Ruleset root: the bundled ``examples/0N-*`` directories the seeds load.
_RULESET_ROOT = "examples"

#: The seven panel routes plus the overview — every GET panel must answer 200.
_PANEL_ROUTES: tuple[str, ...] = (
    "/",
    "/eval",
    "/blp",
    "/temporal",
    "/packs",
    "/guardrail",
    "/audit",
    "/rest",
)

#: The five real rule packs shipped under ``src/fathom/rule_packs/``.
_EXPECTED_PACKS: tuple[str, ...] = (
    "cmmc",
    "hipaa",
    "nist_800_53",
    "owasp_agentic",
    "ssvc",
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A Studio client with the REST app's token + ruleset root configured."""
    monkeypatch.setenv("FATHOM_API_TOKEN", _TOKEN)
    monkeypatch.setenv("FATHOM_RULESET_ROOT", _RULESET_ROOT)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def unconfigured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A Studio client with no REST token (graceful-degradation path)."""
    monkeypatch.delenv("FATHOM_API_TOKEN", raising=False)
    monkeypatch.setenv("FATHOM_RULESET_ROOT", _RULESET_ROOT)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.mark.parametrize("route", _PANEL_ROUTES)
def test_panel_returns_200(client: TestClient, route: str) -> None:
    """Every GET panel route renders successfully (AC-7.2)."""
    response = client.get(route)
    assert response.status_code == 200


def test_session_cookie_minted(client: TestClient) -> None:
    """The first request mints a ``fathom_sid`` session cookie."""
    response = client.get("/")
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert client.cookies.get(SESSION_COOKIE)


def test_packs_lists_five_real_packs(client: TestClient) -> None:
    """``/packs`` surfaces exactly the five on-disk compliance packs (AC-7.2)."""
    assert tuple(_list_rule_packs()) == _EXPECTED_PACKS
    body = client.get("/packs").text
    for pack in _EXPECTED_PACKS:
        assert pack in body


def test_playground_evaluate_renders_decision_and_trace(client: TestClient) -> None:
    """``POST /eval`` returns a real decision + rule_trace (AC-7.3, FR-8)."""
    response = client.post(
        "/eval",
        data={
            "template": "agent",
            "data": '{"id": "carol", "clearance": "confidential"}',
            "ruleset": "01-hello-allow-deny",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "decision:" in body
    # A real evaluation renders the trace heading (the engine ran, not a notice).
    assert "rule_trace" in body
    assert "FATHOM_API_TOKEN is not configured" not in body


def test_scenario_seed_renders_deny_card(client: TestClient) -> None:
    """Seeding scenario 01 loads its ruleset and renders a deny card (AC-7.4)."""
    response = client.post("/scenarios/01-hello-allow-deny/seed")
    assert response.status_code == 200
    body = response.text
    assert "decision: deny" in body
    assert "rule_trace" in body
    # The card shows a real trace, not the empty-trace placeholder.
    assert "<pre>" in body
    assert "Error:" not in body


def test_playground_without_token_shows_notice(unconfigured_client: TestClient) -> None:
    """No ``FATHOM_API_TOKEN`` yields a config notice, not a fake decision."""
    response = unconfigured_client.post(
        "/eval",
        data={"template": "agent", "data": "{}", "ruleset": "01-hello-allow-deny"},
    )
    assert response.status_code == 200
    body = response.text
    assert "FATHOM_API_TOKEN is not configured" in body
    assert "decision: allow" not in body
    assert "decision: deny" not in body


def test_scripted_guardrail_three_allow_two_deny(client: TestClient) -> None:
    """The scripted guardrail run is deterministic: 3 allow / 2 deny."""
    # The route renders the run without error...
    response = client.post("/guardrail/run", data={"mode": "scripted"})
    assert response.status_code == 200
    assert "Scripted run timeline" in response.text
    # ...and the underlying scripted run is deterministically 3 allow / 2 deny.
    timeline = _run_scripted_guardrail()
    assert len(timeline) == len(_SCRIPTED_CALLS) == 5
    decisions = [event["decision"] for event in timeline]
    assert decisions.count("allow") == 3
    assert sum(1 for d in decisions if d != "allow") == 2
