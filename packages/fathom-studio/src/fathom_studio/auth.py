"""Bearer-token gate for the Studio's own routes.

The Studio mounts the production REST app (whose ``/v1`` routes require
``FATHOM_API_TOKEN``) in the same process, so its own panels and JSON API must
not be a weaker door onto the same engine. Every Studio route that changes
state or loads a ruleset therefore depends on :func:`require_auth`, which
validates against the *same* token via
:func:`fathom.integrations.auth.verify_token` — there is no second secret.

Two ways to present it, both checked with the constant-time comparison in
:mod:`fathom.integrations.auth`:

* ``Authorization: Bearer <token>`` — used by the JSON API, ``curl``, tests;
* the ``fathom_token`` cookie — set once by opening the Studio at
  ``/?token=<FATHOM_API_TOKEN>``, so the browser panels' plain HTML forms
  (which cannot set headers) keep working. Same-origin ``fetch`` sends the
  cookie automatically, so the creem SPA is covered by the same grant.

When ``FATHOM_API_TOKEN`` is unset, ``verify_token`` returns ``False`` and the
Studio is closed: an unconfigured deployment exposes nothing.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request
from fathom.integrations.auth import verify_token

if TYPE_CHECKING:
    from starlette.responses import Response

#: Cookie carrying the operator's ``FATHOM_API_TOKEN`` for browser panels.
TOKEN_COOKIE = "fathom_token"

#: Query parameter accepted on ``GET /`` to seed :data:`TOKEN_COOKIE`.
TOKEN_QUERY_PARAM = "token"


def _cookie_authorized(request: Request) -> bool:
    """Return True when the request carries a valid :data:`TOKEN_COOKIE`."""
    cookie = request.cookies.get(TOKEN_COOKIE)
    if not cookie:
        return False
    return verify_token(f"Bearer {cookie}")


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency gating Studio routes on ``FATHOM_API_TOKEN``.

    Accepts the token from the ``Authorization: Bearer`` header or the
    :data:`TOKEN_COOKIE`; raises ``401`` for anything else, including a Studio
    running with no ``FATHOM_API_TOKEN`` configured.
    """
    if verify_token(authorization) or _cookie_authorized(request):
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def grant_cookie(response: Response, token: str) -> bool:
    """Set :data:`TOKEN_COOKIE` on *response* when *token* is the real token.

    Returns whether the grant was made. The cookie value is the configured
    ``FATHOM_API_TOKEN`` (trusted server-side state), so it is ``HttpOnly`` and
    ``SameSite=strict``.
    """
    if not verify_token(f"Bearer {token}"):
        return False
    configured_token = os.environ.get("FATHOM_API_TOKEN", "")
    if not configured_token:
        return False
    response.set_cookie(TOKEN_COOKIE, configured_token, httponly=True, samesite="strict")
    return True
