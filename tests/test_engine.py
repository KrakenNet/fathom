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
        "        conditions:\n          - slot: id\n            expression: \"equals(alice)\"\n"
        "    then:\n      action: allow\n      reason: ok\n"
    )
    engine = Engine.from_rules(str(tmp_path))
    assert "ok" in engine.rule_registry
    assert engine.rule_registry["ok"].name == "ok"


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
