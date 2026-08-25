"""Studio panel + scenario-seed regression tests (FR-8, AC-7.2–7.4).

Exercises the Studio over a :class:`~fastapi.testclient.TestClient` built from
:func:`fathom_studio.app.create_app`. The REST app mounted at ``/api`` reads
``FATHOM_API_TOKEN`` (per-request, via :mod:`fathom.integrations.auth`) and
``FATHOM_RULESET_ROOT`` (per-request, in the evaluate path), so a
``monkeypatch.setenv`` before each request is sufficient — no module reload.

The Studio's own panels are gated on the same ``FATHOM_API_TOKEN``
(:mod:`fathom_studio.auth`), so the configured fixtures present it as a bearer
header the way the SPA and ``curl`` do.

Coverage:

* all seven panel routes plus the ungated SPA shell at ``/`` return 200;
* every panel route 401s without the token, and the ``?token=`` grant on ``/``
  hands a browser the cookie that unlocks them;
* the ``fathom_sid`` session cookie is minted on the first request;
* ``/packs`` lists the real on-disk rule packs;
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

from fathom_studio.app import create_app
from fathom_studio.auth import TOKEN_COOKIE
from fathom_studio.panels import (
    _SCRIPTED_CALLS,
    _list_rule_packs,
    _run_scripted_guardrail,
)
from fathom_studio.rulesets import packaged_root
from fathom_studio.sessions import SESSION_COOKIE

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Bearer token wired into the mounted REST app for the configured fixtures.
_TOKEN = "demo-token"

#: Ruleset root: the ``0N-*`` directories the Studio ships as package data.
#: Absolute, via :func:`packaged_root` -- a repo-relative ``"examples"`` only
#: resolved when pytest happened to run from the repo root, so it broke the
#: moment the suite was invoked from ``packages/fathom-studio/``.
_RULESET_ROOT = str(packaged_root())

#: Authorization header presenting the Studio token, as ``curl``/the SPA do.
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}

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

#: The compliance packs the /packs panel was specified against. Not an
#: exhaustive list: packs are added over time and the panel reads the
#: directory, so asserting an exact set here would only pin the count.
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
    with TestClient(create_app(), headers=_AUTH) as test_client:
        yield test_client


@pytest.fixture
def anonymous_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A Studio client that presents no token at all."""
    monkeypatch.setenv("FATHOM_API_TOKEN", _TOKEN)
    monkeypatch.setenv("FATHOM_RULESET_ROOT", _RULESET_ROOT)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def unconfigured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A Studio client for a server with no ``FATHOM_API_TOKEN`` configured."""
    monkeypatch.delenv("FATHOM_API_TOKEN", raising=False)
    monkeypatch.setenv("FATHOM_RULESET_ROOT", _RULESET_ROOT)
    with TestClient(create_app(), headers=_AUTH) as test_client:
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


def test_packs_lists_the_real_on_disk_packs(client: TestClient) -> None:
    """``/packs`` renders what is on disk, not a hardcoded UI list (AC-7.2)."""
    listed = tuple(_list_rule_packs())
    assert set(_EXPECTED_PACKS) <= set(listed)
    body = client.get("/packs").text
    # Every pack the loader found is rendered, including ones added after
    # this test was written -- a panel that lists its own fixed set would
    # pass an exact-match assertion and still be showing stale packs.
    for pack in listed:
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


def test_unconfigured_studio_refuses_every_panel(unconfigured_client: TestClient) -> None:
    """With no ``FATHOM_API_TOKEN`` configured the Studio serves no panel at all."""
    for route in _PANEL_ROUTES:
        if route == "/":  # the SPA shell carries no engine data
            continue
        assert unconfigured_client.get(route).status_code == 401
    response = unconfigured_client.post(
        "/eval",
        data={"template": "agent", "data": "{}", "ruleset": "01-hello-allow-deny"},
    )
    assert response.status_code == 401


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


# --------------------------------------------------------------------------
# Token gate (studio-api-unauthenticated / wip-studio-api-unauthenticated-surface)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("route", [r for r in _PANEL_ROUTES if r != "/"])
def test_panel_requires_token(anonymous_client: TestClient, route: str) -> None:
    """An anonymous caller gets 401 from every panel, not rule data."""
    assert anonymous_client.get(route).status_code == 401


@pytest.mark.parametrize(
    ("method", "route", "data"),
    [
        ("post", "/eval", {"template": "agent", "data": "{}", "ruleset": ""}),
        ("post", "/scenarios/01-hello-allow-deny/seed", {}),
        ("post", "/guardrail/run", {"mode": "scripted"}),
        ("post", "/audit/token", {}),
    ],
)
def test_state_changing_panel_requires_token(
    anonymous_client: TestClient,
    method: str,
    route: str,
    data: dict[str, str],
) -> None:
    """No anonymous caller can drive the engine or mint an attestation token."""
    response = getattr(anonymous_client, method)(route, data=data)
    assert response.status_code == 401


def test_spa_shell_is_reachable_without_a_token(anonymous_client: TestClient) -> None:
    """``/`` still serves the SPA shell — it carries no engine data."""
    assert anonymous_client.get("/").status_code == 200
    assert anonymous_client.get("/health").status_code == 200


def test_token_query_param_grants_browser_cookie(anonymous_client: TestClient) -> None:
    """``/?token=`` validates the token and hands the browser a session cookie."""
    response = anonymous_client.get("/", params={"token": _TOKEN})
    assert response.status_code == 200
    granted = anonymous_client.cookies.get(TOKEN_COOKIE)
    assert granted
    # The cookie is an opaque session id, never the API token: the browser jar
    # is storage the operator does not control, and the token also opens /v1.
    assert granted != _TOKEN
    assert _TOKEN not in granted
    # The cookie now unlocks the panels for the plain HTML forms.
    assert anonymous_client.get("/packs").status_code == 200


def test_wrong_token_query_param_grants_nothing(anonymous_client: TestClient) -> None:
    """A bogus ``?token=`` mints no cookie and unlocks nothing."""
    anonymous_client.get("/", params={"token": "wrong-token"})
    assert anonymous_client.cookies.get(TOKEN_COOKIE) is None
    assert anonymous_client.get("/packs").status_code == 401


def test_granted_cookie_is_not_a_usable_bearer_token(anonymous_client: TestClient) -> None:
    """A stolen Studio cookie cannot be replayed as a bearer token on ``/v1``.

    This is the point of minting a session id instead of echoing the API token:
    the mounted REST app validates ``FATHOM_API_TOKEN``, which the cookie is not.
    """
    anonymous_client.get("/", params={"token": _TOKEN})
    granted = anonymous_client.cookies.get(TOKEN_COOKIE)
    assert granted
    stolen = anonymous_client.get("/api/v1/rules", headers={"Authorization": f"Bearer {granted}"})
    assert stolen.status_code == 401
