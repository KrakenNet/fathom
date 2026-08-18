"""FastAPI REST server for Fathom rule evaluation."""

from __future__ import annotations

import base64
import binascii
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
from fathom.errors import CompilationError, EvaluationError, EvaluationLimitError
from fathom.errors import ValidationError as FathomValidationError
from fathom.integrations.auth import verify_admin_token, verify_token
from fathom.integrations.paths import PathJailError, resolve_ruleset
from fathom.integrations.sessions import (
    SessionLimitError,
    SessionRulesetMismatchError,
    SessionStore,
)
from fathom.models import (
    AssertFactRequest,
    AssertFactResponse,
    CompileRequest,
    CompileResponse,
    ErrorResponse,
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
    """Return the shared error envelope (``models.ErrorResponse``)."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, detail=detail, field=None).model_dump(),
    )


def _require_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency enforcing data-plane bearer-token auth."""
    if not verify_token(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _require_admin_auth(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency enforcing the scoped reload admin token.

    When ``FATHOM_ADMIN_TOKEN`` is set, only that token is accepted (the
    data-plane ``FATHOM_API_TOKEN`` is rejected). When it is unset, this
    falls back to the data-plane token — backward compatible.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


# Maximum accepted request body for POST /v1/rules/reload. A ruleset that
# large is almost certainly hostile or a misconfiguration; the YAML parser
# should never see an unbounded body. Overridable via FATHOM_MAX_RELOAD_BYTES.
_DEFAULT_MAX_RELOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def _max_reload_bytes() -> int:
    """Return the reload body cap in bytes (env-overridable, read per call)."""
    raw = os.environ.get("FATHOM_MAX_RELOAD_BYTES", "")
    if not raw:
        return _DEFAULT_MAX_RELOAD_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_RELOAD_BYTES
    return value if value > 0 else _DEFAULT_MAX_RELOAD_BYTES


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


def _session_engine(session_id: str, rules_path: str) -> Engine:
    """Return the session Engine, mapping store rejections onto HTTP status.

    A session is bound to the ruleset it was created with; addressing it
    with a different one is 409 rather than a silent evaluation under the
    wrong policy.
    """
    try:
        return session_store.get_or_create(session_id, rules_path)
    except SessionRulesetMismatchError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "session_ruleset_mismatch", "detail": str(exc)},
        ) from exc
    except SessionLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "session_limit_exceeded", "detail": str(exc)},
        ) from exc


def _require_session_engine(session_id: str) -> Engine:
    """Return the Engine for an existing session, or raise 404."""
    engine = session_store.get(session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="session not found")
    return engine


# Maximum accepted request body on the data-plane routes. POST /v1/evaluate
# runs a quadratic CLIPS join over the facts it is handed, so an unbounded
# body is an unbounded amount of server CPU. Sized to stay above the
# 1,000,000-character cap on CompileRequest.yaml_content once JSON-encoded.
# The reload route enforces its own cap (FATHOM_MAX_RELOAD_BYTES) and is
# skipped here. Overridable via FATHOM_MAX_REQUEST_BYTES.
_DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024  # 2 MB
_RELOAD_PATH = "/v1/rules/reload"


def _max_request_bytes() -> int:
    """Return the data-plane body cap in bytes (env-overridable, per call)."""
    raw = os.environ.get("FATHOM_MAX_REQUEST_BYTES", "")
    if not raw:
        return _DEFAULT_MAX_REQUEST_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_REQUEST_BYTES
    return value if value > 0 else _DEFAULT_MAX_REQUEST_BYTES


