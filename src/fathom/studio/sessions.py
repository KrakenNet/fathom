"""Studio session contract and the shared in-process evaluate helper.

This module owns the canonical Studio session handling so the rest of the
package depends on it without forming an import cycle (``app`` and ``panels``
both import from here; neither imports the other for session helpers).

**Session contract** (design "Session handling"): per browser a ``fathom_sid``
cookie is minted by :class:`SessionCookieMiddleware`; :func:`get_sid` resolves
it off ``request.state``; it is forwarded to the mounted REST app as both the
``X-Session-Id`` header *and* the body ``session_id`` on every
``/v1/evaluate`` call (the body field drives the REST ``SessionStore`` working
memory; the header keeps the contract uniform with the stateful ``/v1/rules``
and ``/v1/modules`` routes).

:func:`post_evaluate` is the single in-process ``POST /v1/evaluate`` path used
by both the Playground (``panels``) and the scenario seeder (``scenarios``);
:func:`error_detail` is the shared non-200 message extractor.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx
from httpx import ASGITransport
from starlette.middleware.base import BaseHTTPMiddleware

from fathom.integrations.rest import app as rest_app

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from fastapi import Request
    from starlette.responses import Response

#: Cookie name carrying the per-browser Studio session id.
SESSION_COOKIE = "fathom_sid"

#: Request-state attribute where the resolved session id is stashed.
_SID_STATE_ATTR = "fathom_sid"

#: Base URL used for the in-process ASGI calls to the mounted REST app.
_INTERNAL_BASE_URL = "http://studio.internal"


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


async def post_evaluate(
    *,
    sid: str,
    token: str,
    facts: Sequence[dict[str, Any]],
    ruleset: str,
    error_prefix: str,
    request_error_prefix: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call ``POST /v1/evaluate`` on the mounted REST app in-process.

    Forwards the session both ways (``X-Session-Id`` header + body
    ``session_id``) per the Studio session contract and returns
    ``(payload, error)``. On a non-200 the message is
    ``f"{error_prefix} ({status}): {detail}"``; on a transport failure it is
    ``f"{request_error_prefix}: {exc}"``.
    """
    body = {"facts": list(facts), "ruleset": ruleset, "session_id": sid}
    transport = ASGITransport(app=rest_app)
    async with httpx.AsyncClient(transport=transport, base_url=_INTERNAL_BASE_URL) as client:
        try:
            response = await client.post(
                "/v1/evaluate",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Session-Id": sid,
                },
            )
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            return None, f"{request_error_prefix}: {exc}"

    if response.status_code != 200:
        return None, f"{error_prefix} ({response.status_code}): {error_detail(response)}"
    return response.json(), None


def error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error message from a non-200 response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, str):
            return detail
    return response.text or response.reason_phrase
