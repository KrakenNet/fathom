"""Bearer-token authentication for REST and gRPC integrations.

The data-plane token is read from ``FATHOM_API_TOKEN`` on each verification.
An optional ``FATHOM_ADMIN_TOKEN`` scopes the ruleset-reload admin surface:
when set, reload requires it and the data-plane token no longer works for
reload; when unset, reload falls back to ``FATHOM_API_TOKEN`` (backward
compatible). All tokens are compared with ``hmac.compare_digest`` to avoid
timing leaks.
"""

from __future__ import annotations

import hmac
import os


class AuthError(RuntimeError):
    """Raised when auth configuration is missing or invalid."""


def get_configured_token() -> str:
    """Return the token from ``FATHOM_API_TOKEN`` or raise ``AuthError``."""
    token = os.environ.get("FATHOM_API_TOKEN", "")
    if not token:
        raise AuthError("FATHOM_API_TOKEN is not set. Server mode requires a bearer token.")
    return token


def _presented_bearer(authorization_header: str | None) -> str | None:
    """Extract the token from a ``"Bearer <token>"`` header, else ``None``."""
    if not authorization_header:
        return None
    prefix = "Bearer "
    if not authorization_header.startswith(prefix):
        return None
    return authorization_header[len(prefix) :]


def verify_token(authorization_header: str | None) -> bool:
    """Return True when the ``Authorization`` header matches the configured token.

    Expects the header in the form ``"Bearer <token>"``. Returns ``False`` for
    missing, malformed, or mismatched values.
    """
    presented = _presented_bearer(authorization_header)
    if presented is None:
        return False
    try:
        configured = get_configured_token()
    except AuthError:
        return False
    return hmac.compare_digest(presented.encode(), configured.encode())


def verify_admin_token(authorization_header: str | None) -> bool:
    """Return True when the header is authorised for the reload admin surface.

    Scoped-token behaviour:

    * When ``FATHOM_ADMIN_TOKEN`` is set, the header must match it exactly.
      The data-plane ``FATHOM_API_TOKEN`` does **not** grant reload.
    * When ``FATHOM_ADMIN_TOKEN`` is unset (or empty), this falls back to
      :func:`verify_token` — the existing ``FATHOM_API_TOKEN`` behaviour,
      kept for backward compatibility.

    Returns ``False`` for missing, malformed, or mismatched values.
    """
    admin = os.environ.get("FATHOM_ADMIN_TOKEN", "")
    if not admin:
        return verify_token(authorization_header)
    presented = _presented_bearer(authorization_header)
    if presented is None:
        return False
    return hmac.compare_digest(presented.encode(), admin.encode())
