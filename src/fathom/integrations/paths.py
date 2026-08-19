"""Path-jailing utilities for user-supplied ruleset paths.

Every user-facing path is interpreted relative to the server's configured
``FATHOM_RULESET_ROOT``. Resolved paths (after symlink resolution) must
remain descendants of the root.

:func:`resolve_ruleset` is the *only* barrier between a request-supplied
ruleset name and the ``open()`` calls in :mod:`fathom.compiler`: both the REST
(``rest.py``) and gRPC (``grpc_server.py``) transports funnel through it before
handing anything to :meth:`fathom.engine.Engine.from_rules`. Keep it written in
a form static analysis recognises as sanitizing — see the comment on the
``startswith`` gate below.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathJailError(ValueError):
    """Raised when a user-supplied path escapes the configured ruleset root."""


def resolve_ruleset(root: str, user_path: str) -> Path:
    """Resolve *user_path* relative to *root* and verify it stays inside.

    Returns the fully-resolved absolute :class:`Path`. Raises
    :class:`PathJailError` for parent traversals, absolute inputs, and
    symlinks that escape the root.

    ``""`` and ``"."`` both mean the root itself. Any other spelling that
    normalises back to the root (``"sub/.."``) is rejected: the containment
    test is a strict-descendant check, and keeping it strict is what lets it
    stay a single unqualified guard (see the comment on it below).

    Error messages never echo the resolved server-side ``root`` absolute
    path — that would leak internal filesystem layout to remote callers.
    """
    root_path = Path(root).resolve(strict=False)
    if not root_path.exists() or not root_path.is_dir():
        raise PathJailError("ruleset root is not configured correctly")

    # An embedded null byte makes the OS path calls below raise a bare
    # ValueError, which callers catching PathJailError do not see (both
    # subclass ValueError) — it would surface as a 500 / UNKNOWN instead
    # of the documented rejection.
    if "\x00" in user_path:
        raise PathJailError("invalid ruleset path")

    candidate = Path(user_path)
    if candidate.is_absolute() or candidate.drive:
        raise PathJailError("invalid ruleset path")

    # The root directory is itself a legitimate ruleset -- the transports pass
    # an empty ruleset name to mean "everything under the root" -- and it is
    # the one path that cannot satisfy the descendant test below. Answer it
    # here so that test stays a single unqualified check.
    if str(candidate) == ".":
        return root_path

    root_str = str(root_path)
    try:
        resolved_str = os.path.realpath(os.path.join(root_str, str(candidate)))
    except (ValueError, OSError):
        raise PathJailError("invalid ruleset path") from None

    # ``os.path.realpath`` normalisation followed by a lone ``startswith``
    # against the root is the shape CodeQL's path-injection query models as a
    # sanitizing barrier -- ``Path.relative_to``/``os.path.commonpath`` are
    # equivalent but unrecognised, and even this check stops registering the
    # moment it gains a second disjunct, which puts the report back on every
    # downstream ``open()`` in the compiler.
    #
    # The trailing separator is load-bearing on its own account: without it a
    # sibling ``/srv/rules-evil`` passes a bare ``/srv/rules`` prefix.
    # ``os.path.join(root, "")`` appends it without doubling it when the root
    # is ``/``.
    if not resolved_str.startswith(os.path.join(root_str, "")):
        raise PathJailError("invalid ruleset path")
    return Path(resolved_str)
