"""gRPC session bounds and ruleset binding.

The gRPC store used to be an unbounded insert-only dict with no TTL and no
ceiling; it now shares :class:`fathom.integrations.sessions.SessionStore`
with REST, so both surfaces enforce the same bounds.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest

from fathom.integrations.grpc_server import FathomServicer
from fathom.integrations.sessions import SessionStore

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "01-hello-allow-deny"

_ALLOW_EVERYTHING = """
module: governance
ruleset: loose
version: "1.0"

rules:
  - name: allow-everything
    salience: 1
    when:
      - template: agent
        conditions:
          - slot: id
            expression: "matches(.+)"
    then:
      action: allow
      reason: "LOOSE-POLICY-FIRED"
"""


class _FakeContext:
    """Minimal ServicerContext double: ``abort`` records and raises."""

    def __init__(self) -> None:
        self.metadata: tuple[tuple[str, str], ...] = (("authorization", "Bearer testtok"),)
        self.aborted: tuple[object, str] | None = None

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self.metadata

    def abort(self, code: object, detail: str) -> None:
        self.aborted = (code, detail)
        raise RuntimeError(f"aborted: {detail}")


@pytest.fixture
def ruleset_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A jail root holding a `strict` ruleset and a `loose` superset of it."""
    strict = tmp_path / "strict"
    shutil.copytree(EXAMPLE_DIR / "modules", strict / "modules")
    shutil.copytree(EXAMPLE_DIR / "templates", strict / "templates")
    shutil.copytree(EXAMPLE_DIR / "rules", strict / "rules")

    loose = tmp_path / "loose"
    shutil.copytree(strict, loose)
    (loose / "rules" / "loose.yaml").write_text(_ALLOW_EVERYTHING)

    monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
    monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
    return tmp_path


def _evaluate(svc: FathomServicer, ctx: _FakeContext, ruleset: str, session_id: str) -> object:
    return svc.Evaluate(
        SimpleNamespace(session_id=session_id, ruleset=ruleset, facts=[]),
        ctx,
    )


class TestGrpcSessionBounds:
    def test_store_is_bounded(self, ruleset_root: Path) -> None:
        """The gRPC store carries the same TTL and ceiling as REST."""
        svc = FathomServicer()
        store = svc._session_store
        assert isinstance(store, SessionStore)
        assert store._ttl_seconds == 1800
        assert store._max_sessions == 1000

    def test_ceiling_aborts_resource_exhausted(self, ruleset_root: Path) -> None:
        svc = FathomServicer()
        svc._session_store = SessionStore(max_sessions=1)
        ctx = _FakeContext()
        _evaluate(svc, ctx, "strict", "s1")

        with pytest.raises(RuntimeError, match="aborted"):
            _evaluate(svc, ctx, "strict", "s2")
        assert ctx.aborted is not None
        assert ctx.aborted[0] is grpc.StatusCode.RESOURCE_EXHAUSTED

    def test_expired_sessions_are_reclaimed(self, ruleset_root: Path) -> None:
        svc = FathomServicer()
        svc._session_store = SessionStore(ttl_seconds=0)
        ctx = _FakeContext()
        _evaluate(svc, ctx, "strict", "s1")
        _evaluate(svc, ctx, "strict", "s2")
        assert len(svc._session_store) == 1


class TestGrpcSessionRulesetBinding:
    def test_mismatched_ruleset_aborts_failed_precondition(self, ruleset_root: Path) -> None:
        svc = FathomServicer()
        ctx = _FakeContext()
        _evaluate(svc, ctx, "loose", "S")

        with pytest.raises(RuntimeError, match="aborted"):
            _evaluate(svc, ctx, "strict", "S")
        assert ctx.aborted is not None
        assert ctx.aborted[0] is grpc.StatusCode.FAILED_PRECONDITION

    def test_ruleset_less_rpc_joins_the_existing_session(self, ruleset_root: Path) -> None:
        """AssertFact/Query/Retract carry no ruleset — they must not mismatch."""
        svc = FathomServicer()
        ctx = _FakeContext()
        _evaluate(svc, ctx, "strict", "S")

        svc.AssertFact(
            SimpleNamespace(
                session_id="S",
                template="agent",
                data_json='{"id": "a1", "clearance": "secret"}',
            ),
            ctx,
        )
        result = svc.Query(
            SimpleNamespace(session_id="S", template="agent", filter_json=""),
            ctx,
        )
        assert ctx.aborted is None
        assert len(result.facts_json) == 1

    def test_same_ruleset_reuses_the_session(self, ruleset_root: Path) -> None:
        svc = FathomServicer()
        ctx = _FakeContext()
        _evaluate(svc, ctx, "strict", "S")
        _evaluate(svc, ctx, "strict", "S")
        assert len(svc._session_store) == 1


