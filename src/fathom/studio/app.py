"""Fathom Policy Studio application.

The Studio is a FastAPI + HTMX app that mounts the production REST server
(:mod:`fathom.integrations.rest`) **in the same process** under ``/api``. Because
it is mounted (not proxied), the Studio and the REST app share the REST module's
in-memory :class:`~fathom.integrations.rest.SessionStore`, so working-memory state
asserted through the panels is visible to subsequent calls.

From the browser the REST routes are reached under ``/api`` — e.g. the rules-engine
``POST /v1/evaluate`` is ``POST /api/v1/evaluate``.

A per-browser session is minted as the ``fathom_sid`` cookie (uuid4) by
:func:`SessionCookieMiddleware`; panel handlers read it via :func:`get_sid` and
forward it on REST calls as the ``X-Session-Id`` header.
"""

from __future__ import annotations

import argparse
import os
import uuid
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from fathom import __version__ as _fathom_version
from fathom.integrations.rest import app as rest_app

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.responses import Response

#: Cookie name carrying the per-browser Studio session id.
SESSION_COOKIE = "fathom_sid"

#: Request-state attribute where the resolved session id is stashed.
_SID_STATE_ATTR = "fathom_sid"

#: Default port for ``python -m fathom.studio.app``.
DEFAULT_PORT = 8020


def get_sid(request: Request) -> str:
    """Return the Studio session id for *request*.

    The id is minted by :class:`SessionCookieMiddleware` and stashed on
    ``request.state`` before the route runs; it falls back to the raw cookie
    value (then a fresh uuid4) so the helper is usable outside the middleware
    path (e.g. in tests).
    """
    sid = getattr(request.state, _SID_STATE_ATTR, None)
    if isinstance(sid, str) and sid:
        return sid
    cookie = request.cookies.get(SESSION_COOKIE)
    return cookie if cookie else uuid.uuid4().hex


class SessionCookieMiddleware(BaseHTTPMiddleware):
    """Mint a ``fathom_sid`` cookie per browser and expose it on request state.

    On every request the middleware reads the ``fathom_sid`` cookie, minting a
    fresh uuid4 when absent, stashes it on ``request.state`` (so :func:`get_sid`
    can read it without re-parsing), and sets the cookie on the response when it
    was newly minted.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        sid = request.cookies.get(SESSION_COOKIE)
        minted = sid is None
        if sid is None:
            sid = uuid.uuid4().hex
        setattr(request.state, _SID_STATE_ATTR, sid)
        response = await call_next(request)
        if minted:
            response.set_cookie(
                SESSION_COOKIE,
                sid,
                httponly=True,
                samesite="lax",
            )
        return response


def create_app() -> FastAPI:
    """Build the Studio app: session-cookie middleware, health route, mounted REST.

    The REST app is mounted at ``/api`` (same process) so it shares the REST
    module's in-memory ``SessionStore``. Panel routers are registered by later
    tasks; this is the scaffold.
    """
    studio = FastAPI(
        title="Fathom Policy Studio",
        version=_fathom_version,
        description="Interactive UI over the Fathom rules engine",
    )
    studio.add_middleware(SessionCookieMiddleware)

    @studio.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe for the Studio process."""
        return {"status": "ok"}

    studio.mount("/api", rest_app)
    return studio


app = create_app()


def main() -> None:
    """Run the Studio under uvicorn (``python -m fathom.studio.app``)."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Fathom Policy Studio")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("FATHOM_STUDIO_PORT") or DEFAULT_PORT),
        help=f"bind port (default {DEFAULT_PORT})",
    )
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
