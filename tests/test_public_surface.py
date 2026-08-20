"""Bind the declared public surface to the one the package actually exposes.

`VERSIONING.md` promises that everything in `fathom.__all__` keeps working and
that everything else may move without notice. A promise nobody checks drifts:
the list rots as symbols are added, and callers cannot tell which half of the
document is current. These tests fail on that drift instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import fathom
from fathom import attestation, audit, chained_log, engine, errors, fleet, models

VERSIONING = Path(__file__).resolve().parents[1] / "VERSIONING.md"

_COVERED_BLOCK = re.compile(
    r"<!-- BEGIN COVERED SYMBOLS -->\n(.*?)\n<!-- END COVERED SYMBOLS -->",
    re.S,
)
_BULLET = re.compile(r"^- `([^`]+)`$", re.M)

#: Every module VERSIONING.md names as having its own covered ``__all__``.
DOCUMENTED_MODULES = [attestation, audit, chained_log, engine, errors, fleet, models]


def _documented_symbols() -> list[str]:
    match = _COVERED_BLOCK.search(VERSIONING.read_text(encoding="utf-8"))
    assert match is not None, "VERSIONING.md is missing its COVERED SYMBOLS markers"
    return _BULLET.findall(match.group(1))


def test_versioning_md_lists_exactly_the_exported_symbols() -> None:
    documented = _documented_symbols()
    assert documented == sorted(fathom.__all__), (
        "VERSIONING.md and fathom.__all__ disagree. Adding a symbol to __all__ "
        "commits the project to keeping it working, so the list in "
        "VERSIONING.md has to be updated in the same change."
    )


@pytest.mark.parametrize("name", sorted(fathom.__all__))
def test_every_exported_symbol_resolves(name: str) -> None:
    """Including the lazy ones, which a typo would turn into an AttributeError."""
    assert getattr(fathom, name, None) is not None


@pytest.mark.parametrize("module", DOCUMENTED_MODULES, ids=lambda m: m.__name__)
def test_documented_modules_declare_a_surface(module: object) -> None:
    names = getattr(module, "__all__", None)
    assert names, f"{module.__name__} is named in VERSIONING.md but declares no __all__"
    assert list(names) == sorted(names), f"{module.__name__}.__all__ is not sorted"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.__all__ names a missing {name!r}"


def test_top_level_exports_come_from_a_module_that_declares_them() -> None:
    """A re-export must be public where it is defined, not only at the top.

    Exporting a name from ``fathom`` while its own module keeps it internal
    leaves two answers to "is this covered?", and the wrong one is reachable
    by the import path the docs use.
    """
    surfaces = {n for m in DOCUMENTED_MODULES for n in getattr(m, "__all__", ())}
    unbacked = [n for n in fathom.__all__ if not n.startswith("__") and n not in surfaces]
    assert not unbacked, f"exported from fathom but not from their own module: {unbacked}"
