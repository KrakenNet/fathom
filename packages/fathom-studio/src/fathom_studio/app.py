"""Fathom Policy Studio application.

The Studio is a FastAPI + HTMX app that mounts the production REST server
(:mod:`fathom.integrations.rest`) **in the same process** under ``/api``. Because
it is mounted (not proxied), the Studio and the REST app share the REST module's
in-memory :class:`~fathom.integrations.rest.SessionStore`, so working-memory state
asserted through the panels is visible to subsequent calls.

From the browser the REST routes are reached under ``/api`` — e.g. the rules-engine
``POST /v1/evaluate`` is ``POST /api/v1/evaluate``.

The Studio's own panels and JSON API are gated on the same ``FATHOM_API_TOKEN``
the mounted REST app requires (:mod:`fathom_studio.auth`), so the Studio is never
a weaker door onto the engine it embeds. Only ``/health``, the SPA shell at
``/`` and its static ``/creem`` assets are ungated. To use the browser panels,
open the Studio once as ``/?token=<FATHOM_API_TOKEN>``: the token is validated
and stored in the ``fathom_token`` cookie, which the plain HTML forms and the
SPA's same-origin ``fetch`` calls then carry automatically.

A per-browser session is minted as the ``fathom_sid`` cookie (uuid4) by
:class:`~fathom_studio.sessions.SessionCookieMiddleware`; panel handlers read
it via :func:`~fathom_studio.sessions.get_sid` and forward it on REST calls as
the ``X-Session-Id`` header. The session contract lives in
:mod:`fathom_studio.sessions`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fathom import __version__ as _fathom_version
from fathom.integrations.rest import app as rest_app

from fathom_studio.auth import TOKEN_QUERY_PARAM, grant_cookie
from fathom_studio.panels import router as panels_router
from fathom_studio.sessions import SessionCookieMiddleware
from fathom_studio.studio_api import router as studio_api_router

#: Default port for ``python -m fathom_studio.app``.
DEFAULT_PORT = 8020

#: Directory holding the creem single-page-app assets (served at ``/creem``).
_CREEM_DIR = Path(__file__).resolve().parent / "creem"


def create_app() -> FastAPI:
    """Build the Studio app: session-cookie middleware, panels, mounted REST.

    The REST app is mounted at ``/api`` (same process) so it shares the REST
    module's in-memory ``SessionStore``. Panel routers and the session
    middleware are registered here; the session contract lives in
    :mod:`fathom_studio.sessions` and the token gate in
    :mod:`fathom_studio.auth`.
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

    @studio.get("/")
    async def home(token: str = "") -> FileResponse:
        """Serve the creem single-page app, granting the token cookie on ``?token=``.

        The shell itself carries no engine data, so it is ungated; every route
        the SPA then calls requires the cookie this hands out.
        """
        response = FileResponse(_CREEM_DIR / "index.html")
        if token:
            grant_cookie(response, token)
        return response

    # The creem SPA (CSS/JS/JSX assets) is served as static files; its JSON
    # backend lives under ``/studio/api`` and the legacy server-rendered panels
    # remain reachable under their own routes. Both routers are token-gated.
    studio.mount("/creem", StaticFiles(directory=str(_CREEM_DIR)), name="creem")
    studio.include_router(studio_api_router)
    studio.include_router(panels_router)
    studio.mount("/api", rest_app)
    return studio


app = create_app()


def main() -> None:
    """Run the Studio under uvicorn (``python -m fathom_studio.app``)."""
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
    token = os.environ.get("FATHOM_API_TOKEN", "")
    if token:
        print(f"Studio ready: http://{args.host}:{args.port}/?{TOKEN_QUERY_PARAM}={token}")
    else:
        print("FATHOM_API_TOKEN is not set; the Studio will refuse every gated route.")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
