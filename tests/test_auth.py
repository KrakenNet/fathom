"""Tests for bearer-token auth module."""

from __future__ import annotations

import pytest

from fathom.integrations.auth import (
    AuthError,
    get_configured_token,
    verify_token,
)


class TestGetConfiguredToken:
    def test_returns_env_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "abc123")
        assert get_configured_token() == "abc123"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FATHOM_API_TOKEN", raising=False)
        with pytest.raises(AuthError, match="FATHOM_API_TOKEN"):
            get_configured_token()

    def test_raises_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "")
        with pytest.raises(AuthError, match="FATHOM_API_TOKEN"):
            get_configured_token()


class TestVerifyToken:
    def test_accepts_matching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "secret")
        assert verify_token("Bearer secret") is True

    def test_rejects_missing_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "secret")
        assert verify_token("secret") is False

    def test_rejects_wrong_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "secret")
        assert verify_token("Bearer wrong") is False

    def test_rejects_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_API_TOKEN", "secret")
        assert verify_token(None) is False

    def test_short_wrong_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Short wrong token is rejected; exact match accepted.

        The function uses hmac.compare_digest internally, but this test
        verifies outcomes, not timing.
        """
        monkeypatch.setenv("FATHOM_API_TOKEN", "secret")
        assert verify_token("Bearer s") is False
        assert verify_token("Bearer secret") is True
