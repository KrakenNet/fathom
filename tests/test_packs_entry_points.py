"""Tests for the public rule-pack entry-point loader.

Every name registered in pyproject's ``[project.entry-points."fathom.packs"]``
group must load into a fresh Engine through ``Engine.load_pack`` -- the
documented public API. These tests exercise ``RulePackLoader`` itself rather
than hand-rolling per-pack directory fixtures.
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.packs import RulePackLoader

if TYPE_CHECKING:
    from collections.abc import Callable

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _registered_packs() -> dict[str, str]:
    """Return the ``fathom.packs`` entry points declared in pyproject.toml."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    packs: dict[str, str] = data["project"]["entry-points"]["fathom.packs"]
    return packs


PACK_NAMES = sorted(_registered_packs())


# =========================================================================
# Every registered pack loads through the public API
# =========================================================================


class TestRegisteredPacksLoad:
    """Each declared entry point resolves and loads into a fresh Engine."""

    def test_pack_names_are_registered_in_metadata(self) -> None:
        installed = {ep.name for ep in entry_points(group="fathom.packs")}
        assert set(PACK_NAMES) <= installed

    @pytest.mark.parametrize("pack_name", PACK_NAMES)
    def test_pack_loads_into_fresh_engine(self, pack_name: str) -> None:
        engine = Engine()
        engine.load_pack(pack_name)
        assert engine.template_registry, f"{pack_name} registered no templates"
        assert engine._module_registry, f"{pack_name} registered no modules"

    @pytest.mark.parametrize("pack_name", PACK_NAMES)
    def test_pack_module_exposes_loader_api(self, pack_name: str) -> None:
        """All packs expose the same get_templates/get_modules/get_rules API."""
        module = importlib.import_module(_registered_packs()[pack_name])
        for loader_name in ("get_templates", "get_modules", "get_rules"):
            loader: Callable[[], list[dict[str, Any]]] = getattr(module, loader_name)
            assert loader(), f"{pack_name}.{loader_name}() returned nothing"

    def test_unknown_pack_raises_compilation_error(self) -> None:
        with pytest.raises(CompilationError, match="not found in fathom.packs"):
            Engine().load_pack("no-such-pack")


# =========================================================================
# Declared dependencies
# =========================================================================


class TestPackDependencies:
    """A pack that declares PACK_DEPENDENCIES pulls them in first."""

    def test_cmmc_pulls_in_nist(self) -> None:
        engine = Engine()
        engine.load_pack("cmmc")
        assert "nist" in engine._module_registry
        assert {"audit_event", "data_transfer", "cui_policy"} <= set(engine.template_registry)

    def test_dependency_already_loaded_is_not_reloaded(self) -> None:
        engine = Engine()
        engine.load_pack("nist-800-53")
        engine.load_pack("cmmc")
        assert "cmmc" in engine._module_registry

    def test_pack_is_not_loaded_twice(self) -> None:
        engine = Engine()
        engine.load_pack("cmmc")
        engine.load_pack("nist-800-53")
        engine.load_pack("cmmc")
        assert "cmmc" in engine._module_registry

    def test_circular_dependency_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        packs = {}
        for name, dependency in (("pack-a", "pack-b"), ("pack-b", "pack-a")):
            pack_dir = tmp_path / name
            (pack_dir / "templates").mkdir(parents=True)
            module = ModuleType(name.replace("-", "_"))
            module.__path__ = [str(pack_dir)]  # type: ignore[attr-defined]
            module.PACK_DEPENDENCIES = (dependency,)  # type: ignore[attr-defined]
            packs[name] = module

        def fake_entry_points(*, group: str) -> list[SimpleNamespace]:
            assert group == "fathom.packs"
            return [SimpleNamespace(name=n, load=lambda m=m: m) for n, m in packs.items()]

        monkeypatch.setattr("fathom.packs.entry_points", fake_entry_points)
        with pytest.raises(CompilationError, match="Circular rule pack dependency"):
            RulePackLoader.load(Engine(), "pack-a")


# =========================================================================
# Template collisions between packs
# =========================================================================


class TestTemplateCollisions:
    """Two packs defining incompatible same-named templates fail loudly."""

    def test_hipaa_then_nist_reports_the_collision(self) -> None:
        engine = Engine()
        engine.load_pack("hipaa")
        with pytest.raises(CompilationError) as excinfo:
            engine.load_pack("nist-800-53")
        message = str(excinfo.value)
        assert "data_transfer" in message
        assert "hipaa" in message
        assert "nist-800-53" in message

    def test_collision_does_not_half_load_the_second_pack(self) -> None:
        engine = Engine()
        engine.load_pack("hipaa")
        with pytest.raises(CompilationError):
            engine.load_pack("nist-800-53")
        assert "nist" not in engine._module_registry


# =========================================================================
# Loader plumbing
# =========================================================================


class TestLoaderPlumbing:
    """discover() keeps returning a directory path for third-party callers."""

    def test_discover_returns_pack_directory(self) -> None:
        pack_dir = RulePackLoader.discover("hipaa")
        assert (pack_dir / "rules" / "hipaa_rules.yaml").is_file()

    def test_discover_unknown_pack_raises_compilation_error(self) -> None:
        with pytest.raises(CompilationError):
            RulePackLoader.discover("no-such-pack")

    def test_pack_without_path_raises_compilation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("pathless_pack")
        sys.modules.pop("pathless_pack", None)

        def fake_entry_points(*, group: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(name="pathless", load=lambda: module)]

        monkeypatch.setattr("fathom.packs.entry_points", fake_entry_points)
        with pytest.raises(CompilationError, match="no discoverable path"):
            RulePackLoader.discover("pathless")


class TestReloadForgetsLoadedPacks:
    """`reload_rules` discards the rule registry, so the pack record must go too.

    Keeping it made a later `load_pack` a silent no-op: the call succeeded
    while the pack's rules stayed absent. A pack that appears loaded but
    whose deny rules are gone is a quiet policy weakening, so the retry must
    be attempted — and fail loudly if it cannot succeed.
    """

    def test_pack_is_not_reported_loaded_after_a_reload(self, tmp_path: Path) -> None:
        from fathom.engine import Engine
        from fathom.packs import _pack_state

        engine = Engine()
        engine.load_pack("hipaa")
        assert "hipaa" in _pack_state[engine].loaded
        assert any(r.startswith("hipaa::") for r in engine.rule_registry)

        other = (
            "module: hipaa\n"
            "ruleset: noop\n"
            "rules:\n"
            "  - name: noop\n"
            "    when:\n"
            "      - template: phi_policy\n"
            "        conditions:\n"
            "          - slot: role\n"
            '            expression: "equals(nobody)"\n'
            "    then:\n"
            "      action: deny\n"
            '      reason: "n"\n'
        )
        engine.reload_rules(other.encode())

        # The pack's rules are gone...
        assert not any(r.startswith("hipaa::breach") for r in engine.rule_registry)
        # ...so the engine must no longer claim to hold the pack.
        assert engine not in _pack_state or "hipaa" not in _pack_state[engine].loaded
