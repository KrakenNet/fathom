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
* the ``fathom_token`` cookie — granted once by opening the Studio at
  ``/?token=<FATHOM_API_TOKEN>``, so the browser panels' plain HTML forms
  (which cannot set headers) keep working. Same-origin ``fetch`` sends the
  cookie automatically, so the creem SPA is covered by the same grant.

The cookie value is an opaque per-process session id, never the API token
itself: a browser cookie jar is on-disk storage the operator does not control,
and the token also opens the mounted ``/v1`` routes. Granting a session id
instead keeps the secret in the server process, so revoking is a restart and a
stolen cookie cannot be replayed as a bearer token against the REST API.

When ``FATHOM_API_TOKEN`` is unset, ``verify_token`` returns ``False`` and the
Studio is closed: an unconfigured deployment exposes nothing.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request
from fathom.integrations.auth import verify_token

if TYPE_CHECKING:
    from starlette.responses import Response

#: Cookie carrying an opaque Studio session id for browser panels.
TOKEN_COOKIE = "fathom_token"

#: Session ids handed out by :func:`grant_cookie`, held in memory only. A
#: restart revokes every browser grant, which is the intended blast radius for
#: a localhost developer tool.
_GRANTED: set[str] = set()

#: Ceiling on :data:`_GRANTED`. One entry per browser grant; the bound stops a
#: caller looping ``/?token=`` from growing the process without limit.
_MAX_GRANTS = 1024

#: Query parameter accepted on ``GET /`` to seed :data:`TOKEN_COOKIE`.
TOKEN_QUERY_PARAM = "token"


def _cookie_authorized(request: Request) -> bool:
    """Return True when the request carries a session id this process granted."""
    cookie = request.cookies.get(TOKEN_COOKIE)
    if not cookie:
        return False
    # compare_digest against every granted id rather than a set lookup: hashing
    # the cookie would leak its prefix through timing on the bucket probe.
    return any(secrets.compare_digest(cookie, granted) for granted in tuple(_GRANTED))


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
    """Grant a Studio session cookie on *response* when *token* is the real token.

    Returns whether the grant was made. The cookie carries a freshly minted
    opaque session id -- never ``FATHOM_API_TOKEN`` -- and is ``HttpOnly`` and
    ``SameSite=strict``.
    """
    if not verify_token(f"Bearer {token}"):
        return False
    if len(_GRANTED) >= _MAX_GRANTS:
        _GRANTED.clear()
    session_id = secrets.token_urlsafe(32)
    _GRANTED.add(session_id)
    response.set_cookie(TOKEN_COOKIE, session_id, httponly=True, samesite="strict")
    return True