class TestRulesetLessRpcCannotPoisonASessionId:
    """A ruleset-less RPC must not CREATE a session bound to the empty ruleset.

    `_engine_for` used to fall through to ``get_or_create(session_id, "")``
    when a ruleset-less RPC named an unknown session. That bound the id to
    ``""`` for the full session TTL, so every later ``Evaluate`` naming a
    real ruleset aborted ``FAILED_PRECONDITION`` — one authenticated client
    could wedge arbitrary session ids chosen by other clients. REST never had
    this: its ruleset-less routes 404 on an unknown session.
    """

    def test_unknown_session_on_a_ruleset_less_rpc_is_not_found(self, ruleset_root: Path) -> None:
        svc = FathomServicer()
        ctx = _FakeContext()

        with pytest.raises(RuntimeError, match="aborted"):
            svc.AssertFact(
                SimpleNamespace(
                    session_id="never-created",
                    template="agent",
                    data_json='{"id": "a1", "clearance": "secret"}',
                ),
                ctx,
            )
        assert ctx.aborted is not None
        assert ctx.aborted[0] is grpc.StatusCode.NOT_FOUND
        assert len(svc._session_store) == 0

    def test_a_poisoned_id_stays_usable_for_evaluate(self, ruleset_root: Path) -> None:
        """After the failed ruleset-less call, Evaluate on that id still works."""
        svc = FathomServicer()
        ctx = _FakeContext()

        with pytest.raises(RuntimeError, match="aborted"):
            svc.Query(
                SimpleNamespace(session_id="X", template="agent", filter_json=""),
                ctx,
            )

        ctx2 = _FakeContext()
        _evaluate(svc, ctx2, "strict", "X")
        assert ctx2.aborted is None
        assert len(svc._session_store) == 1


class TestGrpcSessionsOnAMountedServer:
    """A servicer constructed with an engine serves *that* policy, or nothing.

    The REST rule, on the sibling transport: a session compiled the caller's
    own ``ruleset`` off disk, so one extra request field chose which policy
    decided -- and `Reload` on the constructed engine never reached that
    traffic. Refused here the way REST refuses it with 400.
    """

    def test_a_session_is_refused_when_the_servicer_carries_an_engine(
        self, ruleset_root: Path
    ) -> None:
        from fathom.engine import Engine

        svc = FathomServicer(default_engine=Engine.from_rules(str(ruleset_root / "strict")))
        ctx = _FakeContext()

        with pytest.raises(RuntimeError, match="aborted"):
            _evaluate(svc, ctx, "loose", "s1")

        assert ctx.aborted is not None
        assert ctx.aborted[0] is grpc.StatusCode.FAILED_PRECONDITION
        assert "sessions_unavailable" in ctx.aborted[1]
        assert len(svc._session_store) == 0

    def test_a_stateless_call_still_runs_the_mounted_policy(self, ruleset_root: Path) -> None:
        """Refusing sessions must not touch the stateless path."""
        from fathom.engine import Engine

        svc = FathomServicer(default_engine=Engine.from_rules(str(ruleset_root / "strict")))
        ctx = _FakeContext()

        response = _evaluate(svc, ctx, "loose", "")

        assert ctx.aborted is None
        assert response.decision
        assert "LOOSE-POLICY-FIRED" not in response.reason

    def test_sessions_still_work_without_a_mounted_engine(self, ruleset_root: Path) -> None:
        """The multi-ruleset deployment is the one sessions are for."""
        svc = FathomServicer()
        ctx = _FakeContext()

        _evaluate(svc, ctx, "loose", "s1")

        assert ctx.aborted is None
        assert len(svc._session_store) == 1
