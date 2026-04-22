"""FastAPI REST server for Fathom rule evaluation."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    import prometheus_client
    from prometheus_fastapi_instrumentator import Instrumentator

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover
    _HAS_PROMETHEUS = False

from pydantic import ValidationError as PydanticValidationError

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

logger = logging.getLogger(__name__)


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


class RulesetReloadRequest(BaseModel):
    """Request body for ``POST /v1/rules/reload``.

    Exactly one of ``ruleset_path`` / ``ruleset_yaml`` must be supplied.
    ``signature`` is base64-encoded raw 64-byte Ed25519 over the YAML bytes.
    """

    ruleset_path: str | None = None
    ruleset_yaml: str | None = None
    signature: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_audit(sink: Any | None, record: dict[str, Any]) -> None:
    """Write ``record`` to ``sink`` if configured; swallow sink errors.

    Sink is duck-typed: any object with a ``write(record)`` method.
    The hot-reload audit shape (``event_type`` + 4 fields) does not match
    the eval-shaped ``AuditRecord`` model, so the record is passed as a
    plain dict.
    """
    if sink is None:
        return
    try:
        sink.write(record)
    except Exception:  # pragma: no cover - audit failure must not crash reload
        logger.exception("audit sink write failed")


@app.post("/v1/rules/reload", dependencies=[Depends(_require_auth)])
async def reload_rules(
    payload: RulesetReloadRequest,
    request: Request,
) -> JSONResponse:
    """Atomically swap the loaded ruleset with a new (optionally signed) one.

    See design C5 / AC-5.1 / AC-5.4–5.6 / AC-5.8.
    """
    state = request.app.state
    engine = getattr(state, "engine", None)
    attestation = getattr(state, "attestation", None)
    audit_sink = getattr(state, "audit_sink", None)
    pubkey = getattr(state, "ruleset_pubkey", None)
    require_signature = getattr(state, "require_signature", True)

    if engine is None or attestation is None:
        return _make_error_response(
            503,
            "not_ready",
            "engine or attestation not configured",
        )

    # --- exactly-one-of ruleset_path / ruleset_yaml ---
    has_path = payload.ruleset_path is not None
    has_yaml = payload.ruleset_yaml is not None
    if has_path == has_yaml:
        return _make_error_response(
            400,
            "invalid_request",
            "exactly one of ruleset_path or ruleset_yaml must be provided",
        )

    # --- materialise raw YAML bytes ---
    if has_yaml:
        assert payload.ruleset_yaml is not None
        raw_yaml_bytes = payload.ruleset_yaml.encode("utf-8")
    else:
        assert payload.ruleset_path is not None
        resolved = _resolve_user_ruleset(payload.ruleset_path)
        try:
            with open(resolved, "rb") as f:
                raw_yaml_bytes = f.read()
        except OSError as exc:
            return _make_error_response(
                400,
                "invalid_request",
                f"unable to read ruleset_path: {exc}",
            )

    # --- decode signature (base64 string → bytes) ---
    sig_bytes: bytes | None = None
    if payload.signature is not None:
        try:
            sig_bytes = base64.b64decode(payload.signature, validate=True)
        except (binascii.Error, ValueError):
            return _make_error_response(
                400,
                "invalid_request",
                "signature must be valid base64",
            )

    # --- signature verification (fail-closed when required) ---
    hash_before = engine.ruleset_hash
    if require_signature:
        if pubkey is None:
            # Should have failed at build_app; defensive 500.
            return _make_error_response(
                500,
                "server_misconfigured",
                "require_signature=true but ruleset pubkey is not loaded",
            )
        if sig_bytes is None:
            # Missing signature is a signature-rejection, not a request shape
            # error — emit audit "ruleset_reload_rejected" per AC-5.5.
            _write_audit(
                audit_sink,
                {
                    "event_type": "ruleset_reload_rejected",
                    "reason": "missing_signature",
                    "ruleset_hash_before": hash_before,
                    "timestamp": _now_iso(),
                    "actor": "bearer-token",
                },
            )
            return _make_error_response(
                400,
                "unsigned_ruleset",
                "signature is required but was not provided",
            )
        try:
            from fathom.integrations.ruleset_sig import (
                RulesetSignatureError,
                verify_ruleset_signature,
            )

            verify_ruleset_signature(raw_yaml_bytes, sig_bytes, pubkey)
        except RulesetSignatureError as exc:
            _write_audit(
                audit_sink,
                {
                    "event_type": "ruleset_reload_rejected",
                    "reason": str(exc),
                    "ruleset_hash_before": hash_before,
                    "timestamp": _now_iso(),
                    "actor": "bearer-token",
                },
            )
            return _make_error_response(
                400,
                "unsigned_ruleset",
                "ruleset signature verification failed",
            )

    # --- happy path: atomic-swap reload ---
    try:
        hash_before, hash_after = engine.reload_rules(
            raw_yaml_bytes,
            sig_bytes if require_signature else None,
            pubkey if require_signature else None,
        )
    except CompilationError as exc:
        return _make_error_response(
            400,
            "invalid_ruleset",
            str(exc).split("\n", 1)[0],
        )

    timestamp = _now_iso()
    attestation_token = attestation.sign_event(
        {
            "ruleset_hash_before": hash_before,
            "ruleset_hash_after": hash_after,
            "actor": "bearer-token",
            "timestamp": timestamp,
        }
    )

    _write_audit(
        audit_sink,
        {
            "event_type": "ruleset_reloaded",
            "ruleset_hash_before": hash_before,
            "ruleset_hash_after": hash_after,
            "actor": "bearer-token",
            "timestamp": timestamp,
        },
    )

    # Track last reload time for GET /v1/status (T-2.8).
    state.last_reload_iso = timestamp

    return JSONResponse(
        status_code=200,
        content={
            "hash_before": hash_before,
            "hash_after": hash_after,
            "attestation_token": attestation_token,
        },
    )


@app.get("/v1/status")
async def status(request: Request) -> dict[str, str | None]:
    """Report engine liveness info: loaded ruleset hash, version, last-load time.

    Unauthenticated (matches ``/health``): status is a liveness/info endpoint
    used by orchestrators and operators to confirm which ruleset is live.
    """
    state = request.app.state
    engine = getattr(state, "engine", None)
    ruleset_hash = engine.ruleset_hash if engine is not None else None
    loaded_at = getattr(state, "last_reload_iso", None) or getattr(
        state, "boot_time_iso", None
    )
    return {
        "ruleset_hash": ruleset_hash,
        "version": _fathom_version,
        "loaded_at": loaded_at,
    }


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

    Also seeds ``app.state`` with injectable defaults for engine,
    attestation, and audit sink — callers (server entrypoint, tests)
    overwrite these post-build.
    """
    pubkey_path = os.environ.get("FATHOM_RULESET_PUBKEY_PATH")
    allow_unsigned = os.environ.get("FATHOM_ALLOW_UNSIGNED_RULESETS") == "1"

    # Default state slots used by POST /v1/rules/reload. Callers inject
    # real instances after build_app() returns.
    app.state.engine = None
    app.state.attestation = None
    app.state.audit_sink = None
    app.state.require_signature = require_signature
    app.state.last_reload_iso = None
    app.state.boot_time_iso = _now_iso()

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
