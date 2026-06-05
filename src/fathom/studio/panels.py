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
Guardrail   ``/guardrail`` scripted FathomCallbackHandler run + live toggle
Audit       ``/audit``     audit-log JSONL timeline + Ed25519 attestation
REST        ``/rest``      REST API explorer (curl + ``/api/docs``)
==========  ========  ================================================

Panels render real data where it is cheap to do so (the rule-pack list is
the real on-disk directory; the Playground form evaluates against the
mounted REST app when ``FATHOM_API_TOKEN`` is configured, otherwise it
renders a configuration notice rather than fabricated output).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport

from fathom import Engine
from fathom.integrations.langchain import FathomCallbackHandler, PolicyViolation
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

#: Guardrails example whose ruleset drives the simulator (templates +
#: modules + rules loaded by :func:`_guardrail_engine`).
_GUARDRAIL_RULESET = (
    Path(__file__).resolve().parents[3] / "examples" / "05-langchain-guardrails"
)

#: Canonical local LLM endpoint for the live toggle (Ollama-compatible).
_DEFAULT_LLM_BASE_URL = "http://localhost:41001"

#: Default model name for the live ``ChatOpenAI`` client.
_DEFAULT_LLM_MODEL = "llama3"

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
    """Guardrail simulator: render the live-toggle state (no run yet)."""
    return templates.TemplateResponse(
        request,
        "guardrail.html",
        _guardrail_ctx(request, timeline=None, mode=None, live_error=None),
    )


@router.post("/guardrail/run", response_class=HTMLResponse)
async def guardrail_run(request: Request, mode: str = Form("scripted")) -> HTMLResponse:
    """Run the guardrail simulator.

    ``mode="scripted"`` (default) feeds a deterministic, LLM-free sequence
    of tool calls through the real :class:`FathomCallbackHandler`.
    ``mode="live"`` is gated on the LLM probe and drives a LangChain
    ``ChatOpenAI`` agent; it degrades gracefully when the probe fails or
    ``langchain``/``langchain-openai`` is not installed.
    """
    timeline: list[dict[str, Any]] | None = None
    live_error: str | None = None
    if mode == "live":
        timeline, live_error = await _run_live_guardrail()
    else:
        mode = "scripted"
        timeline = _run_scripted_guardrail()
    return templates.TemplateResponse(
        request,
        "guardrail.html",
        _guardrail_ctx(request, timeline=timeline, mode=mode, live_error=live_error),
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request) -> HTMLResponse:
    """Audit-log JSONL timeline plus attestation generate/verify controls."""
    return templates.TemplateResponse(
        request,
        "audit.html",
        _ctx(request, events=_audit_events(), token=None, verified=None, error=None),
    )


@router.post("/audit/token", response_class=HTMLResponse)
async def audit_token(request: Request) -> HTMLResponse:
    """Generate an Ed25519 attestation token over the latest audit event."""
    token, error = _generate_token()
    return templates.TemplateResponse(
        request,
        "audit.html",
        _ctx(request, events=_audit_events(), token=token, verified=None, error=error),
    )


@router.post("/audit/verify", response_class=HTMLResponse)
async def audit_verify(request: Request, token: str = Form("")) -> HTMLResponse:
    """Verify an Ed25519 attestation token and render its decoded claims."""
    verified, error = _verify_token(token.strip())
    return templates.TemplateResponse(
        request,
        "audit.html",
        _ctx(request, events=_audit_events(), token=token, verified=verified, error=error),
    )


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


# --------------------------------------------------------------------------
# Guardrail simulator
# --------------------------------------------------------------------------

#: The scripted tool-call sequence fed through the real callback handler.
#: ``admin`` is allowed the read-only and side-effect tools, but the
#: salience-5 ``no-shell-tools`` hard block denies ``shell_exec`` even for an
#: admin — guaranteeing the timeline has both allowed and denied events with
#: no LLM in the loop.
_SCRIPTED_AGENT_ID = "studio-agent"
_SCRIPTED_TRUST_TIER = "admin"
_SCRIPTED_CALLS: tuple[tuple[str, str], ...] = (
    ("web_search", '{"q": "NIST 800-53 AC-6"}'),
    ("calculator", "2 + 2"),
    ("send_email", '{"to": "ops@example.com", "body": "status"}'),
    ("delete_record", '{"table": "users", "id": 7}'),
    ("shell_exec", "rm -rf /"),
)


