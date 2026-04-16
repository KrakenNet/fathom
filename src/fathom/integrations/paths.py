"""Path-jailing utilities for user-supplied ruleset paths.

Every user-facing path is interpreted relative to the server's configured
``FATHOM_RULESET_ROOT``. Resolved paths (after symlink resolution) must
remain descendants of the root.
"""

from __future__ import annotations

from pathlib import Path


class PathJailError(ValueError):
    """Raised when a user-supplied path escapes the configured ruleset root."""


def resolve_ruleset(root: str, user_path: str) -> Path:
    """Resolve *user_path* relative to *root* and verify it stays inside.

    Returns the fully-resolved absolute :class:`Path`. Raises
    :class:`PathJailError` for parent traversals, absolute inputs, and
    symlinks that escape the root.

    Error messages never echo the resolved server-side ``root`` absolute
    path — that would leak internal filesystem layout to remote callers.
    """
    root_path = Path(root).resolve(strict=False)
    if not root_path.exists() or not root_path.is_dir():
        raise PathJailError("ruleset root is not configured correctly")

    candidate = Path(user_path)
    if candidate.is_absolute() or candidate.drive:
        raise PathJailError("invalid ruleset path")

    resolved = (root_path / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise PathJailError("invalid ruleset path") from None
    return resolved
