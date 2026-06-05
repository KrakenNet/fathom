"""Fathom Policy Studio panel routes.

Seven server-rendered panels presented over the mounted REST app
(:mod:`fathom.integrations.rest`, reachable under ``/api``):

==========  ========  ================================================
Panel       Route     Backend
==========  ========  ================================================
Overview    ``/``     links every panel
Playground  ``/eval`` ``POST /v1/evaluate`` → decision, reason,
                      rule_trace, module_trace, duration_us
BLP         ``/blp``  Bell-LaPadula lattice gallery (seeded later)
Temporal    ``/temporal``  temporal-rule scenarios
Rule packs  ``/packs``     lists ``fathom/src/fathom/rule_packs/``
Guardrail   ``/guardrail`` guardrail simulator (live toggle later)
Audit       ``/audit``     audit-log + attestation timeline
REST        ``/rest``      REST API explorer (curl + ``/api/docs``)
==========  ========  ================================================

Panels render real data where it is cheap to do so (the rule-pack list is
the real on-disk directory; the Playground form evaluates against the
mounted REST app when ``FATHOM_API_TOKEN`` is configured, otherwise it
renders a configuration notice rather than fabricated output).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport

from fathom.integrations.rest import app as rest_app
from fathom.studio.app import get_sid
from fathom.studio.scenarios import SCENARIOS, get_scenario
from fathom.studio.scenarios import seed as seed_scenario

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Directory holding the Jinja2 panel templates (sibling of this module).
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

#: Root of the built-in rule packs, listed by the ``/packs`` panel.
_RULE_PACKS_DIR = Path(__file__).resolve().parents[1] / "rule_packs"

#: Subdirectories under ``rule_packs/`` that are not packs.
_NON_PACK_DIRS = frozenset({"__pycache__"})

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

#: Panel metadata used by the overview page and the shared nav bar.
PANELS: tuple[tuple[str, str, str], ...] = (
    ("/eval", "Playground", "Assert facts, see allow/deny + full trace."),
    ("/blp", "BLP gallery", "Bell-LaPadula lattice and dominates()."),
    ("/temporal", "Temporal", "Rate / distinct-count rules with TTL expiry."),
    ("/packs", "Rule packs", "Browse the built-in compliance rule packs."),
    ("/guardrail", "Guardrail", "Scripted LangChain guardrail simulator."),
    ("/audit", "Audit", "Audit-log timeline and Ed25519 attestation."),
    ("/rest", "REST API", "Explore the mounted REST endpoints."),
)


def _list_rule_packs() -> list[str]:
    """Return the sorted names of the on-disk rule packs."""
    if not _RULE_PACKS_DIR.is_dir():
        return []
    return sorted(
        entry.name
        for entry in _RULE_PACKS_DIR.iterdir()
        if entry.is_dir() and entry.name not in _NON_PACK_DIRS
    )


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    """Build the base template context shared by every panel."""
    ctx: dict[str, Any] = {"request": request, "panels": PANELS}
    ctx.update(extra)
    return ctx


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request) -> HTMLResponse:
    """Studio home: a short intro plus links to every panel."""
    return templates.TemplateResponse(request, "overview.html", _ctx(request))


@router.get("/eval", response_class=HTMLResponse)
async def eval_form(request: Request) -> HTMLResponse:
    """Render the Playground form (no evaluation yet) plus scenario seeds."""
    return templates.TemplateResponse(
        request,
        "eval.html",
        _ctx(
            request,
            configured=_api_token() is not None,
            result=None,
            error=None,
            scenarios=SCENARIOS,
        ),
    )


@router.post("/eval", response_class=HTMLResponse)
async def eval_run(
    request: Request,
    template: str = Form(...),
    data: str = Form(""),
    ruleset: str = Form(""),
) -> HTMLResponse:
    """Evaluate a single fact against the mounted REST app and render the trace."""
    token = _api_token()
    result: dict[str, Any] | None = None
    error: str | None = None
    if token is None:
        error = "FATHOM_API_TOKEN is not configured; cannot evaluate."
    else:
        result, error = await _evaluate(
            sid=get_sid(request),
            token=token,
            template=template.strip(),
            data_json=data,
            ruleset=ruleset.strip(),
        )
    return templates.TemplateResponse(
        request,
        "eval.html",
        _ctx(
            request,
            configured=token is not None,
            result=result,
            error=error,
            sent={"template": template, "data": data, "ruleset": ruleset},
            scenarios=SCENARIOS,
        ),
    )


@router.get("/blp", response_class=HTMLResponse)
async def blp(request: Request) -> HTMLResponse:
    """Bell-LaPadula gallery: one-click seed of example 03 (dominates())."""
    return templates.TemplateResponse(
        request, "blp.html", _ctx(request, scenario=get_scenario("03-classification-blp"))
    )


@router.get("/temporal", response_class=HTMLResponse)
async def temporal(request: Request) -> HTMLResponse:
    """Temporal scenarios: one-click seed of example 04 (rate_exceeds)."""
    return templates.TemplateResponse(
        request, "temporal.html", _ctx(request, scenario=get_scenario("04-temporal-anomaly"))
    )


@router.post("/scenarios/{scenario_id}/seed", response_class=HTMLResponse)
async def seed_route(request: Request, scenario_id: str) -> HTMLResponse:
    """Seed an example (01–05) and render its real evaluation decision."""
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return templates.TemplateResponse(
            request,
            "scenario.html",
            _ctx(request, scenario=None, result=None, error=f"Unknown scenario: {scenario_id}"),
            status_code=404,
        )
    token = _api_token()
    result: dict[str, Any] | None = None
    error: str | None = None
    if token is None:
        error = "FATHOM_API_TOKEN is not configured; cannot seed."
    else:
        # Each seed gets its own fresh session (minted inside ``seed``) so a
        # scenario always loads its own ruleset into clean working memory,
        # independent of any prior seed in the same browser.
        result, error = await seed_scenario(scenario, token=token)
    return templates.TemplateResponse(
        request,
        "scenario.html",
        _ctx(request, scenario=scenario, result=result, error=error),
    )


@router.get("/packs", response_class=HTMLResponse)
async def packs(request: Request) -> HTMLResponse:
    """List the built-in rule packs on disk."""
    return templates.TemplateResponse(
        request, "packs.html", _ctx(request, packs_list=_list_rule_packs())
    )


@router.get("/guardrail", response_class=HTMLResponse)
async def guardrail(request: Request) -> HTMLResponse:
    """Guardrail simulator panel (live toggle wired by a later task)."""
    return templates.TemplateResponse(request, "guardrail.html", _ctx(request))


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request) -> HTMLResponse:
    """Audit-log and attestation timeline panel."""
    return templates.TemplateResponse(request, "audit.html", _ctx(request))


@router.get("/rest", response_class=HTMLResponse)
async def rest(request: Request) -> HTMLResponse:
    """REST API explorer: curl examples and a link to the mounted docs."""
    return templates.TemplateResponse(
        request, "rest.html", _ctx(request, endpoints=_REST_ENDPOINTS)
    )


#: Endpoints surfaced by the REST explorer panel (path is under ``/api``).
_REST_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/health", "Liveness probe (no auth)."),
    ("GET", "/api/v1/status", "Engine status (no auth)."),
    ("POST", "/api/v1/evaluate", "Evaluate facts against a ruleset."),
    ("GET", "/api/v1/rules", "List loaded rules (X-Session-Id)."),
    ("GET", "/api/v1/modules", "List loaded modules (X-Session-Id)."),
    ("GET", "/api/docs", "Interactive OpenAPI docs."),
)


def _api_token() -> str | None:
    """Return the configured REST bearer token, or ``None`` if unset."""
    token = os.environ.get("FATHOM_API_TOKEN")
    return token if token else None


async def _evaluate(
    *,
    sid: str,
    token: str,
    template: str,
    data_json: str,
    ruleset: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call ``POST /api/v1/evaluate`` in-process and return ``(result, error)``."""
    import json

    facts: Sequence[dict[str, Any]]
    if data_json.strip():
        try:
            parsed = json.loads(data_json)
        except json.JSONDecodeError as exc:
            return None, f"Invalid JSON for fact data: {exc}"
        if not isinstance(parsed, dict):
            return None, "Fact data must be a JSON object."
        facts = [{"template": template, "data": parsed}]
    else:
        facts = [{"template": template, "data": {}}]

    body = {"facts": list(facts), "ruleset": ruleset, "session_id": sid}
    transport = ASGITransport(app=rest_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://studio.internal"
    ) as client:
        try:
            response = await client.post(
                "/v1/evaluate",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Session-Id": sid,
                },
            )
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            return None, f"Request failed: {exc}"

    if response.status_code != 200:
        detail = _error_detail(response)
        return None, f"Evaluate failed ({response.status_code}): {detail}"
    return response.json(), None


def _error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error message from a non-200 response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, str):
            return detail
    return response.text or response.reason_phrase