class BodySizeLimitMiddleware:
    """Reject over-sized request bodies while they stream in.

    The cap is enforced on the bytes actually received rather than the
    Content-Length header (chunked bodies lie), and it aborts as soon as
    the running total passes the limit so a hostile body is never fully
    buffered. Raising :class:`HTTPException` from inside ``receive`` is
    deliberate: FastAPI re-raises it out of body parsing unchanged, so it
    renders through the normal error envelope.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == _RELOAD_PATH:
            await self._app(scope, receive, send)
            return

        limit = _max_request_bytes()
        total = 0

        async def counting_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error": "payload_too_large",
                            "detail": f"request body exceeds the {limit}-byte limit",
                        },
                    )
            return message

        await self._app(scope, counting_receive, send)


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

app.add_middleware(BodySizeLimitMiddleware)


# Slug used in the ``error`` field when an HTTPException carries only a
# plain-string detail. One envelope for every error the API returns:
# ``{"error": str, "detail": str, "field": str | None}`` (models.ErrorResponse).
_ERROR_SLUGS = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "unavailable",
}


# Every route renders errors through the ErrorResponse envelope above, so
# declare it once and attach it to each route. Without this the exported
# OpenAPI still advertises FastAPI's default 422 shape (a `detail` LIST of
# error objects), which is not what the API returns — clients written
# against the published spec fail to parse a real error.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Invalid request"},
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    413: {"model": ErrorResponse, "description": "Request body too large"},
    422: {"model": ErrorResponse, "description": "Request body failed validation"},
    503: {"model": ErrorResponse, "description": "Service unavailable"},
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Render every HTTPException through the single ErrorResponse envelope.

    Registered on the Starlette base class so framework-raised errors (405,
    404 on an unknown route) use the same envelope as the app's own.
    """
    fallback = _ERROR_SLUGS.get(exc.status_code, "error")
    if isinstance(exc.detail, dict):
        body = ErrorResponse(
            error=str(exc.detail.get("error", fallback)),
            detail=str(exc.detail.get("detail", "")),
            field=exc.detail.get("field"),
        )
    else:
        body = ErrorResponse(error=fallback, detail=str(exc.detail), field=None)
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render FastAPI's body-validation errors through the same envelope."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    # `loc` is ("body", <field>, ...) for a field error but ("body", <int>)
    # for a malformed-JSON error, where the int is a BYTE OFFSET. Rendering
    # that offset as `"field": "1"` presents a position as a field name, so
    # drop non-identifier parts and report no field instead.
    loc = ".".join(
        str(part) for part in first.get("loc", ()) if part != "body" and not isinstance(part, int)
    )
    body = ErrorResponse(
        error="validation_error",
        detail=str(first.get("msg", "invalid request body")),
        field=loc or None,
    )
    return JSONResponse(status_code=422, content=body.model_dump())


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
    body = ErrorResponse(error="validation_error", detail=str(exc), field=exc.slot or None)
    return JSONResponse(status_code=422, content=body.model_dump())


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


session_store = SessionStore()


