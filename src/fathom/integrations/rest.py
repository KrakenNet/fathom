"""FastAPI REST server for Fathom rule evaluation."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    import prometheus_client
    from prometheus_fastapi_instrumentator import Instrumentator

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover
    _HAS_PROMETHEUS = False

from pydantic import ValidationError as PydanticValidationError

logger = logging.getLogger(__name__)

from fathom import __version__ as _fathom_version
from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.errors import ValidationError as FathomValidationError
from fathom.integrations.auth import verify_token
from fathom.integrations.paths import PathJailError, resolve_ruleset
from fathom.models import (
    AssertFactRequest,
    AssertFactResponse,
    CompileRequest,
    CompileResponse,
    EvaluateRequest,
    EvaluateResponse,
    ModuleDefinition,
    QueryFactsRequest,
    QueryFactsResponse,
    RetractFactsRequest,
    RetractFactsResponse,
    RulesetDefinition,
    TemplateDefinition,
)


def _make_list_response(items: Sequence[Any]) -> dict[str, Any]:
    """Return a consistent list envelope: ``{"items": [...], "count": N}``."""
    return {"items": list(items), "count": len(items)}


def _make_error_response(
    status_code: int,
    error: str,
    detail: str,
) -> JSONResponse:
    """Return a consistent error envelope: ``{"error": str, "detail": str}``."""
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "detail": detail},
    )


def _require_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency enforcing bearer-token auth."""
    if not verify_token(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _resolve_user_ruleset(user_path: str) -> str:
    """Jail *user_path* under ``FATHOM_RULESET_ROOT``.

    Empty string is a valid input and resolves to the root itself — this
    lets callers evaluate against the full root directory without having
    to name a specific ruleset file.
    """
    root = os.environ.get("FATHOM_RULESET_ROOT", "")
    if not root:
        raise HTTPException(
            status_code=500,
            detail="FATHOM_RULESET_ROOT is not configured",
        )
    try:
        return str(resolve_ruleset(root, user_path))
    except PathJailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SessionStore:
    """Manages Engine instances for stateful REST sessions."""

    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_sessions: int = 1000,
    ) -> None:
        self._sessions: dict[str, tuple[Engine, float]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions

    def _cleanup_expired(self) -> None:
        """Remove expired sessions (lazy cleanup)."""
        now = time.time()
        expired = [
            sid
            for sid, (_, last_access) in self._sessions.items()
            if now - last_access > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    def get_or_create(self, session_id: str, rules_path: str) -> Engine:
        """Get existing session or create new one."""
        self._cleanup_expired()

        if session_id in self._sessions:
            engine, _ = self._sessions[session_id]
            self._sessions[session_id] = (engine, time.time())
            return engine

        if len(self._sessions) >= self._max_sessions:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "session_limit_exceeded",
                    "detail": "Maximum session limit reached",
                },
            )

        engine = Engine.from_rules(rules_path)
        self._sessions[session_id] = (engine, time.time())
        return engine


# Docs/OpenAPI are disabled by default — they leak schema and route names
# to unauthenticated callers. Set FATHOM_EXPOSE_DOCS=1 to re-enable them
# (intended for local development only).
_expose_docs = os.environ.get("FATHOM_EXPOSE_DOCS") == "1"

app = FastAPI(
    title="Fathom Rules Engine",
    version=_fathom_version,
    description="Deterministic reasoning runtime for AI agents",
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
)


_metrics_enabled = _HAS_PROMETHEUS and os.environ.get("FATHOM_METRICS") == "1"

if _metrics_enabled:
    # Instrument without exposing a public /metrics; we register an
    # auth-gated endpoint below instead.
    Instrumentator().instrument(app)

    @app.get("/metrics", dependencies=[Depends(_require_auth)])
    async def metrics() -> Response:
        """Serve Prometheus exposition format metrics (auth-gated)."""
        body = prometheus_client.generate_latest()
        return Response(
            content=body,
            media_type=prometheus_client.CONTENT_TYPE_LATEST,
        )


@app.exception_handler(FathomValidationError)
async def fathom_validation_error_handler(
    request: Request, exc: FathomValidationError
) -> JSONResponse:
    """Return 422 for Fathom validation errors."""
    content: dict[str, str | None] = {
        "error": "validation_error",
        "detail": str(exc),
    }
    if exc.slot:
        content["field"] = exc.slot
    return JSONResponse(status_code=422, content=content)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


session_store = SessionStore()


@app.post(
    "/v1/evaluate",
    response_model=EvaluateResponse,
    dependencies=[Depends(_require_auth)],
)
async def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """Evaluate facts against a ruleset (stateless or stateful)."""
    resolved = _resolve_user_ruleset(request.ruleset)
    if request.session_id:
        engine = session_store.get_or_create(request.session_id, resolved)
    else:
        engine = Engine.from_rules(resolved)

    for fact_input in request.facts:
        engine.assert_fact(fact_input.template, fact_input.data)

    result = engine.evaluate()

    return EvaluateResponse(
        decision=result.decision,
        reason=result.reason,
        rule_trace=result.rule_trace,
        module_trace=result.module_trace,
        duration_us=result.duration_us,
    )


