"""Make ``fathom_studio`` importable when the package is not installed.

``fathom-studio`` is a sibling package of ``fathom-rules`` in this repo, so
``uv run pytest packages/fathom-studio/tests`` from the repo root would not see
it. When it is properly installed (editable or from a wheel), this is a no-op.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("fathom_studio") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
