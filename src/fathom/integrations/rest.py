"""FastAPI REST server for Fathom rule evaluation."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.datastructures import State
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from fathom.attestation import AttestationService

try:
    import prometheus_client
    from prometheus_fastapi_instrumentator import Instrumentator

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover
    _HAS_PROMETHEUS = False

from pydantic import ValidationError as PydanticValidationError

from fathom import __version__ as _fathom_version
from fathom.compiler import Compiler, compile_file_by_kind
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
    QueryFactsRequest,
    QueryFactsResponse,
    RetractFactsRequest,
    RetractFactsResponse,
)
from fathom.rego import flatten_input
from fathom.yaml_utils import safe_load

__all__ = ["app", "build_app"]

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


def _session_engine(
    state: State,
    session_id: str,
    rules_path: str,
    attestation_service: AttestationService | None = None,
) -> Engine:
    """Return the session Engine, mapping store rejections onto HTTP status.

    A session is bound to the ruleset it was created with; addressing it
    with a different one is 409 rather than a silent evaluation under the
    wrong policy.

    Refused outright on a server that mounts an Engine. A session needs its
    own working memory -- ``/v1/facts`` accumulates into it -- so it cannot
    *be* the mounted Engine without every session reading every other
    session's facts; and any other Engine is compiled from the ``ruleset``
    the caller named, which is the caller choosing the deciding policy and
    escaping ``POST /v1/rules/reload`` at the same time. Neither is
    acceptable, so the mounted deployment serves stateless evaluation only.
    """
    if getattr(state, "engine", None) is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "sessions_unavailable",
                "detail": (
                    "this server serves the ruleset mounted on app.state.engine; "
                    "omit session_id, or run a server with no Engine mounted to "
                    "use sessions"
                ),
            },
        )
    try:
        store: SessionStore = state.session_store
        return store.get_or_create(session_id, rules_path, attestation_service)
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


def _require_session_engine(state: State, session_id: str) -> Engine:
    """Return the Engine for an existing session, or raise 404."""
    store: SessionStore = state.session_store
    engine = store.get(session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="session not found")
    return engine


def _data_plane_engine(
    state: State,
    resolved: str,
    attestation_service: AttestationService | None,
) -> Engine:
    """Return the Engine a stateless evaluation should run against.

    When an Engine is mounted on ``app.state.engine`` it *is* the served
    policy: it is the one ``POST /v1/rules/reload`` swaps, and a reload the
    data plane cannot see is not a reload. Every stateless request used to
    compile a fresh Engine off disk instead, so a successful hot-reload
    changed the reported ruleset hash and nothing else — the endpoint
    reported success while traffic kept being decided by the old ruleset.

    Without a mounted Engine the request's own ``ruleset`` is compiled from
    disk, which is what makes multi-ruleset serving work. The caller's path
    is resolved and jailed either way, so a traversal attempt is still
    rejected before this point.

    Raises:
        HTTPException: 400 when the named ruleset cannot be loaded. The
            underlying diagnostic names server-side absolute paths, so it is
            logged rather than returned.
    """
    mounted: Engine | None = getattr(state, "engine", None)
    if mounted is not None:
        # The mounted Engine is usually constructed before the attestation
        # service is injected onto app.state, so attach it here rather than
        # publish an `attestation_token` field that is always null.
        if mounted.attestation_service is None and attestation_service is not None:
            mounted.attestation_service = attestation_service
        return mounted
    try:
        return Engine.from_rules(resolved, attestation_service=attestation_service)
    except (CompilationError, FathomValidationError, OSError) as exc:
        logger.warning("evaluate: unable to load ruleset", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_ruleset", "detail": "ruleset could not be loaded"},
        ) from exc


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

# Routes live on a router so every app ``build_app`` returns gets its own
# FastAPI instance (and its own ``state``) carrying the same API.
router = APIRouter()


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
    500: {"model": ErrorResponse, "description": "Evaluation failed or server misconfigured"},
    503: {"model": ErrorResponse, "description": "Service unavailable"},
}

# The session GET routes read ``X-Session-Id`` off the request rather than
# through ``Header()``, so a missing header answers 400 like the rest of the
# session contract instead of FastAPI's 422. Declare it here instead.
_SESSION_HEADER = {
    "parameters": [
        {"name": "X-Session-Id", "in": "header", "required": True, "schema": {"type": "string"}}
    ]
}


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


async def metrics() -> Response:
    """Serve Prometheus exposition format metrics (auth-gated)."""
    body = prometheus_client.generate_latest()
    return Response(
        content=body,
        media_type=prometheus_client.CONTENT_TYPE_LATEST,
    )


async def fathom_validation_error_handler(
    request: Request, exc: FathomValidationError
) -> JSONResponse:
    """Return 422 for Fathom validation errors."""
    body = ErrorResponse(error="validation_error", detail=str(exc), field=exc.slot or None)
    return JSONResponse(status_code=422, content=body.model_dump())


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an unexpected failure as the declared 500 envelope, not plain text.

    The exception itself is logged by Starlette; its text may carry server
    detail, so it is not echoed.
    """
    body = ErrorResponse(error="internal_error", detail="internal server error", field=None)
    return JSONResponse(status_code=500, content=body.model_dump())


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@router.post(
    "/v1/evaluate",
    response_model=EvaluateResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def evaluate(request: EvaluateRequest, http_request: Request) -> EvaluateResponse:
    """Evaluate facts against a ruleset (stateless or stateful).

    Request-scoped: the supplied facts are asserted, evaluated, then
    withdrawn (:meth:`Engine.evaluate_once`), so an earlier request on the
    same session can never change this one's decision.

    ``ruleset`` names a path under ``FATHOM_RULESET_ROOT`` and is always
    resolved and jailed. It selects the policy only on a server with no
    Engine mounted on ``app.state.engine`` — the shipped
    ``uvicorn fathom.integrations.rest:app`` deployment. A server that
    mounts one serves *that* Engine, because it is the one
    ``POST /v1/rules/reload`` swaps and a reload the data plane cannot see
    is not a reload. ``session_id`` is refused there with 400
    ``sessions_unavailable`` for the same reason: a session's Engine is
    compiled from the ruleset the caller named, so opening one would hand
    policy selection back to the data plane.

    Declared ``def`` (not ``async def``) on purpose: CLIPS evaluation is
    blocking CPU work, so Starlette must run it in the threadpool rather
    than on the event loop, where one large request stalls every other
    connection.
    """
    resolved = _resolve_user_ruleset(request.ruleset)
    # Signing is per-engine, so the service has to be handed to the engine at
    # construction. Without this the response's `attestation_token` was a
    # field that could never be non-null: declared in the schema, published in
    # the OpenAPI document, and unreachable.
    state = http_request.app.state
    attestation = getattr(state, "attestation", None)
    if request.session_id:
        engine = _session_engine(state, request.session_id, resolved, attestation)
    else:
        engine = _data_plane_engine(state, resolved, attestation)

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
        # Any other evaluation failure, a CLIPS runtime error in a rule
        # included. No decision was produced, so none is returned.
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
        metadata=result.metadata,
        attestation_token=result.attestation_token,
    )


