"""gRPC server for Fathom rule evaluation.

Provides :class:`FathomServicer` implementing the ``FathomService`` proto
defined in ``protos/fathom.proto``.  Each RPC delegates to
:class:`~fathom.engine.Engine` for fact management and evaluation.

Requires ``grpcio >= 1.60``.  Install via::

    pip install fathom-rules[grpc]
"""

from __future__ import annotations

import json
import logging
import os
from concurrent import futures
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

try:
    import grpc
except ImportError as _exc:
    raise ImportError(
        "grpcio is required for the gRPC integration. "
        "Install it with: pip install fathom-rules[grpc]"
    ) from _exc

from fathom.errors import CompilationError
from fathom.integrations.auth import verify_token
from fathom.integrations.paths import PathJailError, resolve_ruleset
from fathom.proto import fathom_pb2, fathom_pb2_grpc

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fathom.attestation import AttestationService
    from fathom.engine import Engine

logger = logging.getLogger(__name__)


class SessionStore:
    """Minimal session store for gRPC — same pattern as the REST server."""

    def __init__(self) -> None:
        self._sessions: dict[str, Engine] = {}

    def get_or_create(self, session_id: str, rules_path: str = "") -> Engine:
        """Return an existing session or create a new one.

        Args:
            session_id: Unique session identifier.
            rules_path: Path to rules directory for new sessions.

        Returns:
            Configured Engine instance.
        """
        from fathom.engine import Engine

        if session_id in self._sessions:
            return self._sessions[session_id]

        engine = Engine.from_rules(rules_path) if rules_path else Engine()
        self._sessions[session_id] = engine
        return engine