def _require_session_id(
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> str:
    """Require a session id via the ``X-Session-Id`` header.

    Session IDs are not put in the query string because query strings are
    logged by intermediaries and leak session identifiers into access logs.
    """
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-Id header required")
    return x_session_id


@app.get("/v1/templates", dependencies=[Depends(_require_auth)])
async def list_templates(
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all registered template definitions for a session."""
    engine_tuple = session_store._sessions.get(session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    items = [t.model_dump() for t in engine.template_registry.values()]
    return _make_list_response(items)


@app.get("/v1/rules", dependencies=[Depends(_require_auth)])
async def list_rules(
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all loaded rule definitions for a session."""
    engine_tuple = session_store._sessions.get(session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    items = [r.model_dump() for r in engine.rule_registry.values()]
    return _make_list_response(items)


@app.get("/v1/modules", dependencies=[Depends(_require_auth)])
async def list_modules(
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all registered module definitions for a session."""
    engine_tuple = session_store._sessions.get(session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    items = [m.model_dump() for m in engine.module_registry.values()]
    return _make_list_response(items)


@app.post(
    "/v1/compile",
    response_model=CompileResponse,
    dependencies=[Depends(_require_auth)],
)
async def compile_yaml(request: CompileRequest) -> CompileResponse:
    """Compile YAML content into CLIPS constructs."""
    compiler = Compiler()
    errors: list[str] = []
    constructs: list[str] = []

    try:
        data = yaml.safe_load(request.yaml_content)
    except yaml.YAMLError:
        return CompileResponse(clips="", errors=["invalid YAML"])

    if not isinstance(data, dict):
        return CompileResponse(clips="", errors=["invalid YAML: expected a mapping"])

    try:
        if "templates" in data:
            for tmpl_data in data["templates"]:
                defn = TemplateDefinition(**tmpl_data)
                constructs.append(compiler.compile_template(defn))
        elif "modules" in data:
            for mod_data in data["modules"]:
                mod_defn = ModuleDefinition(**mod_data)
                constructs.append(compiler.compile_module(mod_defn))
        elif "rules" in data or "ruleset" in data:
            ruleset = RulesetDefinition(**data)
            for rule_defn in ruleset.rules:
                constructs.append(
                    compiler.compile_rule(rule_defn, ruleset.module),
                )
    except CompilationError as exc:
        # Return the construct + message but not the raw detail/file paths.
        errors.append(str(exc).split("\n", 1)[0])
    except PydanticValidationError as exc:
        # Surface the triggering message(s) but drop input values / URLs.
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ())) or "body"
            errors.append(f"{loc}: {err.get('msg', 'invalid value')}")
    except Exception:
        errors.append("internal compilation error")

    return CompileResponse(
        clips="\n".join(constructs),
        errors=errors,
    )


@app.post(
    "/v1/facts",
    response_model=AssertFactResponse,
    dependencies=[Depends(_require_auth)],
)
async def assert_fact(request: AssertFactRequest) -> AssertFactResponse:
    """Assert a single fact into a session's working memory.

    Unlike ``/v1/evaluate``, this endpoint does **not** create sessions on
    the fly — the ``session_id`` must reference a session previously
    created via ``/v1/evaluate``. Unknown session ids return 404.
    """
    engine_tuple = session_store._sessions.get(request.session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    engine.assert_fact(request.template, request.data)
    session_store._sessions[request.session_id] = (engine, time.time())
    return AssertFactResponse(success=True)


@app.post(
    "/v1/query",
    response_model=QueryFactsResponse,
    dependencies=[Depends(_require_auth)],
)
async def query_facts(request: QueryFactsRequest) -> QueryFactsResponse:
    """Query a session's working memory for facts matching template + filter.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404.
    """
    engine_tuple = session_store._sessions.get(request.session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    facts = engine.query(request.template, request.filter)
    session_store._sessions[request.session_id] = (engine, time.time())
    return QueryFactsResponse(facts=facts)


@app.delete(
    "/v1/facts",
    response_model=RetractFactsResponse,
    dependencies=[Depends(_require_auth)],
)
async def retract_facts(request: RetractFactsRequest) -> RetractFactsResponse:
    """Retract facts matching template + optional filter from working memory.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404. Retract is by
    template + filter (matches the gRPC surface), not by fact index.
    """
    engine_tuple = session_store._sessions.get(request.session_id)
    if engine_tuple is None:
        raise HTTPException(status_code=404, detail="session not found")
    engine, _ = engine_tuple
    count = engine.retract(request.template, request.filter)
    session_store._sessions[request.session_id] = (engine, time.time())
    return RetractFactsResponse(retracted_count=count)


_RULESET_PUBKEY_ERROR = (
    "ruleset pubkey unreadable or missing; "
    "set FATHOM_RULESET_PUBKEY_PATH or enable dev escape"
)


def build_app(*, require_signature: bool = True) -> FastAPI:
    """Return the REST app with ruleset pubkey bootstrapped onto ``app.state``.

    Fail-closed by default: when ``require_signature=True``, the pubkey at
    ``FATHOM_RULESET_PUBKEY_PATH`` must exist and be readable. The dev escape
    (skip pubkey load, allow unsigned reload) requires BOTH
    ``require_signature=False`` AND ``FATHOM_ALLOW_UNSIGNED_RULESETS=1``.
    """
    pubkey_path = os.environ.get("FATHOM_RULESET_PUBKEY_PATH")
    allow_unsigned = os.environ.get("FATHOM_ALLOW_UNSIGNED_RULESETS") == "1"

    if not require_signature and allow_unsigned:
        logger.warning(
            "ruleset signature verification disabled "
            "(require_signature=false + FATHOM_ALLOW_UNSIGNED_RULESETS=1); "
            "hot-reload will accept unsigned rulesets"
        )
        app.state.ruleset_pubkey = None
        return app

    if not pubkey_path:
        raise RuntimeError(_RULESET_PUBKEY_ERROR)

    try:
        with open(pubkey_path, "rb") as f:
            app.state.ruleset_pubkey = f.read()
    except OSError as exc:
        raise RuntimeError(_RULESET_PUBKEY_ERROR) from exc

    return app
