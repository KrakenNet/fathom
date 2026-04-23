"""Unit tests for the Google ADK integration adapter."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Mock the google.adk package before importing the adapter so the import guard
# does not raise when google-adk is not installed.
_google_mock = MagicMock()
sys.modules.setdefault("google", _google_mock)
sys.modules.setdefault("google.adk", _google_mock.adk)
sys.modules.setdefault("google.adk.agents", _google_mock.adk.agents)

from fathom.integrations.google_adk import (  # noqa: E402
    PolicyViolation,
    _build_tool_request_facts,
    _evaluate_tool_call,
    fathom_before_tool_callback,
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
ARGS_DICT: dict[str, Any] = {"query": "hello"}
ARGS_JSON = '{"query": "hello"}'
ARGS_PLAIN = "some plain text"
AGENT_ID = "agent-007"


def _make_tool(name: str = TOOL_NAME) -> SimpleNamespace:
    """Return a mock tool object with a .name attribute."""
    return SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# 1. _build_tool_request_facts
# ---------------------------------------------------------------------------


class TestBuildToolRequestFacts:
    """Tests for the shared fact-building helper."""

    def test_dict_input(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, ARGS_DICT, AGENT_ID)
        assert facts["tool_name"] == "web_search"
        assert facts["arguments"] == str({"query": "hello"})
        assert facts["agent_id"] == AGENT_ID

    def test_json_string_input_parsed(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, ARGS_JSON, AGENT_ID)
        assert facts["arguments"] == str({"query": "hello"})

    def test_plain_text_fallback(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, ARGS_PLAIN, AGENT_ID)
        assert facts["arguments"] == "some plain text"

    def test_tool_name_stored(self) -> None:
        facts = _build_tool_request_facts("calculator", ARGS_DICT, AGENT_ID)
        assert facts["tool_name"] == "calculator"

    def test_none_input(self) -> None:
        facts = _build_tool_request_facts(TOOL_NAME, None, AGENT_ID)  # type: ignore[arg-type]
        assert facts["arguments"] == "None"


# ---------------------------------------------------------------------------
# 2. _evaluate_tool_call — shared evaluation logic
# ---------------------------------------------------------------------------


class TestEvaluateToolCall:
    """Tests for the shared evaluation helper."""

    def test_allow_does_not_raise(self) -> None:
        engine = _make_engine(decision="allow")
        _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, ARGS_DICT)
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_deny_raises_policy_violation(self) -> None:
        engine = _make_engine(
            decision="deny",
            reason="blocked by policy",
            rule_trace=["rule-1"],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, ARGS_DICT)
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
            _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, ARGS_DICT)
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
# 4. fathom_before_tool_callback
# ---------------------------------------------------------------------------


class TestBeforeToolCallback:
    """Tests for the fathom_before_tool_callback factory function."""

    def test_allow_returns_none(self) -> None:
        engine = _make_engine(decision="allow")
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = _make_tool()
        result = callback(tool, ARGS_DICT, MagicMock())
        assert result is None
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_deny_returns_error_dict(self) -> None:
        engine = _make_engine(decision="deny", reason="forbidden", rule_trace=["deny-rule"])
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = _make_tool()
        result = callback(tool, ARGS_DICT, MagicMock())
        assert result is not None
        assert "error" in result
        assert "Policy violation" in result["error"]
        assert "forbidden" in result["error"]

    def test_escalate_returns_error_dict(self) -> None:
        engine = _make_engine(
            decision="escalate", reason="needs approval", rule_trace=["esc-rule"]
        )
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = _make_tool()
        result = callback(tool, ARGS_DICT, MagicMock())
        assert result is not None
        assert "error" in result
        assert "needs approval" in result["error"]

    def test_tool_name_extracted_from_tool_object(self) -> None:
        engine = _make_engine(decision="allow")
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = _make_tool("calculator")
        callback(tool, {"expr": "1+1"}, MagicMock())
        call_args = engine.assert_fact.call_args
        assert call_args[0][0] == "tool_request"
        fact = call_args[0][1]
        assert fact["tool_name"] == "calculator"
        assert fact["agent_id"] == AGENT_ID

    def test_tool_without_name_defaults_to_unknown(self) -> None:
        engine = _make_engine(decision="allow")
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = object()  # no .name attribute
        callback(tool, ARGS_DICT, MagicMock())
        call_args = engine.assert_fact.call_args
        fact = call_args[0][1]
        assert fact["tool_name"] == "unknown"

    def test_fact_dict_passed_to_engine(self) -> None:
        engine = _make_engine(decision="allow")
        callback = fathom_before_tool_callback(engine, AGENT_ID)
        tool = _make_tool("web_search")
        callback(tool, {"query": "test"}, MagicMock())
        call_args = engine.assert_fact.call_args
        assert call_args[0][0] == "tool_request"
        fact = call_args[0][1]
        assert fact["tool_name"] == "web_search"
        assert fact["agent_id"] == AGENT_ID


# ---------------------------------------------------------------------------
# 5. ImportError when google-adk not installed
# ---------------------------------------------------------------------------


class TestImportGuard:
    """Test that missing google-adk raises ImportError with message."""

    def test_import_error_when_google_adk_missing(self) -> None:
        # Remove the module from cache so re-import triggers the guard
        mod_name = "fathom.integrations.google_adk"
        saved_modules: dict[str, Any] = {}
        for key in list(sys.modules):
            if key == mod_name or key.startswith("google.adk") or key.startswith("google"):
                saved_modules[key] = sys.modules.pop(key)

        try:
            with (
                patch.dict(
                    sys.modules,
                    {"google.adk": None, "google.adk.agents": None, "google": None},
                ),
                pytest.raises(ImportError, match="google-adk is required"),
            ):
                importlib.import_module(mod_name)
        finally:
            # Restore original modules
            sys.modules.update(saved_modules)
