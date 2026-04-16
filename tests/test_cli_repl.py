"""REPL input handling tests."""

from __future__ import annotations

import pytest

pytest.importorskip("typer", reason="Typer (fathom-rules[cli] extra) is required for REPL tests")

from fathom.cli import _repl_loop  # noqa: E402
from fathom.engine import Engine
from fathom.models import SlotDefinition, SlotType, TemplateDefinition


@pytest.fixture
def engine_with_templates() -> Engine:
    e = Engine()
    for name in ("user", "user_banned"):
        e._template_registry[name] = TemplateDefinition(
            name=name,
            slots=[SlotDefinition(name="id", type=SlotType.STRING, required=True)],
        )
        e._safe_build(
            f"(deftemplate {name} (slot id (type STRING)))",
            context=name,
        )
    e.assert_fact("user", {"id": "alice"})
    e.assert_fact("user_banned", {"id": "mallory"})
    return e


def test_query_exact_template_does_not_match_prefix_collision(
    engine_with_templates: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`query user` must not match `user_banned` facts."""
    cmds = iter(["query user", "quit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(cmds))
    _repl_loop(engine_with_templates)
    out = capsys.readouterr().out
    assert "alice" in out
    assert "mallory" not in out


def test_retract_exact_template_does_not_retract_prefix_collision(
    engine_with_templates: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`retract user` must not retract `user_banned` facts."""
    cmds = iter(["retract user", "quit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(cmds))
    _repl_loop(engine_with_templates)
    assert engine_with_templates.query("user") == []
    assert engine_with_templates.query("user_banned") == [{"id": "mallory"}]
