"""Fathom Policy Studio application.

The Studio is a FastAPI + HTMX app that mounts the production REST server
(:mod:`fathom.integrations.rest`) **in the same process** under ``/api``. Because
it is mounted (not proxied), the Studio and the REST app share the REST module's
in-memory :class:`~fathom.integrations.rest.SessionStore`, so working-memory state
asserted through the panels is visible to subsequent calls.

From the browser the REST routes are reached under ``/api`` — e.g. the rules-engine
``POST /v1/evaluate`` is ``POST /api/v1/evaluate``.

A per-browser session is minted as the ``fathom_sid`` cookie (uuid4) by
:class:`~fathom.studio.sessions.SessionCookieMiddleware`; panel handlers read
it via :func:`~fathom.studio.sessions.get_sid` and forward it on REST calls as
the ``X-Session-Id`` header. The session contract lives in
:mod:`fathom.studio.sessions`.
"""

from __future__ import annotations

import argparse
import os

from fastapi import FastAPI

from fathom import __version__ as _fathom_version
from fathom.integrations.rest import app as rest_app
from fathom.studio.panels import router as panels_router
from fathom.studio.sessions import SessionCookieMiddleware

#: Default port for ``python -m fathom.studio.app``.
DEFAULT_PORT = 8020


def create_app() -> FastAPI:
    """Build the Studio app: session-cookie middleware, panels, mounted REST.

    The REST app is mounted at ``/api`` (same process) so it shares the REST
    module's in-memory ``SessionStore``. Panel routers and the session
    middleware are registered here; the session contract lives in
    :mod:`fathom.studio.sessions`.
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

    studio.include_router(panels_router)
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