@app.post(
    "/v1/evaluate",
    response_model=EvaluateResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """Evaluate facts against a ruleset (stateless or stateful).

    Request-scoped: the supplied facts are asserted, evaluated, then
    withdrawn (:meth:`Engine.evaluate_once`), so an earlier request on the
    same session can never change this one's decision.

    Declared ``def`` (not ``async def``) on purpose: CLIPS evaluation is
    blocking CPU work, so Starlette must run it in the threadpool rather
    than on the event loop, where one large request stalls every other
    connection.
    """
    resolved = _resolve_user_ruleset(request.ruleset)
    if request.session_id:
        engine = _session_engine(request.session_id, resolved)
    else:
        engine = Engine.from_rules(resolved)

    try:
        result = engine.evaluate_once(
            facts=[(f.template, f.data) for f in request.facts],
        )
    except EvaluationLimitError as exc:
        # The ruleset exhausted its activation budget, which is how a
        # non-terminating ruleset is stopped. 503 rather than 500: this is a
        # policy problem, the request produced no decision, and the server is
        # still healthy.
        raise HTTPException(
            status_code=503,
            detail={"error": "evaluation_failed", "detail": str(exc)},
        ) from exc
    except EvaluationError as exc:
        # Any other evaluation failure is a server-side fault, not something
        # the caller can fix by retrying or by sending different facts.
        raise HTTPException(
            status_code=500,
            detail={"error": "evaluation_error", "detail": str(exc)},
        ) from exc

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
    engine = _require_session_engine(session_id)
    items = [t.model_dump() for t in engine.template_registry.values()]
    return _make_list_response(items)


@app.get("/v1/rules", dependencies=[Depends(_require_auth)])
async def list_rules(
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all loaded rule definitions for a session."""
    engine = _require_session_engine(session_id)
    items = [r.model_dump() for r in engine.rule_registry.values()]
    return _make_list_response(items)


@app.get("/v1/modules", dependencies=[Depends(_require_auth)])
async def list_modules(
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all registered module definitions for a session."""
    engine = _require_session_engine(session_id)
    items = [m.model_dump() for m in engine.module_registry.values()]
    return _make_list_response(items)


@app.post(
    "/v1/compile",
    response_model=CompileResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def compile_yaml(request: CompileRequest, http_request: Request) -> CompileResponse:
    """Compile YAML content into CLIPS constructs.

    Rule literals are emitted according to the declared slot type, so this
    endpoint compiles against the templates of the engine mounted on
    ``app.state.engine`` when one is configured. Without an engine there is
    no type context available and literals fall back to the untyped form —
    which may differ from what ``Engine.from_rules`` builds for the same
    YAML. Post the templates alongside the rules, or use ``fathom compile``
    against the ruleset directory, when the exact form matters.

    Declared ``def`` so compilation runs in the threadpool, not on
    the event loop.
    """
    state_engine = getattr(http_request.app.state, "engine", None)
    templates = state_engine.template_registry if state_engine is not None else None
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
            # Slot types decide how a literal is emitted (a STRING slot gets
            # a quoted CLIPS string, a SYMBOL slot does not), so compile
            # against the loaded engine's templates. Without them this
            # endpoint returned CLIPS that the same server's engine would
            # never build — and that CLIPS does not even accept
            # ([CSTRNCHK1]) for a string slot holding e.g. an email address.
            for rule_defn in ruleset.rules:
                constructs.append(
                    compiler.compile_rule(rule_defn, ruleset.module, templates),
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
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def assert_fact(request: AssertFactRequest) -> AssertFactResponse:
    """Assert a single fact into a session's working memory.

    Unlike ``/v1/evaluate``, this endpoint does **not** create sessions on
    the fly — the ``session_id`` must reference a session previously
    created via ``/v1/evaluate``. Unknown session ids return 404.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(request.session_id)
    engine.assert_fact(request.template, request.data)
    return AssertFactResponse(success=True)


@app.post(
    "/v1/query",
    response_model=QueryFactsResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def query_facts(request: QueryFactsRequest) -> QueryFactsResponse:
    """Query a session's working memory for facts matching template + filter.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(request.session_id)
    facts = engine.query(request.template, request.filter)
    return QueryFactsResponse(facts=facts)


@app.delete(
    "/v1/facts",
    response_model=RetractFactsResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def retract_facts(request: RetractFactsRequest) -> RetractFactsResponse:
    """Retract facts matching template + optional filter from working memory.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404. Retract is by
    template + filter (matches the gRPC surface), not by fact index.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(request.session_id)
    count = engine.retract(request.template, request.filter)
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
    except Exception:
        # Audit failure must not crash a reload, but the record must not
        # vanish either — log it in full so the event is recoverable from
        # the process log when the sink rejects it.
        logger.exception("audit sink write failed; dropped record: %r", record)


@app.post(
    "/v1/rules/reload",
    dependencies=[Depends(_require_admin_auth)],
    # The body is read and validated manually (to enforce the size cap on
    # real bytes before parsing), so FastAPI no longer infers the request
    # body schema from a parameter. Re-declare it here so the OpenAPI export
    # keeps documenting the RulesetReloadRequest shape.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": RulesetReloadRequest.model_json_schema()}},
        }
    },
)
async def reload_rules(
    request: Request,
) -> JSONResponse:
    """Atomically swap the loaded ruleset with a new (optionally signed) one.

    Requires the scoped admin token (``FATHOM_ADMIN_TOKEN`` when set, else the
    data-plane token). Bodies larger than ``FATHOM_MAX_RELOAD_BYTES`` (default
    5 MB) are rejected with 413 before any YAML parsing — the cap is enforced
    on the actual bytes received, not the Content-Length header (chunked
    bodies lie). Rate limiting is host-level (reverse proxy) by design.

    See design C5 / AC-5.1 / AC-5.4–5.6 / AC-5.8.
    """
    # --- body size cap (enforced on real bytes, not Content-Length) ---
    # Stream the body in chunks and abort as soon as the running total
    # exceeds the limit, so a hostile chunked request (which can lie in
    # its Content-Length header) is rejected without being fully buffered.
    limit = _max_reload_bytes()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return _make_error_response(
                413,
                "payload_too_large",
                f"request body exceeds the {limit}-byte reload limit",
            )
        chunks.append(chunk)
    raw_body = b"".join(chunks)

    try:
        payload = RulesetReloadRequest.model_validate_json(raw_body)
    except PydanticValidationError as exc:
        errs = exc.errors()
        detail = errs[0].get("msg", "invalid request body") if errs else "invalid request body"
        return _make_error_response(422, "validation_error", detail)

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
            "ruleset_hash_before": hash_before,
            "ruleset_hash_after": hash_after,
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
    loaded_at = getattr(state, "last_reload_iso", None) or getattr(state, "boot_time_iso", None)
    return {
        "ruleset_hash": ruleset_hash,
        "version": _fathom_version,
        "loaded_at": loaded_at,
    }


_RULESET_PUBKEY_ERROR = (
    "ruleset pubkey unreadable or missing; set FATHOM_RULESET_PUBKEY_PATH or enable dev escape"
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
