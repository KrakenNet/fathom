"""Tests for bearer-token auth module."""

from __future__ import annotations

import pytest

from fathom.integrations.auth import (
    AuthError,
    get_configured_token,
    verify_admin_token,
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


class TestVerifyAdminToken:
    def test_falls_back_to_api_token_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No FATHOM_ADMIN_TOKEN → data-plane token authorises (backward compat)."""
        monkeypatch.delenv("FATHOM_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("FATHOM_API_TOKEN", "dataplane")
        assert verify_admin_token("Bearer dataplane") is True
        assert verify_admin_token("Bearer wrong") is False

    def test_empty_admin_token_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty FATHOM_ADMIN_TOKEN is treated as unset → falls back."""
        monkeypatch.setenv("FATHOM_ADMIN_TOKEN", "")
        monkeypatch.setenv("FATHOM_API_TOKEN", "dataplane")
        assert verify_admin_token("Bearer dataplane") is True

    def test_admin_token_required_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When set, only the admin token authorises — data-plane is rejected."""
        monkeypatch.setenv("FATHOM_ADMIN_TOKEN", "adminsecret")
        monkeypatch.setenv("FATHOM_API_TOKEN", "dataplane")
        assert verify_admin_token("Bearer adminsecret") is True
        assert verify_admin_token("Bearer dataplane") is False

    def test_rejects_missing_and_malformed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FATHOM_ADMIN_TOKEN", "adminsecret")
        assert verify_admin_token(None) is False
        assert verify_admin_token("adminsecret") is False  # missing Bearer prefix
