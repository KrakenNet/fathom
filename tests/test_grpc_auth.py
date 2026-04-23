"""Tests for gRPC auth + path jailing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from fathom.integrations.grpc_server import FathomServicer

if TYPE_CHECKING:
    from pathlib import Path


class _FakeContext:
    def __init__(self) -> None:
        self.metadata: tuple[tuple[str, str], ...] = ()
        self.aborted: tuple[object, str] | None = None

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self.metadata

    def abort(self, code: object, detail: str) -> None:
        self.aborted = (code, detail)
        raise RuntimeError(f"aborted: {detail}")


class TestGrpcAuth:
    def test_rejects_missing_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        req = SimpleNamespace(session_id="", ruleset="", facts=[])
        with pytest.raises(RuntimeError, match="aborted"):
            svc.Evaluate(req, ctx)
        assert ctx.aborted is not None

    def test_rejects_wrong_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        ctx.metadata = (("authorization", "Bearer wrong"),)
        req = SimpleNamespace(session_id="", ruleset="", facts=[])
        with pytest.raises(RuntimeError, match="aborted"):
            svc.Evaluate(req, ctx)

    def test_accepts_valid_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        ctx.metadata = (("authorization", "Bearer testtok"),)
        req = SimpleNamespace(session_id="", ruleset="", facts=[])
        result = svc.Evaluate(req, ctx)
        assert "decision" in result

    def test_path_jail_parent_traversal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        ctx.metadata = (("authorization", "Bearer testtok"),)
        req = SimpleNamespace(session_id="", ruleset="../escape", facts=[])
        with pytest.raises(RuntimeError, match="aborted"):
            svc.Evaluate(req, ctx)

    def test_auth_required_on_assert_fact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        req = SimpleNamespace(session_id="", template="", data_json="{}")
        with pytest.raises(RuntimeError, match="aborted"):
            svc.AssertFact(req, ctx)

    def test_auth_required_on_query(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        req = SimpleNamespace(session_id="", template="", filter_json="")
        with pytest.raises(RuntimeError, match="aborted"):
            svc.Query(req, ctx)

    def test_auth_required_on_retract(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "testtok")
        monkeypatch.setenv("FATHOM_RULESET_ROOT", str(tmp_path))
        svc = FathomServicer()
        ctx = _FakeContext()
        req = SimpleNamespace(session_id="", template="", filter_json="")
        with pytest.raises(RuntimeError, match="aborted"):
            svc.Retract(req, ctx)