class FathomServicer(fathom_pb2_grpc.FathomServiceServicer):
    """gRPC servicer delegating RPCs to :class:`~fathom.engine.Engine`.

    Each method receives a protobuf request, extracts parameters, calls
    the appropriate Engine method, and returns a protobuf response.

    ``Reload`` returns a real :class:`fathom_pb2.ReloadResponse` so it can
    be registered on a ``grpc.server`` and called via a generated stub.
    The other RPCs still return plain ``dict`` payloads as structural
    stubs — they are not exercised via the real gRPC channel yet.

    Args:
        default_engine: Engine instance used for session-less requests.
        attestation: Optional attestation service used by :meth:`Reload`
            to sign ``ruleset_reloaded`` audit events. Required when
            ``Reload`` is invoked; absent at construction is tolerated so
            existing read-only RPCs remain callable without it.
        audit_sink: Optional duck-typed sink with a ``write(record)``
            method; receives ``ruleset_reloaded`` / ``ruleset_reload_rejected``
            dicts. Failures are logged and swallowed (matches REST).
        ruleset_pubkey: Optional PEM-encoded Ed25519 public key used to
            verify detached ruleset signatures during :meth:`Reload`.
        require_signature: Fail-closed flag — when True, :meth:`Reload`
            rejects unsigned or badly-signed payloads with
            ``INVALID_ARGUMENT`` and "unsigned_ruleset".
    """

    def __init__(
        self,
        default_engine: Engine | None = None,
        attestation: AttestationService | None = None,
        audit_sink: Any | None = None,
        ruleset_pubkey: bytes | None = None,
        require_signature: bool = True,
    ) -> None:
        from fathom.engine import Engine

        self._default_engine = default_engine or Engine()
        self._session_store = SessionStore()
        self._attestation = attestation
        self._audit_sink = audit_sink
        self._ruleset_pubkey = ruleset_pubkey
        self._require_signature = require_signature

    def _engine_for(self, session_id: str, ruleset: str = "") -> Engine:
        """Resolve engine: session-scoped or default."""
        if session_id:
            return self._session_store.get_or_create(session_id, ruleset)
        return self._default_engine

    def _check_auth(self, context: Any) -> None:
        """Abort the RPC if the caller did not present a valid bearer token."""
        md = dict(context.invocation_metadata())
        header = md.get("authorization")
        if not verify_token(header):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "unauthorized")

    def _resolve_ruleset(self, user_path: str, context: Any) -> str:
        """Return a jailed absolute path, or abort the RPC."""
        if not user_path:
            return ""
        root = os.environ.get("FATHOM_RULESET_ROOT", "")
        if not root:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "FATHOM_RULESET_ROOT not configured",
            )
        try:
            return str(resolve_ruleset(root, user_path))
        except PathJailError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            raise  # unreachable; abort raises

    # --- RPC implementations ---

    def Evaluate(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> dict[str, Any]:
        """Evaluate facts against loaded rules.

        Asserts each fact from the request into working memory, runs
        the evaluation, and returns the decision with traces.
        """
        self._check_auth(context)
        ruleset = self._resolve_ruleset(
            getattr(request, "ruleset", ""),
            context,
        )
        engine = self._engine_for(request.session_id, ruleset)

        for fact in request.facts:
            data: dict[str, Any] = json.loads(fact.data_json)
            engine.assert_fact(fact.template, data)

        result = engine.evaluate()

        return {
            "decision": result.decision or "",
            "reason": result.reason or "",
            "rule_trace": list(result.rule_trace),
            "module_trace": list(result.module_trace),
            "duration_us": result.duration_us,
        }

    def AssertFact(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> dict[str, Any]:
        """Assert a single fact into working memory."""
        self._check_auth(context)
        engine = self._engine_for(request.session_id)
        data = json.loads(request.data_json)
        engine.assert_fact(request.template, data)
        return {"success": True}

    def Query(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> dict[str, Any]:
        """Query working memory for matching facts."""
        self._check_auth(context)
        engine = self._engine_for(request.session_id)

        fact_filter: dict[str, Any] | None = None
        if request.filter_json:
            fact_filter = json.loads(request.filter_json)

        facts = engine.query(request.template, fact_filter)
        return {"facts_json": [json.dumps(f) for f in facts]}

    def Retract(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> dict[str, Any]:
        """Retract facts matching template and optional filter."""
        self._check_auth(context)
        engine = self._engine_for(request.session_id)

        fact_filter: dict[str, Any] | None = None
        if request.filter_json:
            fact_filter = json.loads(request.filter_json)

        count = engine.retract(request.template, fact_filter)
        return {"retracted_count": count}

    def SubscribeChanges(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> Iterator[dict[str, Any]]:
        """Stream working-memory changes (stub).

        Full implementation requires an event bus wired into the Engine's
        fact assertion and retraction paths.  This stub yields nothing
        and returns immediately.
        """
        self._check_auth(context)
        return iter([])

    def _write_audit(self, record: dict[str, Any]) -> None:
        """Forward ``record`` to the audit sink; swallow sink errors.

        Mirrors the REST implementation — audit writes are fire-and-forget
        so a wedged sink never blocks a reload. Sink is duck-typed: any
        object exposing ``write(record)``.
        """
        if self._audit_sink is None:
            return
        try:
            self._audit_sink.write(record)
        except Exception:  # pragma: no cover - audit failure must not crash reload
            logger.exception("audit sink write failed")

    def Reload(  # noqa: N802 — gRPC convention
        self,
        request: Any,
        context: Any,
    ) -> fathom_pb2.ReloadResponse:
        """Atomically swap the loaded ruleset with a new (optionally signed) one.

        gRPC parity with ``POST /v1/rules/reload`` (design C5 / D3). Error
        mapping:

        * Exactly-one-of violation → ``INVALID_ARGUMENT`` "invalid_request"
        * Unreadable ``ruleset_path`` → ``INVALID_ARGUMENT`` "invalid_request"
        * Missing signature (fail-closed) → ``INVALID_ARGUMENT`` "unsigned_ruleset"
        * Bad signature → ``INVALID_ARGUMENT`` "unsigned_ruleset"
        * Compile error → ``FAILED_PRECONDITION`` with message
        * Not-ready (no engine/attestation) → ``FAILED_PRECONDITION`` "not_ready"
        """
        self._check_auth(context)

        engine = self._default_engine
        attestation = self._attestation
        if engine is None or attestation is None:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "not_ready: engine or attestation not configured",
            )
        assert engine is not None  # noqa: S101 - narrowed by abort above
        assert attestation is not None  # noqa: S101 - narrowed by abort above

        # --- exactly-one-of ruleset_path / ruleset_yaml ---
        # Proto oneof auto-enforces one-or-none; WhichOneof returns None
        # when neither field was set by the caller.
        which = request.WhichOneof("source") if hasattr(request, "WhichOneof") else None
        if which is None:
            # Fall back to structural inspection for non-proto test doubles.
            has_path = bool(getattr(request, "ruleset_path", ""))
            has_yaml = bool(getattr(request, "ruleset_yaml", ""))
            if has_path == has_yaml:
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "invalid_request: exactly one of ruleset_path or "
                    "ruleset_yaml must be provided",
                )
            which = "ruleset_path" if has_path else "ruleset_yaml"

        # --- materialise raw YAML bytes ---
        if which == "ruleset_yaml":
            raw_yaml_bytes = request.ruleset_yaml.encode("utf-8")
        else:
            resolved = self._resolve_ruleset(request.ruleset_path, context)
            try:
                with open(resolved, "rb") as f:
                    raw_yaml_bytes = f.read()
            except OSError as exc:
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"invalid_request: unable to read ruleset_path: {exc}",
                )

        sig_bytes: bytes | None = request.signature or None
        hash_before = engine.ruleset_hash
        actor = "grpc-anon"
        timestamp = datetime.now(UTC).isoformat()

        # --- signature verification (fail-closed when required) ---
        if self._require_signature:
            if self._ruleset_pubkey is None:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "server_misconfigured: require_signature=true but "
                    "ruleset pubkey is not loaded",
                )
            assert self._ruleset_pubkey is not None  # noqa: S101 - narrowed
            if sig_bytes is None:
                self._write_audit(
                    {
                        "event_type": "ruleset_reload_rejected",
                        "reason": "missing_signature",
                        "ruleset_hash_before": hash_before,
                        "timestamp": timestamp,
                        "actor": actor,
                    },
                )
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "unsigned_ruleset: signature is required but was not provided",
                )
            assert sig_bytes is not None  # noqa: S101 - narrowed by abort above
            try:
                from fathom.integrations.ruleset_sig import (
                    RulesetSignatureError,
                    verify_ruleset_signature,
                )

                verify_ruleset_signature(
                    raw_yaml_bytes,
                    sig_bytes,
                    self._ruleset_pubkey,
                )
            except RulesetSignatureError as exc:
                self._write_audit(
                    {
                        "event_type": "ruleset_reload_rejected",
                        "reason": str(exc),
                        "ruleset_hash_before": hash_before,
                        "timestamp": timestamp,
                        "actor": actor,
                    },
                )
                context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "unsigned_ruleset: ruleset signature verification failed",
                )

        # --- happy path: atomic-swap reload ---
        try:
            hash_before, hash_after = engine.reload_rules(
                raw_yaml_bytes,
                sig_bytes if self._require_signature else None,
                self._ruleset_pubkey if self._require_signature else None,
            )
        except CompilationError as exc:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"invalid_ruleset: {str(exc).split(chr(10), 1)[0]}",
            )

        timestamp = datetime.now(UTC).isoformat()
        attestation_token = attestation.sign_event(
            {
                "ruleset_hash_before": hash_before,
                "ruleset_hash_after": hash_after,
                "actor": actor,
                "timestamp": timestamp,
            }
        )

        self._write_audit(
            {
                "event_type": "ruleset_reloaded",
                "ruleset_hash_before": hash_before,
                "ruleset_hash_after": hash_after,
                "actor": actor,
                "timestamp": timestamp,
            },
        )

        return fathom_pb2.ReloadResponse(
            ruleset_hash_before=hash_before,
            ruleset_hash_after=hash_after,
            attestation_token=attestation_token,
        )