def _require_session_id(request: Request) -> str:
    """Require a session id via the ``X-Session-Id`` header.

    Session IDs are not put in the query string because query strings are
    logged by intermediaries and leak session identifiers into access logs.
    """
    x_session_id = request.headers.get("X-Session-Id")
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-Id header required")
    return x_session_id


@router.get(
    "/v1/templates",
    dependencies=[Depends(_require_auth)],
    responses=_ERROR_RESPONSES,
    openapi_extra=_SESSION_HEADER,
)
async def list_templates(
    request: Request,
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all registered template definitions for a session."""
    engine = _require_session_engine(request.app.state, session_id)
    items = [t.model_dump() for t in engine.template_registry.values()]
    return _make_list_response(items)


@router.get(
    "/v1/rules",
    dependencies=[Depends(_require_auth)],
    responses=_ERROR_RESPONSES,
    openapi_extra=_SESSION_HEADER,
)
async def list_rules(
    request: Request,
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all loaded rule definitions for a session."""
    engine = _require_session_engine(request.app.state, session_id)
    items = [r.model_dump() for r in engine.rule_registry.values()]
    return _make_list_response(items)


@router.get(
    "/v1/modules",
    dependencies=[Depends(_require_auth)],
    responses=_ERROR_RESPONSES,
    openapi_extra=_SESSION_HEADER,
)
async def list_modules(
    request: Request,
    session_id: str = Depends(_require_session_id),
) -> dict[str, object]:
    """Return all registered module definitions for a session."""
    engine = _require_session_engine(request.app.state, session_id)
    items = [m.model_dump() for m in engine.module_registry.values()]
    return _make_list_response(items)


#: Kinds a compiled document returns, in build order. The focus order is a
#: per-evaluation command, not a construct, so it is not returned.
_COMPILE_KINDS = ("templates", "modules", "functions", "rules")


@router.post(
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

    try:
        data = safe_load(request.yaml_content)
    except yaml.YAMLError:
        return CompileResponse(clips="", errors=["invalid YAML"])

    if not isinstance(data, dict):
        return CompileResponse(clips="", errors=["invalid YAML: expected a mapping"])

    # Compile through the same function `fathom compile` uses, so a document
    # is classified (and refused) exactly as the CLI and loader do. It reads a
    # file, so the content is written to a private temp dir; the file sits two
    # levels down so the hierarchy lookup (file dir, ./hierarchies,
    # ../hierarchies) never leaves that dir.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "inline" / "inline.yaml"
        path.parent.mkdir()
        path.write_text(request.yaml_content, encoding="utf-8")
        try:
            by_kind = compile_file_by_kind(path, Compiler(), templates)
        except CompilationError as exc:
            cause = exc.__cause__
            if isinstance(cause, PydanticValidationError):
                # Surface the triggering message(s) but drop input values / URLs.
                return CompileResponse(
                    clips="",
                    errors=[
                        f"{'.'.join(str(p) for p in err.get('loc', ())) or 'body'}: "
                        f"{err.get('msg', 'invalid value')}"
                        for err in cause.errors()
                    ],
                )
            # Return the construct + message but not the raw detail; the temp
            # path is server-side detail too.
            message = str(exc).split("\n", 1)[0].replace(str(path), "yaml_content")
            return CompileResponse(clips="", errors=[message])
        except Exception:
            logger.warning("compile: internal compilation error", exc_info=True)
            return CompileResponse(clips="", errors=["internal compilation error"])

    constructs = [c for kind in _COMPILE_KINDS for c in by_kind.get(kind, [])]
    if not constructs:
        return CompileResponse(clips="", errors=["no compilable constructs found"])
    return CompileResponse(clips="\n".join(constructs), errors=[])


@router.post(
    "/v1/facts",
    response_model=AssertFactResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def assert_fact(request: AssertFactRequest, http_request: Request) -> AssertFactResponse:
    """Assert a single fact into a session's working memory.

    Unlike ``/v1/evaluate``, this endpoint does **not** create sessions on
    the fly — the ``session_id`` must reference a session previously
    created via ``/v1/evaluate``. Unknown session ids return 404.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(http_request.app.state, request.session_id)
    engine.assert_fact(request.template, request.data)
    return AssertFactResponse(success=True)


@router.post(
    "/v1/query",
    response_model=QueryFactsResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def query_facts(request: QueryFactsRequest, http_request: Request) -> QueryFactsResponse:
    """Query a session's working memory for facts matching template + filter.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(http_request.app.state, request.session_id)
    facts = engine.query(request.template, request.filter)
    return QueryFactsResponse(facts=facts)


@router.delete(
    "/v1/facts",
    response_model=RetractFactsResponse,
    responses=_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def retract_facts(request: RetractFactsRequest, http_request: Request) -> RetractFactsResponse:
    """Retract facts matching template + optional filter from working memory.

    The ``session_id`` must reference an existing session created via
    ``/v1/evaluate``. Unknown session ids return 404. Retract is by
    template + filter (matches the gRPC surface), not by fact index.

    Declared ``def`` so the blocking CLIPS call runs in the threadpool.
    """
    engine = _require_session_engine(http_request.app.state, request.session_id)
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


class RulesetReloadResponse(BaseModel):
    """Response body for a successful ``POST /v1/rules/reload``."""

    ruleset_hash_before: str
    ruleset_hash_after: str
    attestation_token: str


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


@router.post(
    "/v1/rules/reload",
    dependencies=[Depends(_require_admin_auth)],
    responses={
        200: {"model": RulesetReloadResponse, "description": "Ruleset reloaded"},
        **_ERROR_RESPONSES,
        500: {"model": ErrorResponse, "description": "Server misconfigured"},
    },
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

    def _rejected(status: int, error: str, detail: str, reason: str) -> JSONResponse:
        """Every way a reload can be refused is an audited event.

        Only the two signature rejections wrote to the sink, so an operator
        reading the audit trail saw nothing for a compile failure -- the
        reason the how-to names -- or for an unreadable path, a malformed
        signature, or a request that named both sources. A reload attempt
        that leaves no trace is the one an attacker wants.
        """
        _write_audit(
            audit_sink,
            {
                "event_type": "ruleset_reload_rejected",
                "reason": reason,
                "ruleset_hash_before": engine.ruleset_hash if engine is not None else None,
                "timestamp": _now_iso(),
                "actor": "bearer-token",
            },
        )
        return _make_error_response(status, error, detail)

    # --- exactly-one-of ruleset_path / ruleset_yaml ---
    has_path = payload.ruleset_path is not None
    has_yaml = payload.ruleset_yaml is not None
    if has_path == has_yaml:
        return _rejected(
            400,
            "invalid_request",
            "exactly one of ruleset_path or ruleset_yaml must be provided",
            "invalid_request",
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
        except OSError:
            # The OSError text carries the resolved server-side absolute path
            # ("[Errno 2] No such file or directory: '/srv/rules/x.yaml'"),
            # which must never reach a remote caller -- the same rule the
            # ruleset path jail follows. Log it, answer with a fixed string.
            logger.warning("reload: unable to read ruleset_path", exc_info=True)
            return _rejected(
                400,
                "invalid_request",
                "unable to read ruleset_path",
                "unreadable_ruleset_path",
            )

    # --- decode signature (base64 string → bytes) ---
    sig_bytes: bytes | None = None
    if payload.signature is not None:
        try:
            sig_bytes = base64.b64decode(payload.signature, validate=True)
        except (binascii.Error, ValueError):
            return _rejected(
                400,
                "invalid_request",
                "signature must be valid base64",
                "malformed_signature",
            )

    # --- signature verification (fail-closed when required) ---
    hash_before = engine.ruleset_hash
    if require_signature:
        if pubkey is None:
            # Should have failed at build_app; defensive 500.
            return _rejected(
                500,
                "server_misconfigured",
                "require_signature=true but ruleset pubkey is not loaded",
                "server_misconfigured",
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
    except CompilationError:
        # Compiler diagnostics are written for a library caller and name the
        # files they were reading ("cannot read file /srv/rules/agents.yaml"),
        # so they are server-side detail. Callers who want the diagnostic run
        # the ruleset through POST /v1/compile, which compiles inline YAML and
        # touches no server paths.
        logger.warning("reload: ruleset failed to compile", exc_info=True)
        return _rejected(
            400,
            "invalid_ruleset",
            "ruleset failed to compile",
            "compile_failed",
        )

    # Sessions hold their own Engine, compiled when the session opened, so
    # they would keep deciding on the pre-reload ruleset for as long as they
    # stayed alive — an admin tightening policy would not reach them. Drop
    # them: a reload already discards working memory by design (see
    # docs/how-to/hot-reload.md), so surviving with stale *policy* is the
    # worse of the two.
    state.session_store.clear()

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


@router.get("/v1/status")
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


# ---------------------------------------------------------------------------
# OPA-compatible Data API
# ---------------------------------------------------------------------------
#
# `POST /v1/data/<path>` is OPA's decision endpoint, and an existing OPA
# client -- a sidecar caller, a Kubernetes admission webhook, an SDK -- speaks
# it already. Serving it here means a policy converted with
# `fathom convert rego` can be pointed at Fathom without touching the callers.
#
# The mapping mirrors OPA's own: `data.<package>.<rule>` addresses a document,
# so leading segments name the ruleset directory and the last segment names
# the document. A `<rule>` of `allow` or `deny` answers with the bare boolean
# OPA would return; anything else is read as a package and answers with the
# whole decision object.
#
# Deliberately NOT OPA-compatible: this surface requires the same bearer token
# as every other route. OPA's data API is unauthenticated by default; adopting
# that here would put an authentication hole next to the endpoints that do not
# have one.

#: Documents that answer with a bare boolean. A ruleset directory named
#: `allow` or `deny` is shadowed by this and has to be addressed as a package
#: -- an acceptable trade for matching OPA's addressing, and the reason the
#: names are listed here rather than sniffed.
_OPA_DECISION_DOCUMENTS = ("allow", "deny")

#: Template the OPA `input` document is asserted as. Matches the default
#: `fathom convert rego` emits, so a converted policy works unconfigured.
_OPA_DEFAULT_TEMPLATE = "input"


class OPADataRequest(BaseModel):
    """OPA's Data API request body: `{"input": {...}}`."""

    input: dict[str, Any] = Field(default_factory=dict)


class OPAErrorResponse(BaseModel):
    """OPA's error envelope. Declared so the OpenAPI document says so."""

    code: str
    message: str


#: Errors these two routes can produce, in OPA's envelope rather than
#: Fathom's. 401, 413 and 422 are the exceptions: they come from the shared
#: auth dependency, body-size middleware and body validation, which answer in
#: Fathom's shape.
_OPA_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": OPAErrorResponse, "description": "Invalid request"},
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    413: {"model": ErrorResponse, "description": "Request body too large"},
    422: {"model": ErrorResponse, "description": "Request body failed validation"},
    500: {"model": OPAErrorResponse, "description": "Evaluation failed"},
}


def _opa_error(status: int, code: str, message: str) -> JSONResponse:
    """OPA's error envelope, which is not Fathom's.

    A client written against OPA parses `code`/`message`. Returning Fathom's
    `{"error": ..., "detail": ...}` here would mean the endpoint speaks OPA on
    the happy path and something else the moment anything goes wrong, which is
    the half-compatibility that costs more than no compatibility.
    """
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _opa_facts(engine: Engine, template: str, document: dict[str, Any]) -> dict[str, Any]:
    """Build the fact for *document*, keeping only slots the template declares.

    OPA's `input` is an arbitrary document and a Fathom template is a fixed
    set of typed slots. Fields no slot declares are dropped rather than
    asserted: no rule can match on them, so passing them through would fail
    the assert on a field nothing reads.
    """
    definition = engine.template_registry[template]
    declared = {slot.name for slot in definition.slots}
    return {k: v for k, v in flatten_input(document).items() if k in declared}


def _opa_undefined(engine: Engine, document_name: str) -> JSONResponse:
    """The answer for a document no rule can be evaluated against.

    Shaped exactly like the happy path so an OPA client cannot tell the two
    apart -- which is the point: OPA answers `false` for an undefined `allow`,
    not an error.
    """
    decision = engine.default_decision
    if document_name:
        return JSONResponse(content={"result": decision == document_name})
    return JSONResponse(
        content={
            "result": {
                "allow": decision == "allow",
                "deny": decision == "deny",
                "decision": decision,
                "reason": None,
                "rule_trace": [],
            }
        }
    )


def _opa_evaluate(
    state: State, path: str, document: dict[str, Any], template: str
) -> JSONResponse:
    """Shared body of the GET and POST forms of the Data API."""
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return _opa_error(
            400,
            "invalid_parameter",
            "the whole data document is not addressable; name a ruleset, "
            "as in /v1/data/<ruleset>/allow",
        )

    document_name = segments[-1]
    if document_name in _OPA_DECISION_DOCUMENTS:
        ruleset_path = "/".join(segments[:-1])
    else:
        document_name = ""
        ruleset_path = "/".join(segments)

    try:
        resolved = _resolve_user_ruleset(ruleset_path)
    except HTTPException as exc:
        return _opa_error(exc.status_code, "invalid_parameter", str(exc.detail))

    attestation = getattr(state, "attestation", None)
    try:
        engine = _data_plane_engine(state, resolved, attestation)
    except HTTPException as exc:
        # The loader's own text names the resolved server-side absolute path
        # ("/srv/rules/x is not a directory"), which must never reach a remote
        # caller — the same rule the ruleset path jail follows. Echo back only
        # the path the caller sent.
        return _opa_error(
            exc.status_code, "invalid_parameter", f"ruleset {ruleset_path!r} could not be loaded"
        )

    if template not in engine.template_registry:
        return _opa_error(
            400,
            "invalid_parameter",
            f"template {template!r} is not declared by this ruleset; "
            f"pass ?template= naming one of {sorted(engine.template_registry)}",
        )

    try:
        result = engine.evaluate_once(facts=[(template, _opa_facts(engine, template, document))])
    except FathomValidationError:
        # The document does not fit the templates -- a missing required slot,
        # a value of the wrong type. In Rego that is not an error: the
        # reference is undefined, the rule body fails, and the policy falls to
        # its default. Answer the same way rather than reporting a caller's
        # partial document as a server fault (it used to be a 500, which is
        # what orchestrators and circuit-breakers read as "the policy engine
        # is broken"). The engine's default decision is fail-closed.
        logger.debug("opa data: document does not fit template %r", template, exc_info=True)
        return _opa_undefined(engine, document_name)
    except EvaluationError as exc:
        return _opa_error(500, "internal_error", str(exc))

    if document_name:
        # Always defined, never OPA's `{}` undefined response: a Fathom engine
        # has a default decision (`deny`), so some decision always comes back.
        # That is the same shape a Rego policy with `default allow := false`
        # produces, which is what `fathom convert rego` tells you to write.
        return JSONResponse(content={"result": result.decision == document_name})

    return JSONResponse(
        content={
            "result": {
                "allow": result.decision == "allow",
                "deny": result.decision == "deny",
                "decision": result.decision,
                "reason": result.reason,
                "rule_trace": result.rule_trace,
            }
        }
    )


@router.post(
    "/v1/data/{path:path}",
    responses=_OPA_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def opa_data(
    path: str,
    request: OPADataRequest,
    http_request: Request,
    template: str = _OPA_DEFAULT_TEMPLATE,
) -> JSONResponse:
    """Evaluate a ruleset through OPA's Data API.

    `POST /v1/data/authz/basic/allow` with `{"input": {...}}` answers
    `{"result": true}`; drop the trailing `allow`/`deny` to get the whole
    decision object instead.

    Declared ``def`` for the same reason as ``/v1/evaluate``: CLIPS evaluation
    is blocking CPU work and belongs in the threadpool, not on the event loop.
    """
    return _opa_evaluate(http_request.app.state, path, request.input, template)


@router.get(
    "/v1/data/{path:path}",
    responses=_OPA_ERROR_RESPONSES,
    dependencies=[Depends(_require_auth)],
)
def opa_data_get(
    path: str,
    request: Request,
    # Named `input` on the wire because that is what OPA's Data API calls it;
    # the Python name differs only to avoid shadowing the builtin.
    input_json: str | None = Query(default=None, alias="input"),
    template: str = _OPA_DEFAULT_TEMPLATE,
) -> JSONResponse:
    """The GET form of the Data API, with `input` as a JSON query parameter.

    OPA supports it and shell-based checks use it. Note that query strings are
    logged by intermediaries, so anything sensitive belongs in the POST body.
    """
    if input_json is None:
        document: dict[str, Any] = {}
    else:
        try:
            document = json.loads(input_json)
        except json.JSONDecodeError as exc:
            return _opa_error(400, "invalid_parameter", f"input is not valid JSON: {exc}")
        if not isinstance(document, dict):
            return _opa_error(400, "invalid_parameter", "input must be a JSON object")
    return _opa_evaluate(request.app.state, path, document, template)


def _new_app() -> FastAPI:
    """Build a FastAPI app serving the API, with its own state and sessions."""
    new = FastAPI(
        title="Fathom Rules Engine",
        version=_fathom_version,
        description="Deterministic reasoning runtime for AI agents",
        docs_url="/docs" if _expose_docs else None,
        redoc_url="/redoc" if _expose_docs else None,
        openapi_url="/openapi.json" if _expose_docs else None,
        exception_handlers={
            StarletteHTTPException: http_exception_handler,
            RequestValidationError: request_validation_error_handler,
            FathomValidationError: fathom_validation_error_handler,
            Exception: unhandled_exception_handler,
        },
    )
    new.add_middleware(BodySizeLimitMiddleware)
    if _metrics_enabled:
        # Instrument without exposing a public /metrics; register an
        # auth-gated endpoint instead.
        Instrumentator().instrument(new)
        new.add_api_route("/metrics", metrics, dependencies=[Depends(_require_auth)])
    new.include_router(router)
    new.state.engine = None
    new.state.attestation = None
    new.state.audit_sink = None
    new.state.session_store = SessionStore()
    return new


#: The app ``uvicorn fathom.integrations.rest:app`` (and the Docker image)
#: serves. ``build_app`` returns a separate app on every call.
app = _new_app()


_RULESET_PUBKEY_ERROR = (
    "ruleset pubkey unreadable or missing; set FATHOM_RULESET_PUBKEY_PATH or enable dev escape"
)


def build_app(*, require_signature: bool = True) -> FastAPI:
    """Return a new REST app with ruleset pubkey bootstrapped onto ``app.state``.

    Each call builds an independent app -- its own ``state``, Engine slot and
    session store -- so two apps in one process never share policy or sessions.
    The module-level ``app`` is a different instance again.

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

    # Default state slots (engine, attestation, audit sink) are seeded by
    # _new_app(); callers inject real instances after build_app() returns.
    app = _new_app()
    # Both halves or neither. Assigning the flag verbatim here made
    # `require_signature=False` alone switch verification off, while the env
    # var below decided only whether a pubkey was loaded -- so a single stray
    # flag lowered the floor the docs promise takes two.
    dev_escape = not require_signature and allow_unsigned
    app.state.require_signature = not dev_escape
    app.state.last_reload_iso = None
    app.state.boot_time_iso = _now_iso()

    if not require_signature and not allow_unsigned:
        logger.warning(
            "require_signature=false has no effect without "
            "FATHOM_ALLOW_UNSIGNED_RULESETS=1; ruleset signature verification "
            "stays ON (the dev escape requires both)"
        )

    if dev_escape:
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
