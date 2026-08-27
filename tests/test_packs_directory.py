"""Tests for loading a rule pack that lives in a directory.

``Engine.load_pack`` only finds packs registered in the ``fathom.packs``
entry-point group -- installed distributions. A host that keeps packs as
directories (vendored, checked out, or uploaded at runtime) had to call the
four ``load_*`` methods itself in the one order that works, and got a raw
CLIPS diagnostic when it got that order wrong. These cover the loader that
replaces that hand-rolling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES = (
    "templates:\n"
    "  - name: agent\n"
    "    slots:\n"
    "      - name: id\n"
    "        type: symbol\n"
    "      - name: level\n"
    "        type: symbol\n"
)

MODULES = "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"

FUNCTIONS = (
    "functions:\n"
    "  - name: clearance\n"
    "    type: classification\n"
    "    params: [a, b]\n"
    "    hierarchy_ref: clearance.yaml\n"
)

HIERARCHY = "name: clearance\nlevels:\n  - public\n  - secret\n"

#: Calls ``meets-or-exceeds``, which only exists once ``functions/`` is
#: loaded -- so this rule is the load-order canary.
RULES_USING_A_FUNCTION = (
    "ruleset: gov\n"
    "module: gov\n"
    "rules:\n"
    "  - name: allow-cleared\n"
    "    when:\n"
    "      - template: agent\n"
    "        conditions:\n"
    "          - slot: level\n"
    '            expression: "meets_or_exceeds(public)"\n'
    "    then:\n"
    "      action: allow\n"
    "      reason: cleared\n"
)


def _write_subdir_pack(root: Path) -> Path:
    """A pack in the ``templates/ modules/ functions/ rules/`` convention."""
    for kind, body in (
        ("templates", TEMPLATES),
        ("modules", MODULES),
        ("functions", FUNCTIONS),
        ("rules", RULES_USING_A_FUNCTION),
    ):
        (root / kind).mkdir()
        (root / kind / f"{kind}.yaml").write_text(body)
    # A sibling hierarchies/ dir: load_functions globs functions/*.yaml, so
    # the hierarchy cannot sit beside the function that references it.
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "clearance.yaml").write_text(HIERARCHY)
    return root


# =========================================================================
# 1. The ordering, applied to a directory
# =========================================================================


class TestLoadPackDir:
    """``Engine.load_pack_dir`` loads a directory in dependency order."""

    def test_loads_a_pack_into_an_existing_engine(self, tmp_path: Path) -> None:
        """The point of the method: an engine that already exists gains a pack."""
        engine = Engine()
        assert not engine.rule_registry

        engine.load_pack_dir(_write_subdir_pack(tmp_path))

        assert "gov::allow-cleared" in engine.rule_registry
        assert "agent" in engine.template_registry

    def test_the_loaded_pack_evaluates(self, tmp_path: Path) -> None:
        """Ordering that merely does not raise is not enough; the rules must fire."""
        engine = Engine()
        engine.load_pack_dir(_write_subdir_pack(tmp_path))

        result = engine.evaluate_once([("agent", {"id": "a1", "level": "secret"})])

        assert result.decision == "allow"

    def test_a_flat_directory_loads_too(self, tmp_path: Path) -> None:
        """The other supported layout: top-level keys instead of subdirectories."""
        (tmp_path / "01-templates.yaml").write_text(TEMPLATES)
        (tmp_path / "02-modules.yaml").write_text(MODULES)
        (tmp_path / "03-rules.yaml").write_text(
            "ruleset: gov\nmodule: gov\nrules:\n"
            "  - name: allow-any\n    when:\n      - template: agent\n"
            '        conditions:\n          - slot: id\n            expression: "equals(a1)"\n'
            "    then:\n      action: allow\n      reason: ok\n"
        )

        engine = Engine()
        engine.load_pack_dir(tmp_path)

        result = engine.evaluate_once([("agent", {"id": "a1"})])

        assert result.decision == "allow"

    def test_loading_the_same_directory_twice_is_a_no_op(self, tmp_path: Path) -> None:
        """Rule names are unique per module, so a second load would otherwise fail."""
        engine = Engine()
        pack = _write_subdir_pack(tmp_path)

        engine.load_pack_dir(pack)
        engine.load_pack_dir(pack)  # must not raise "duplicate rule name"

        assert len(engine.rule_registry) == 1

    def test_identity_is_the_resolved_path(self, tmp_path: Path) -> None:
        """A relative path and its absolute form are the same pack, not two."""
        pack = _write_subdir_pack(tmp_path)
        engine = Engine()

        engine.load_pack_dir(str(pack))
        engine.load_pack_dir(str(pack) + "/.")

        assert len(engine.rule_registry) == 1


# =========================================================================
# 2. Failures a hand-rolled loader gave no warning about
# =========================================================================


class TestLoadPackDirRejections:
    """The loader refuses what the four-call sequence accepted silently."""

    def test_a_missing_directory_is_named(self, tmp_path: Path) -> None:
        engine = Engine()

        with pytest.raises(CompilationError, match="is not a directory"):
            engine.load_pack_dir(tmp_path / "nope")

    def test_a_file_is_not_a_pack(self, tmp_path: Path) -> None:
        target = tmp_path / "rules.yaml"
        target.write_text(TEMPLATES)
        engine = Engine()

        with pytest.raises(CompilationError, match="is not a directory"):
            engine.load_pack_dir(target)

    def test_a_directory_with_nothing_recognised_fails_loudly(self, tmp_path: Path) -> None:
        """Pointing one level too high used to build an engine with no rules."""
        (tmp_path / "README.md").write_text("not a pack\n")
        engine = Engine()

        with pytest.raises(CompilationError, match="holds nothing to load"):
            engine.load_pack_dir(tmp_path)

    def test_a_second_pack_may_not_redefine_a_template(self, tmp_path: Path) -> None:
        """Directory packs get the collision check entry-point packs already had."""
        first_dir = tmp_path / "first"
        first_dir.mkdir()
        first = _write_subdir_pack(first_dir)
        second = tmp_path / "second"
        (second / "templates").mkdir(parents=True)
        (second / "templates" / "t.yaml").write_text(
            "templates:\n  - name: agent\n    slots:\n"
            "      - name: completely\n        type: symbol\n"
        )

        engine = Engine()
        engine.load_pack_dir(first)

        with pytest.raises(CompilationError, match="redefines template 'agent'"):
            engine.load_pack_dir(second)

    def test_a_failed_load_claims_nothing(self, tmp_path: Path) -> None:
        """A rejected pack must not appear loaded, or the retry is a silent no-op."""
        pack = tmp_path / "broken"
        (pack / "templates").mkdir(parents=True)
        (pack / "templates" / "t.yaml").write_text(TEMPLATES)
        (pack / "rules").mkdir()
        (pack / "rules" / "r.yaml").write_text(
            "ruleset: gov\nmodule: gov\nrules:\n"
            "  - name: r\n    when:\n      - template: agent\n"
            '        conditions:\n          - slot: id\n            expression: "equals(a1)"\n'
            "    then:\n      action: allow\n      reason: ok\n"
        )

        engine = Engine()
        with pytest.raises(CompilationError):
            engine.load_pack_dir(pack)  # module 'gov' was never registered

        # The retry is attempted rather than skipped as already-loaded.
        with pytest.raises(CompilationError):
            engine.load_pack_dir(pack)


# =========================================================================
# 3. from_rules is the same loader
# =========================================================================


class TestFromRulesSharesTheLoader:
    """One implementation of the ordering, reached two ways."""

    def test_from_rules_still_loads_a_subdirectory_pack(self, tmp_path: Path) -> None:
        engine = Engine.from_rules(str(_write_subdir_pack(tmp_path)))

        result = engine.evaluate_once([("agent", {"id": "a1", "level": "secret"})])

        assert result.decision == "allow"

    def test_from_rules_and_load_pack_dir_agree(self, tmp_path: Path) -> None:
        pack = _write_subdir_pack(tmp_path)

        constructed = Engine.from_rules(str(pack))
        loaded = Engine()
        loaded.load_pack_dir(pack)

        assert set(constructed.rule_registry) == set(loaded.rule_registry)
        assert set(constructed.template_registry) == set(loaded.template_registry)


# =========================================================================
# 4. Focus is engine-wide: a second pack must not unfocus the first
# =========================================================================


def _write_flat_pack(root: Path, name: str, *, focus: bool = True) -> Path:
    """A one-module pack whose rule denies on ``(<name> (id go))``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "01-templates.yaml").write_text(
        f"templates:\n  - name: {name}\n    slots:\n      - name: id\n        type: symbol\n"
    )
    focus_line = f"focus_order: [{name}]\n" if focus else ""
    (root / "02-modules.yaml").write_text(f"modules:\n  - name: {name}\n{focus_line}")
    (root / "03-rules.yaml").write_text(
        f"ruleset: {name}\nmodule: {name}\nrules:\n"
        f"  - name: deny-{name}\n    when:\n      - template: {name}\n"
        '        conditions:\n          - slot: id\n            expression: "equals(go)"\n'
        f"    then:\n      action: deny\n      reason: {name}\n"
    )
    return root


