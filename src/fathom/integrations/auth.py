"""Bearer-token authentication for REST and gRPC integrations.

Token is read from ``FATHOM_API_TOKEN`` on each verification. Tokens are
compared with ``hmac.compare_digest`` to avoid timing leaks.
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
        raise AuthError(
            "FATHOM_API_TOKEN is not set. Server mode requires a bearer token."
        )
    return token


def verify_token(authorization_header: str | None) -> bool:
    """Return True when the ``Authorization`` header matches the configured token.

    Expects the header in the form ``"Bearer <token>"``. Returns ``False`` for
    missing, malformed, or mismatched values.
    """
    if not authorization_header:
        return False
    prefix = "Bearer "
    if not authorization_header.startswith(prefix):
        return False
    presented = authorization_header[len(prefix):]
    try:
        configured = get_configured_token()
    except AuthError:
        return False
    return hmac.compare_digest(presented.encode(), configured.encode())
