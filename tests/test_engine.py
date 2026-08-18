from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_rule_registry_exposes_loaded_rules(tmp_path: Path) -> None:
    """Engine.rule_registry returns dict[str, RuleDefinition] after load_rules."""
    from fathom.engine import Engine

    # Build a minimal rule pack directory.
    (tmp_path / "templates.yaml").write_text(
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )
    (tmp_path / "rules.yaml").write_text(
        "ruleset: gov\nmodule: gov\nrules:\n"
        "  - name: ok\n    when:\n      - template: agent\n"
        '        conditions:\n          - slot: id\n            expression: "equals(alice)"\n'
        "    then:\n      action: allow\n      reason: ok\n"
    )
    engine = Engine.from_rules(str(tmp_path))
    assert "gov::ok" in engine.rule_registry
    assert engine.rule_registry["gov::ok"].name == "ok"


def test_focus_order_exposed_and_settable() -> None:
    from fathom.engine import Engine

    engine = Engine()
    assert engine.focus_order == []
    engine.set_focus(["a", "b"])
    assert engine.focus_order == ["a", "b"]


def test_assert_fact_rejects_fleet_scoped_template() -> None:
    from fathom.engine import Engine
    from fathom.errors import ScopeError
    from fathom.models import SlotDefinition, SlotType, TemplateDefinition

    engine = Engine()
    tmpl = TemplateDefinition(
        name="session_state",
        scope="fleet",
        slots=[SlotDefinition(name="user", type=SlotType.STRING, required=True)],
    )
    engine._template_registry["session_state"] = tmpl
    engine._safe_build(
        "(deftemplate session_state (slot user (type STRING)))",
        context="session_state",
    )

    with pytest.raises(ScopeError, match="FleetEngine"):
        engine.assert_fact("session_state", {"user": "alice"})


def _write_pack(root: Path, modules_yaml: str | None = None) -> None:
    """Minimal templates/ + modules/ subdirs a rules/ file can reference."""
    (root / "templates").mkdir()
    (root / "templates" / "t.yaml").write_text(
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    )
    (root / "modules").mkdir()
    (root / "modules" / "m.yaml").write_text(
        modules_yaml or "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )


def _rules_yaml(rule_name: str, action: str, reason: str) -> str:
    return (
        "ruleset: gov\nmodule: gov\nrules:\n"
        f"  - name: {rule_name}\n    when:\n      - template: agent\n"
        '        conditions:\n          - slot: id\n            expression: "equals(alice)"\n'
        f"    then:\n      action: {action}\n      reason: {reason}\n"
    )


def test_duplicate_rule_name_across_files_raises(tmp_path: Path) -> None:
    """C4: a second file redefining a rule name must fail, not silently win."""
    from fathom.engine import Engine
    from fathom.errors import CompilationError

    _write_pack(tmp_path)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "aa.yaml").write_text(_rules_yaml("r-deny", "deny", "blocked"))
    (rules_dir / "zz.yaml").write_text(_rules_yaml("r-deny", "allow", "OVERWRITTEN"))

    with pytest.raises(CompilationError, match="duplicate rule name 'gov::r-deny'"):
        Engine.from_rules(str(tmp_path))


def test_same_rule_name_in_two_modules_both_registered(tmp_path: Path) -> None:
    """The registry is keyed module::name, so cross-module names no longer collapse."""
    from fathom.engine import Engine

    _write_pack(
        tmp_path,
        "modules:\n  - name: gov\n    priority: 100\n"
        "  - name: sec\n    priority: 90\nfocus_order: [gov, sec]\n",
    )
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "gov.yaml").write_text(_rules_yaml("shared", "deny", "from-gov"))
    (rules_dir / "sec.yaml").write_text(
        _rules_yaml("shared", "allow", "from-sec").replace("module: gov", "module: sec")
    )

    engine = Engine.from_rules(str(tmp_path))
    assert set(engine.rule_registry) == {"gov::shared", "sec::shared"}


def test_load_templates_is_load_order_independent(tmp_path: Path) -> None:
    """Directory loads are sorted, not readdir-ordered (unsorted-glob-load-order)."""
    from fathom.engine import Engine

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    for name in ["zeta", "mid", "alpha"]:
        (templates_dir / f"{name}.yaml").write_text(
            f"templates:\n  - name: {name}\n    slots:\n"
            "      - name: id\n        type: symbol\n"
        )
    engine = Engine()
    engine.load_templates(str(templates_dir))
    assert list(engine.template_registry) == ["alpha", "mid", "zeta"]


def test_load_modules_focus_order_is_file_order_independent(tmp_path: Path) -> None:
    """A focus_order in a later-sorted file may reference an earlier-sorted module."""
    from fathom.engine import Engine

    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    (modules_dir / "alpha.yaml").write_text("modules:\n  - name: alpha\n    priority: 100\n")
    (modules_dir / "zeta.yaml").write_text(
        "modules:\n  - name: beta\n    priority: 90\nfocus_order: [beta, alpha]\n"
    )
    engine = Engine()
    engine.load_modules(str(modules_dir))
    assert engine.focus_order == ["beta", "alpha"]
