"""Unit tests for the LangChain integration adapter."""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fathom.integrations.langchain import (
    FathomAsyncCallbackHandler,
    FathomCallbackHandler,
    PolicyViolation,
    _build_tool_request_facts,
    _evaluate_tool_call,
    fathom_guard,
)  # noqa: I001

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


SERIALIZED_TOOL: dict[str, Any] = {"name": "web_search"}
INPUT_JSON = '{"query": "hello"}'
INPUT_PLAIN = "some plain text"
AGENT_ID = "agent-007"


# ---------------------------------------------------------------------------
# 1. _build_tool_request_facts
# ---------------------------------------------------------------------------


class TestBuildToolRequestFacts:
    """Tests for the shared fact-building helper."""

    def test_json_input_parsed(self) -> None:
        facts = _build_tool_request_facts(SERIALIZED_TOOL, INPUT_JSON, AGENT_ID)
        assert facts["tool_name"] == "web_search"
        assert facts["arguments"] == str({"query": "hello"})
        assert facts["agent_id"] == AGENT_ID

    def test_plain_text_fallback(self) -> None:
        facts = _build_tool_request_facts(SERIALIZED_TOOL, INPUT_PLAIN, AGENT_ID)
        assert facts["arguments"] == "some plain text"

    def test_missing_name_defaults_to_unknown(self) -> None:
        facts = _build_tool_request_facts({}, INPUT_JSON, AGENT_ID)
        assert facts["tool_name"] == "unknown"

    def test_none_input_str(self) -> None:
        facts = _build_tool_request_facts(SERIALIZED_TOOL, None, AGENT_ID)  # type: ignore[arg-type]
        assert facts["arguments"] == "None"


# ---------------------------------------------------------------------------
# 2. _evaluate_tool_call — shared evaluation logic
# ---------------------------------------------------------------------------


class TestEvaluateToolCall:
    """Tests for the shared evaluation helper."""

    def test_allow_does_not_raise(self) -> None:
        engine = _make_engine(decision="allow")
        _evaluate_tool_call(engine, AGENT_ID, SERIALIZED_TOOL, INPUT_JSON)
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_deny_raises_policy_violation(self) -> None:
        engine = _make_engine(
            decision="deny",
            reason="blocked by policy",
            rule_trace=["rule-1"],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            _evaluate_tool_call(engine, AGENT_ID, SERIALIZED_TOOL, INPUT_JSON)
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
            _evaluate_tool_call(engine, AGENT_ID, SERIALIZED_TOOL, INPUT_JSON)
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
# 4. FathomCallbackHandler (sync)
# ---------------------------------------------------------------------------


class TestSyncHandler:
    """Tests for the synchronous LangChain callback handler."""

    def test_on_tool_start_allow(self) -> None:
        engine = _make_engine(decision="allow")
        handler = FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)
        handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
        engine.assert_fact.assert_called_once()
        engine.evaluate.assert_called_once()

    def test_on_tool_start_deny_raises(self) -> None:
        engine = _make_engine(decision="deny", reason="forbidden", rule_trace=["deny-rule"])
        handler = FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)
        with pytest.raises(PolicyViolation) as exc_info:
            handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
        assert exc_info.value.decision == "deny"

    def test_on_tool_start_escalate_raises(self) -> None:
        engine = _make_engine(
            decision="escalate", reason="needs approval", rule_trace=["esc-rule"]
        )
        handler = FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)
        with pytest.raises(PolicyViolation) as exc_info:
            handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
        assert exc_info.value.decision == "escalate"
        assert exc_info.value.reason == "needs approval"

    def test_stores_attributes(self) -> None:
        engine = _make_engine()
        handler = FathomCallbackHandler(engine=engine, agent_id=AGENT_ID, session_id="sess-1")
        assert handler._engine is engine
        assert handler._agent_id == AGENT_ID
        assert handler._session_id == "sess-1"

    def test_fact_dict_passed_to_engine(self) -> None:
        engine = _make_engine(decision="allow")
        handler = FathomCallbackHandler(engine=engine, agent_id=AGENT_ID)
        handler.on_tool_start({"name": "calculator"}, '{"expr": "1+1"}')
        call_args = engine.assert_fact.call_args
        assert call_args[0][0] == "tool_request"
        fact = call_args[0][1]
        assert fact["tool_name"] == "calculator"
        assert fact["agent_id"] == AGENT_ID


# ---------------------------------------------------------------------------
# 5. FathomAsyncCallbackHandler
# ---------------------------------------------------------------------------