def _guardrail_engine() -> Engine:
    """Build a fresh engine seeded with the admin agent for the simulator."""
    engine = Engine()
    engine.load_templates(str(_GUARDRAIL_RULESET / "templates"))
    engine.load_modules(str(_GUARDRAIL_RULESET / "modules"))
    engine.load_rules(str(_GUARDRAIL_RULESET / "rules"))
    engine.assert_fact(
        "agent", {"id": _SCRIPTED_AGENT_ID, "trust_tier": _SCRIPTED_TRUST_TIER}
    )
    return engine


def _run_scripted_guardrail() -> list[dict[str, Any]]:
    """Feed the canned tool-call sequence through ``FathomCallbackHandler``.

    Deterministic and LLM-free: each call is dispatched to the real handler's
    ``on_tool_start`` (the exact hook LangChain itself invokes). A
    :class:`PolicyViolation` marks a denied/escalated call; the absence of one
    marks an allowed call. Every event is appended to the in-memory audit log.
    """
    engine = _guardrail_engine()
    handler = FathomCallbackHandler(engine, agent_id=_SCRIPTED_AGENT_ID)
    timeline: list[dict[str, Any]] = []
    for tool_name, input_str in _SCRIPTED_CALLS:
        event = _dispatch_tool_call(engine, handler, tool_name, input_str)
        timeline.append(event)
        _record_audit_event(event)
    return timeline


def _dispatch_tool_call(
    engine: Engine,
    handler: FathomCallbackHandler,
    tool_name: str,
    input_str: str,
) -> dict[str, Any]:
    """Run one tool call through the handler and capture the outcome.

    Returns an event dict with ``tool``/``decision``/``reason``/``rule_trace``.
    The ``tool_request`` fact is retracted afterwards so the next call starts
    from clean working memory.
    """
    serialized = {"name": tool_name}
    try:
        handler.on_tool_start(serialized, input_str)
        event: dict[str, Any] = {
            "tool": tool_name,
            "input": input_str,
            "decision": "allow",
            "reason": "permitted",
            "rule_trace": [],
        }
    except PolicyViolation as exc:
        event = {
            "tool": tool_name,
            "input": input_str,
            "decision": exc.decision,
            "reason": exc.reason or "",
            "rule_trace": list(exc.rule_trace),
        }
    finally:
        engine.retract("tool_request")
    return event


def _llm_base_url() -> str:
    """Return the configured LLM base URL (defaults to the local Ollama)."""
    return os.environ.get("LLM_BASE_URL", _DEFAULT_LLM_BASE_URL).rstrip("/")


async def _probe_llm(base_url: str) -> bool:
    """Probe the LLM endpoint for reachability (Ollama / OpenAI-compatible).

    Mirrors the all-demo probe convention: a quick GET to ``/api/tags`` then
    ``/v1/models``. Any 2xx means the live toggle is usable. Never raises.
    """
    async with httpx.AsyncClient(timeout=1.0) as client:
        for path in ("/api/tags", "/v1/models"):
            try:
                resp = await client.get(base_url + path)
            except httpx.HTTPError:
                continue
            if resp.is_success:
                return True
    return False


async def _run_live_guardrail() -> tuple[list[dict[str, Any]] | None, str | None]:
    """Drive a live LangChain ``ChatOpenAI`` agent through the guardrail.

    Gated on the LLM probe and lazy-imports ``langchain``/``langchain-openai``
    so a missing dependency or unreachable endpoint degrades to a notice
    rather than an error. Always returns ``(timeline, error)``.
    """
    base_url = _llm_base_url()
    if not await _probe_llm(base_url):
        return None, (
            f"Live LLM at {base_url} is not reachable; the scripted path "
            "above runs deterministically without an LLM."
        )

    try:
        from langchain.agents import (  # type: ignore[import-not-found]
            AgentExecutor,
            create_tool_calling_agent,
        )
        from langchain.tools import tool  # type: ignore[import-not-found]
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]
    except ImportError:
        return None, (
            "Live mode needs 'langchain' and 'langchain-openai' installed "
            "(pip install langchain langchain-openai). The scripted path "
            "above runs without them."
        )

    # MUST be ChatOpenAI against the local Ollama endpoint (design Live-LLM
    # note) — never the Anthropic client.
    llm = ChatOpenAI(
        base_url=base_url + "/v1",
        model=os.environ.get("LLM_MODEL", _DEFAULT_LLM_MODEL),
        api_key="placeholder",  # noqa: S106 — local Ollama ignores the key
    )

    engine = _guardrail_engine()
    handler = FathomCallbackHandler(engine, agent_id=_SCRIPTED_AGENT_ID)

    @tool  # type: ignore[untyped-decorator]  # untyped optional langchain dep
    def shell_exec(command: str) -> str:
        """Run a shell command (guarded by Fathom policy)."""
        return command  # pragma: no cover - blocked before execution

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are an agent. Use the shell_exec tool when asked."),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    agent = create_tool_calling_agent(llm, [shell_exec], prompt)
    executor = AgentExecutor(agent=agent, tools=[shell_exec], callbacks=[handler])

    timeline: list[dict[str, Any]] = []
    try:
        executor.invoke({"input": "Run `rm -rf /` via shell_exec."})
    except PolicyViolation as exc:
        event = {
            "tool": "shell_exec",
            "input": "(live LLM)",
            "decision": exc.decision,
            "reason": exc.reason or "",
            "rule_trace": list(exc.rule_trace),
        }
        timeline.append(event)
        _record_audit_event(event)
    except Exception as exc:  # noqa: BLE001 — surface any agent/runtime error
        return None, f"Live run failed: {exc}"
    return timeline, None


