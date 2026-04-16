"""Unit tests for the CrewAI integration adapter."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock crewai before importing the adapter (crewai is not installed)
# ---------------------------------------------------------------------------

_mock_crewai = ModuleType("crewai")
sys.modules.setdefault("crewai", _mock_crewai)

from fathom.integrations.crewai import (  # noqa: E402
    PolicyViolation,
    _build_tool_request_facts,
    _evaluate_tool_call,
    fathom_before_tool_call,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(
    decision: str = "allow",
    reason: str | None = None,
    rule_trace: list[str] | None = None,
) -> MagicMock:
    """Return a mock Engine whose evaluate() returns a preset result."""
    engine = MagicMock(unsafe=True)
    result = SimpleNamespace(
        decision=decision,
        reason=reason,
        rule_trace=rule_trace or [],
    )
    engine.evaluate.return_value = result
    return engine


TOOL_NAME = "web_search"
INPUT_JSON = '{"query": "hello"}'
INPUT_PLAIN = "some plain text"
AGENT_ID = "agent-007"


# ---------------------------------------------------------------------------
# 1. _build_tool_request_facts
# ---------------------------------------------------------------------------


class TestBuildToolRequestFacts:
    """Tests for the shared fact-building helper."""

    def test_json_input_parsed(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, INPUT_JSON, AGENT_ID)
        assert facts["tool_name"] == "web_search"
        assert facts["arguments"] == str({"query": "hello"})
        assert facts["agent_id"] == AGENT_ID

    def test_plain_text_fallback(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, INPUT_PLAIN, AGENT_ID)
        assert facts["arguments"] == "some plain text"

    def test_missing_name_defaults_to_unknown(self) -> None:
        facts = _build_tool_request_facts("", INPUT_JSON, AGENT_ID)
        assert facts["tool_name"] == "unknown"

    def test_none_input_str(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, None, AGENT_ID)  # type: ignore[arg-type]
        assert facts["arguments"] == "None"


# ---------------------------------------------------------------------------
# 2. _evaluate_tool_call — shared evaluation logic
# ---------------------------------------------------------------------------


class TestEvaluateToolCall:
    """Tests for the shared evaluation helper."""

    def test_allow_does_not_raise(self) -> None:
        engine = _make_engine(decision="allow")
        _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, INPUT_JSON)
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_deny_raises_policy_violation(self) -> None:
        engine = _make_engine(
            decision="deny",
            reason="blocked by policy",
            rule_trace=["rule-1"],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, INPUT_JSON)
        assert exc_info.value.decision == "deny"
        assert exc_info.value.reason == "blocked by policy"
        assert exc_info.value.rule_trace == ["rule-1"]

    def test_escalate_raises_policy_violation(self) -> None:
        engine = _make_engine(
            decision="escalate",
            reason="needs human review",
            rule_trace=["rule-2", "rule-3"],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, INPUT_JSON)
        assert exc_info.value.decision == "escalate"
        assert exc_info.value.reason == "needs human review"


# ---------------------------------------------------------------------------
# 3. PolicyViolation exception
# ---------------------------------------------------------------------------


class TestPolicyViolation:
    """Tests for the PolicyViolation exception class."""

    def test_str_contains_decision_and_reason(self) -> None:
        exc = PolicyViolation(decision="deny", reason="not allowed", rule_trace=["r1"])
        assert "deny" in str(exc)
        assert "not allowed" in str(exc)

    def test_attributes_stored(self) -> None:
        exc = PolicyViolation(decision="escalate", reason="review", rule_trace=["r1", "r2"])
        assert exc.decision == "escalate"
        assert exc.reason == "review"
        assert exc.rule_trace == ["r1", "r2"]


# ---------------------------------------------------------------------------
# 4. fathom_before_tool_call hook
# ---------------------------------------------------------------------------


class TestBeforeToolCallHook:
    """Tests for the fathom_before_tool_call factory function."""

    def test_allow_passes_through(self) -> None:
        engine = _make_engine(decision="allow")
        hook = fathom_before_tool_call(engine=engine, agent_id=AGENT_ID)
        hook(TOOL_NAME, INPUT_JSON)
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_deny_raises(self) -> None:
        engine = _make_engine(decision="deny", reason="forbidden", rule_trace=["deny-rule"])
        hook = fathom_before_tool_call(engine=engine, agent_id=AGENT_ID)
        with pytest.raises(PolicyViolation) as exc_info:
            hook(TOOL_NAME, INPUT_JSON)
        assert exc_info.value.decision == "deny"

    def test_escalate_raises(self) -> None:
        engine = _make_engine(
            decision="escalate", reason="needs approval", rule_trace=["esc-rule"]
        )
        hook = fathom_before_tool_call(engine=engine, agent_id=AGENT_ID)
        with pytest.raises(PolicyViolation) as exc_info:
            hook(TOOL_NAME, INPUT_JSON)
        assert exc_info.value.decision == "escalate"
        assert exc_info.value.reason == "needs approval"

    def test_fact_dict_passed_to_engine(self) -> None:
        engine = _make_engine(decision="allow")
        hook = fathom_before_tool_call(engine=engine, agent_id=AGENT_ID)
        hook("calculator", '{"expr": "1+1"}')
        call_args = engine.assert_fact.call_args
        assert call_args[0][0] == "tool_request"
        fact = call_args[0][1]
        assert fact["tool_name"] == "calculator"
        assert fact["agent_id"] == AGENT_ID


# ---------------------------------------------------------------------------
# 5. ImportError when crewai not installed
# ---------------------------------------------------------------------------


class TestImportGuard:
    """Test that missing crewai raises ImportError with message."""

    def test_import_error_when_crewai_missing(self) -> None:
        # Remove the module from cache so re-import triggers the guard
        mod_name = "fathom.integrations.crewai"
        saved_modules: dict[str, Any] = {}
        for key in list(sys.modules):
            if key == mod_name or key.startswith("crewai"):
                saved_modules[key] = sys.modules.pop(key)

        try:
            with (
                patch.dict(
                    sys.modules,
                    {"crewai": None},
                ),
                pytest.raises(ImportError, match="crewai is required"),
            ):
                importlib.import_module(mod_name)
        finally:
            # Restore original modules
            sys.modules.update(saved_modules)
