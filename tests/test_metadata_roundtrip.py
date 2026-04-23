# tests/test_metadata_roundtrip.py
"""End-to-end metadata round-trip through compile + evaluate.

Guards against regressions of C2: the compiler/evaluator contract on how
the ``metadata`` slot is serialised through CLIPS.
"""

from __future__ import annotations

from fathom.engine import Engine
from fathom.models import (
    ActionType,
    FactPattern,
    ModuleDefinition,
    RuleDefinition,
    SlotDefinition,
    SlotType,
    TemplateDefinition,
    ThenBlock,
)


def test_rule_metadata_preserved_as_dict() -> None:
    """A rule that fires should produce result.metadata equal to the input dict."""
    engine = Engine()

    # MAIN must export before sub-modules can import from it.
    engine._safe_build("(defmodule MAIN (export ?ALL))", context="module:MAIN")

    engine._safe_build(
        "(deftemplate agent (slot id (type STRING)))",
        context="agent",
    )
    engine._template_registry["agent"] = TemplateDefinition(
        name="agent",
        slots=[SlotDefinition(name="id", type=SlotType.STRING, required=True)],
    )

    # Register a module we can attach the rule to.
    engine._module_registry["gov"] = ModuleDefinition(name="gov", description="test", priority=100)
    engine._focus_order = ["gov"]
    engine._evaluator._focus_order = ["gov"]
    engine._safe_build("(defmodule gov (import MAIN ?ALL))", context="gov")

    # Compile and build one rule with rich metadata.
    rule = RuleDefinition(
        name="allow-alice",
        when=[FactPattern(template="agent", alias="$a", conditions=[])],
        then=ThenBlock(
            action=ActionType.ALLOW,
            reason="test",
            metadata={
                "framework": "nist_800_53",
                "control_id": "AC-3",
                "cmmc_practice": "AC.L1-3.1.1",
            },
        ),
    )
    clips_str = engine._compiler.compile_rule(rule, "gov")
    engine._safe_build(clips_str, context="rule:allow-alice")

    engine.assert_fact("agent", {"id": "alice"})
    result = engine.evaluate()

    assert result.decision == "allow"
    assert result.metadata == {
        "framework": "nist_800_53",
        "control_id": "AC-3",
        "cmmc_practice": "AC.L1-3.1.1",
    }


def test_rule_empty_metadata_is_empty_dict() -> None:
    """Rules without metadata return result.metadata={}."""
    engine = Engine()

    # MAIN must export before sub-modules can import from it.
    engine._safe_build("(defmodule MAIN (export ?ALL))", context="module:MAIN")

    engine._safe_build("(deftemplate req (slot op (type STRING)))", context="req")
    engine._template_registry["req"] = TemplateDefinition(
        name="req",
        slots=[SlotDefinition(name="op", type=SlotType.STRING, required=True)],
    )
    engine._module_registry["m"] = ModuleDefinition(name="m", priority=100)
    engine._focus_order = ["m"]
    engine._evaluator._focus_order = ["m"]
    engine._safe_build("(defmodule m (import MAIN ?ALL))", context="m")

    rule = RuleDefinition(
        name="plain",
        when=[FactPattern(template="req", alias="$r", conditions=[])],
        then=ThenBlock(action=ActionType.ALLOW, reason="ok"),
    )
    engine._safe_build(engine._compiler.compile_rule(rule, "m"), context="rule:plain")

    engine.assert_fact("req", {"op": "read"})
    result = engine.evaluate()

    assert result.metadata == {}