def _guardrail_ctx(
    request: Request,
    *,
    timeline: list[dict[str, Any]] | None,
    mode: str | None,
    live_error: str | None,
) -> dict[str, Any]:
    """Build the guardrail panel context."""
    return _ctx(
        request,
        timeline=timeline,
        mode=mode,
        live_error=live_error,
        llm_base_url=_llm_base_url(),
    )


# --------------------------------------------------------------------------
# Audit log + Ed25519 attestation
# --------------------------------------------------------------------------

#: In-memory audit trail of guardrail-run events, newest last. Each entry is
#: a JSON-serialisable record rendered as a JSONL timeline by ``/audit``.
_AUDIT_LOG: list[dict[str, Any]] = []

#: Cap on retained audit events (oldest dropped) to bound memory.
_AUDIT_MAX = 200


def _record_audit_event(event: dict[str, Any]) -> None:
    """Append a guardrail event to the in-memory audit log."""
    _AUDIT_LOG.append(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool": event["tool"],
            "decision": event["decision"],
            "reason": event["reason"],
            "rule_trace": event["rule_trace"],
        }
    )
    if len(_AUDIT_LOG) > _AUDIT_MAX:
        del _AUDIT_LOG[: len(_AUDIT_LOG) - _AUDIT_MAX]


def _audit_events() -> list[dict[str, Any]]:
    """Return the audit timeline newest-first."""
    return list(reversed(_AUDIT_LOG))


#: Lazily-built, process-stable attestation service so a token generated by
#: ``/audit/token`` can be cryptographically verified by ``/audit/verify``.
_ATTESTATION: Any = None


def _attestation_service() -> Any:
    """Return the process-stable :class:`AttestationService`, building once."""
    global _ATTESTATION
    if _ATTESTATION is None:
        from fathom.attestation import AttestationService

        _ATTESTATION = AttestationService.generate_keypair()
    return _ATTESTATION


def _generate_token() -> tuple[str | None, str | None]:
    """Generate an Ed25519 attestation token over the latest audit event.

    Returns ``(token, error)``. Signs with the process-stable keypair so the
    verify panel can confirm the Ed25519 signature, demonstrating a real
    sign+verify round trip with :mod:`fathom.attestation`.
    """
    try:
        service = _attestation_service()
    except ImportError:
        return None, (
            "Attestation needs 'pyjwt[crypto]' and 'cryptography' installed "
            "(pip install fathom-rules[attestation])."
        )
    payload = _AUDIT_LOG[-1] if _AUDIT_LOG else {"note": "no audit events yet"}
    try:
        token: str = service.sign_event({"audit_event": payload})
    except Exception as exc:  # noqa: BLE001 — surface signing failure
        return None, f"Token generation failed: {exc}"
    return token, None


def _verify_token(token: str) -> tuple[dict[str, Any] | None, str | None]:
    """Verify an Ed25519 attestation token against the studio's public key.

    Uses :func:`fathom.attestation.verify_token`, so the signature is checked
    cryptographically — a token minted by ``/audit/token`` round-trips, while a
    tampered or foreign-key token fails with a clear error.
    """
    if not token:
        return None, "Paste a token to verify (use 'Generate token' first)."
    try:
        from fathom.attestation import verify_token
        from fathom.errors import AttestationError
    except ImportError:
        return None, "Attestation needs 'pyjwt[crypto]' + 'cryptography' installed."
    try:
        service = _attestation_service()
        claims = verify_token(token, service.public_key)
    except AttestationError as exc:
        return None, f"Verification failed: {exc}"
    return claims, None