class TestAsyncHandler:
    """Tests for the asynchronous LangChain callback handler."""

    def test_on_tool_start_allow(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="allow")
            handler = FathomAsyncCallbackHandler(engine=engine, agent_id=AGENT_ID)
            await handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
            engine.assert_fact.assert_called_once()
            engine.evaluate.assert_called_once()

        asyncio.run(_run())

    def test_on_tool_start_deny_raises(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="deny", reason="blocked", rule_trace=["d1"])
            handler = FathomAsyncCallbackHandler(engine=engine, agent_id=AGENT_ID)
            with pytest.raises(PolicyViolation) as exc_info:
                await handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
            assert exc_info.value.decision == "deny"

        asyncio.run(_run())

    def test_on_tool_start_escalate_raises(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="escalate", reason="human review", rule_trace=["e1"])
            handler = FathomAsyncCallbackHandler(engine=engine, agent_id=AGENT_ID)
            with pytest.raises(PolicyViolation) as exc_info:
                await handler.on_tool_start(SERIALIZED_TOOL, INPUT_JSON)
            assert exc_info.value.decision == "escalate"

        asyncio.run(_run())

    def test_stores_attributes(self) -> None:
        engine = _make_engine()
        handler = FathomAsyncCallbackHandler(engine=engine, agent_id=AGENT_ID, session_id="sess-2")
        assert handler._engine is engine
        assert handler._agent_id == AGENT_ID
        assert handler._session_id == "sess-2"


# ---------------------------------------------------------------------------
# 6. fathom_guard LangGraph node
# ---------------------------------------------------------------------------


class TestFathomGuard:
    """Tests for the fathom_guard LangGraph node function."""

    def test_allow_decision(self) -> None:
        engine = _make_engine(decision="allow", reason="all clear")
        state: dict[str, Any] = {"tool_name": "web_search", "arguments": "q"}
        result = fathom_guard(state, engine, AGENT_ID)
        assert result == {"fathom_decision": "allow", "fathom_reason": "all clear"}

    def test_deny_decision(self) -> None:
        engine = _make_engine(decision="deny", reason="not allowed")
        state: dict[str, Any] = {"tool_name": "exec", "arguments": "rm -rf"}
        result = fathom_guard(state, engine, AGENT_ID)
        assert result == {"fathom_decision": "deny", "fathom_reason": "not allowed"}

    def test_escalate_decision(self) -> None:
        engine = _make_engine(decision="escalate", reason="review needed")
        state: dict[str, Any] = {"tool_name": "deploy"}
        result = fathom_guard(state, engine, AGENT_ID)
        assert result == {
            "fathom_decision": "escalate",
            "fathom_reason": "review needed",
        }

    def test_missing_tool_name_defaults_unknown(self) -> None:
        engine = _make_engine(decision="allow")
        result = fathom_guard({}, engine, AGENT_ID)
        call_args = engine.assert_fact.call_args
        assert call_args[0][1]["tool_name"] == "unknown"
        assert result["fathom_decision"] == "allow"

    def test_none_decision_defaults_allow(self) -> None:
        engine = _make_engine(decision=None)  # type: ignore[arg-type]
        result = fathom_guard({"tool_name": "t"}, engine, AGENT_ID)
        assert result["fathom_decision"] == "allow"

    def test_none_reason_defaults_empty_string(self) -> None:
        engine = _make_engine(decision="allow", reason=None)
        result = fathom_guard({"tool_name": "t"}, engine, AGENT_ID)
        assert result["fathom_reason"] == ""

    def test_asserts_correct_fact(self) -> None:
        engine = _make_engine(decision="allow")
        fathom_guard({"tool_name": "calc", "arguments": "1+1"}, engine, "a1")
        engine.assert_fact.assert_called_once_with(
            "tool_request",
            {"tool_name": "calc", "arguments": "1+1", "agent_id": "a1"},
        )


# ---------------------------------------------------------------------------
# 7. ImportError when langchain-core not installed
# ---------------------------------------------------------------------------


class TestImportGuard:
    """Test that missing langchain-core raises ImportError with message."""

    def test_import_error_when_langchain_core_missing(self) -> None:
        # Remove the module from cache so re-import triggers the guard
        mod_name = "fathom.integrations.langchain"
        saved_modules: dict[str, Any] = {}
        for key in list(sys.modules):
            if key == mod_name or key.startswith("langchain"):
                saved_modules[key] = sys.modules.pop(key)

        try:
            with (
                patch.dict(
                    sys.modules,
                    {"langchain_core": None, "langchain_core.callbacks": None},
                ),
                pytest.raises(ImportError, match="langchain-core is required"),
            ):
                importlib.import_module(mod_name)
        finally:
            # Restore original modules
            sys.modules.update(saved_modules)
