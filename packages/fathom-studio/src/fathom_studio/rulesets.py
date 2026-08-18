"""Location of the demo rulesets the Studio evaluates against.

The Studio ships the ``examples/0N-*`` rulesets (their ``templates/`` /
``modules/`` / ``rules/`` / ``functions/`` / ``hierarchies/`` YAML) as package
data under ``fathom_studio/demo_rulesets/`` and resolves them with
:mod:`importlib.resources`. The previous ``Path(__file__).parents[3] /
"examples"`` walk only ever pointed at a real directory from a source checkout;
from an installed wheel it resolved outside the package and every ruleset load
failed, so the guardrail panel 500-ed and the SPA silently fell back to its
in-browser mock engine.

``FATHOM_RULESET_ROOT`` still overrides the packaged copy, so an operator can
point the Studio at their own rulesets.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

#: Name of the package-data directory holding the bundled demo rulesets.
_RULESETS_DIR = "demo_rulesets"


class RulesetRootError(RuntimeError):
    """Raised when the configured or packaged ruleset root does not exist."""


def packaged_root() -> Path:
    """Return the packaged ``demo_rulesets/`` directory, wherever the package lives."""
    return Path(str(resources.files(__package__ or "fathom_studio"))) / _RULESETS_DIR


def ruleset_root() -> str:
    """Return the ruleset root: ``FATHOM_RULESET_ROOT`` or the packaged rulesets.

    Raises :class:`RulesetRootError` when the resulting directory is missing,
    so a misconfigured Studio says so instead of degrading to fabricated data.
    """
    configured = os.environ.get("FATHOM_RULESET_ROOT")
    root = Path(configured) if configured else packaged_root()
    if not root.is_dir():
        raise RulesetRootError(
            f"Ruleset root '{root}' does not exist"
            + (" (set by FATHOM_RULESET_ROOT)" if configured else "")
        )
    return str(root)
