"""Every shipped pack and example, held to the assertions one of them got.

Structural check A from the audit post-mortem. Three suites already made the
strongest possible claims about a shipped artifact -- ``fathom compile``
prints CLIPS that loads, ``fathom info`` lists the operators, the pack decides
what its docs say it decides -- and each made them about a single artifact
named as a string literal. Widening that sample to the directory listing, with
no new assertion, broke three of twelve targets.

So the sample is not chosen here. It is read off disk, and a pack added to
``src/fathom/rule_packs/`` or an example added to ``examples/`` is covered the
moment it lands.

Two shapes of target, distinguished by what the artifact itself declares:

- **self-contained** -- loads alone, so ``compile``/``info`` must both succeed
  on the directory by itself;
- **dependent** -- declares ``PACK_DEPENDENCIES``, so it is only meaningful
  together with what it names. ``Engine.load_pack`` is the surface that
  resolves that, and compiling the directory alone must *fail*, not print
  constructs that cannot load.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.packs import DEPENDENCIES_ATTR

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO / "src" / "fathom" / "rule_packs"
EXAMPLES_DIR = REPO / "examples"


def _pack_dirs() -> list[Path]:
    return sorted(
        p for p in PACKS_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
    )


def _example_dirs() -> list[Path]:
    return sorted(p for p in EXAMPLES_DIR.iterdir() if p.is_dir())


def _dependencies(pack_dir: Path) -> tuple[str, ...]:
    """What ``<pack>/__init__.py`` declares it needs loaded first."""
    module = importlib.import_module(f"fathom.rule_packs.{pack_dir.name}")
    return tuple(getattr(module, DEPENDENCIES_ATTR, ()))


#: Every shipped artifact, read off disk. Never a string literal.
ALL_TARGETS = _pack_dirs() + _example_dirs()
SELF_CONTAINED = [p for p in _pack_dirs() if not _dependencies(p)] + _example_dirs()
DEPENDENT = [p for p in _pack_dirs() if _dependencies(p)]


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "fathom.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=300,
        check=False,
    )


def _loads_into_clips(text: str) -> None:
    """Build *text* into an env prepared the way the Engine prepares one."""
    import clips

    env = clips.Environment()
    Engine()._register_external_functions(env=env)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.clp"
        out.write_text(text, encoding="utf-8")
        env.load(str(out))


@pytest.mark.parametrize("target", ALL_TARGETS, ids=_ids(ALL_TARGETS))
def test_every_shipped_target_validates(target: Path) -> None:
    result = _cli("validate", str(target))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("target", SELF_CONTAINED, ids=_ids(SELF_CONTAINED))
def test_a_self_contained_target_compiles_to_clips_that_loads(target: Path) -> None:
    result = _cli("compile", str(target), "--format", "raw")
    assert result.returncode == 0, result.stdout + result.stderr

    _loads_into_clips(result.stdout)


@pytest.mark.parametrize("target", SELF_CONTAINED, ids=_ids(SELF_CONTAINED))
def test_a_self_contained_target_reports_its_operators(target: Path) -> None:
    result = _cli("info", str(target))
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Functions (0)" not in result.stdout
    assert "fathom-matches" in result.stdout


@pytest.mark.parametrize("target", SELF_CONTAINED, ids=_ids(SELF_CONTAINED))
def test_a_self_contained_target_loads_as_an_engine(target: Path) -> None:
    engine = Engine.from_rules(str(target))

    assert engine.rule_registry, f"{target.name} registered no rules"


@pytest.mark.parametrize("target", DEPENDENT, ids=_ids(DEPENDENT))
def test_a_dependent_pack_refuses_to_compile_alone(target: Path) -> None:
    """Exit 0 over CLIPS that raises on line 1 is the failure this replaces."""
    result = _cli("compile", str(target), "--format", "raw")

    assert result.returncode != 0, (
        f"{target.name} declares {_dependencies(target)} yet compiled alone:\n"
        f"{result.stdout[:400]}"
    )


@pytest.mark.parametrize("target", DEPENDENT, ids=_ids(DEPENDENT))
def test_a_dependent_pack_compiles_with_what_it_declares(target: Path, tmp_path: Path) -> None:
    """Together with its dependencies, the same pack must produce loadable CLIPS."""
    staged = tmp_path / "staged"
    staged.mkdir()
    for name in (*_dependencies(target), target.name):
        source = PACKS_DIR / name.replace("-", "_")
        assert source.is_dir(), f"{target.name} declares unknown dependency {name!r}"
        shutil.copytree(source, staged / source.name)

    result = _cli("compile", str(staged), "--format", "raw")
    assert result.returncode == 0, result.stdout + result.stderr

    _loads_into_clips(result.stdout)


@pytest.mark.parametrize("pack", _pack_dirs(), ids=_ids(_pack_dirs()))
def test_every_pack_loads_through_the_entry_point_loader(pack: Path) -> None:
    """``load_pack`` is the surface that resolves ``PACK_DEPENDENCIES``."""
    engine = Engine()
    engine.load_pack(_entry_point_name(pack))

    assert engine.rule_registry, f"{pack.name} registered no rules"


def _entry_point_name(pack: Path) -> str:
    """The name the pack is registered under in the ``fathom.packs`` group."""
    from importlib.metadata import entry_points

    for entry in entry_points(group="fathom.packs"):
        if entry.value.rsplit(".", 1)[-1] == pack.name:
            return entry.name
    pytest.fail(f"{pack.name} is not registered in the fathom.packs entry-point group")


@pytest.fixture(autouse=True)
def _isolate_pack_state() -> Iterator[None]:
    """Pack loading keeps per-engine state keyed on the engine object."""
    yield
    from fathom.packs import _pack_state

    _pack_state.clear()