class TestFocusSurvivesASecondPack:
    """``set_focus`` REPLACES, so loading pack B used to silently unfocus A.

    Nothing raised and A's rules stayed in the registry -- they simply
    stopped firing, and the decision fell through to the engine default with
    an empty ``rule_trace``. Policy that reads as enforced and is not.
    """

    def test_both_packs_still_fire(self, tmp_path: Path) -> None:
        engine = Engine()
        engine.load_pack_dir(_write_flat_pack(tmp_path / "a", "alpha"))
        engine.load_pack_dir(_write_flat_pack(tmp_path / "b", "beta"))

        assert engine.evaluate_once([("alpha", {"id": "go"})]).reason == "alpha"
        assert engine.evaluate_once([("beta", {"id": "go"})]).reason == "beta"

    def test_a_pack_declaring_no_focus_order_still_fires(self, tmp_path: Path) -> None:
        """The fallback used to be skipped whenever *any* focus already existed."""
        engine = Engine()
        engine.load_pack_dir(_write_flat_pack(tmp_path / "a", "alpha"))
        engine.load_pack_dir(_write_flat_pack(tmp_path / "b", "beta", focus=False))

        assert engine.evaluate_once([("alpha", {"id": "go"})]).reason == "alpha"
        assert engine.evaluate_once([("beta", {"id": "go"})]).reason == "beta"

    def test_the_declared_order_is_kept(self, tmp_path: Path) -> None:
        engine = Engine()
        engine.load_pack_dir(_write_flat_pack(tmp_path / "a", "alpha"))
        engine.load_pack_dir(_write_flat_pack(tmp_path / "b", "beta"))

        assert engine.focus_order == ["alpha", "beta"]

    def test_set_focus_still_replaces(self, tmp_path: Path) -> None:
        """The public API keeps its documented semantics; only loading appends."""
        engine = Engine()
        engine.load_pack_dir(_write_flat_pack(tmp_path / "a", "alpha"))
        engine.load_pack_dir(_write_flat_pack(tmp_path / "b", "beta"))

        engine.set_focus(["beta"])

        assert engine.focus_order == ["beta"]
        assert engine.evaluate_once([("alpha", {"id": "go"})]).rule_trace == []