def serve(
    engine: Engine | None = None,
    port: int = 50051,
    max_workers: int = 10,
) -> grpc.Server:
    """Start the Fathom gRPC server.

    TLS is required by default. Set ``FATHOM_GRPC_TLS_CERT`` and
    ``FATHOM_GRPC_TLS_KEY`` to PEM file paths to bind a secure port.
    Set ``FATHOM_GRPC_ALLOW_INSECURE=1`` to fall back to an insecure port
    (explicit opt-in only — the bearer token is transmitted in the clear
    without TLS and is trivially captured by passive network observers).

    Args:
        engine: Optional pre-configured Engine. A default Engine is
            created when omitted.
        port: TCP port to listen on. Defaults to ``50051``.
        max_workers: Thread pool size. Defaults to ``10``.

    Returns:
        The running :class:`grpc.Server` instance.
    """
    server: grpc.Server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
    )
    servicer = FathomServicer(default_engine=engine)
    fathom_pb2_grpc.add_FathomServiceServicer_to_server(servicer, server)  # type: ignore[no-untyped-call]

    cert_path = os.environ.get("FATHOM_GRPC_TLS_CERT", "")
    key_path = os.environ.get("FATHOM_GRPC_TLS_KEY", "")
    allow_insecure = os.environ.get("FATHOM_GRPC_ALLOW_INSECURE") == "1"

    if cert_path and key_path:
        with open(cert_path, "rb") as cf, open(key_path, "rb") as kf:
            credentials = grpc.ssl_server_credentials([(kf.read(), cf.read())])
        server.add_secure_port(f"[::]:{port}", credentials)
    elif allow_insecure:
        server.add_insecure_port(f"[::]:{port}")
    else:
        raise RuntimeError(
            "gRPC server requires TLS. Set FATHOM_GRPC_TLS_CERT and "
            "FATHOM_GRPC_TLS_KEY to PEM paths, or explicitly opt in to "
            "insecure mode with FATHOM_GRPC_ALLOW_INSECURE=1."
        )
    server.start()
    return server