def _write_shared_template_pack(root: Path, name: str) -> Path:
    """A pack whose ``request`` template is byte-identical across packs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "01-templates.yaml").write_text(
        "templates:\n  - name: request\n    slots:\n      - name: action\n        type: symbol\n"
    )
    (root / "02-modules.yaml").write_text(f"modules:\n  - name: {name}\nfocus_order: [{name}]\n")
    (root / "03-rules.yaml").write_text(
        f"ruleset: {name}\nmodule: {name}\nrules:\n"
        f"  - name: deny-{name}\n    when:\n      - template: request\n"
        "        conditions:\n          - slot: action\n"
        f'            expression: "equals({name})"\n'
        f"    then:\n      action: deny\n      reason: {name}\n"
    )
    return root


class TestTwoPacksMaySharTheSameTemplate:
    """``packs.py`` allows an identical redefinition; the engine then refused it.

    The collision check rejects only *incompatible* redefinitions -- two packs
    declaring the same template with the same slots are documented as sharing
    it. ``load_templates`` rebuilt it anyway, and CLIPS answered "Cannot
    redefine deftemplate 'request' while it is in use": the raw diagnostic
    that check exists to replace, on the one pairing it deliberately allows.
    """

    def test_both_packs_load_and_decide(self, tmp_path: Path) -> None:
        engine = Engine()
        engine.load_pack_dir(_write_shared_template_pack(tmp_path / "a", "alpha"))
        engine.load_pack_dir(_write_shared_template_pack(tmp_path / "b", "beta"))

        assert engine.evaluate_once([("request", {"action": "alpha"})]).reason == "alpha"
        assert engine.evaluate_once([("request", {"action": "beta"})]).reason == "beta"

    def test_an_incompatible_redefinition_is_still_rejected(self, tmp_path: Path) -> None:
        """Only the identical case is waved through."""
        engine = Engine()
        engine.load_pack_dir(_write_shared_template_pack(tmp_path / "a", "alpha"))

        clashing = tmp_path / "b"
        _write_shared_template_pack(clashing, "beta")
        (clashing / "01-templates.yaml").write_text(
            "templates:\n  - name: request\n    slots:\n"
            "      - name: action\n        type: string\n"
        )

        with pytest.raises(CompilationError):
            engine.load_pack_dir(clashing)
