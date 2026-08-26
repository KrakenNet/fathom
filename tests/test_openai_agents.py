"""Unit tests for the OpenAI Agents SDK integration adapter."""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from agents import Agent
from agents.tool_context import ToolContext
from agents.tool_guardrails import ToolInputGuardrail, ToolInputGuardrailData

# openai-agents is installed in CI (`uv sync --all-extras`), so the adapter
# imports the real package here. A MagicMock used to be planted instead, which
# is precisely how a guardrail signature the SDK never calls passed this suite.
# See tests/test_adapters_real_engine.py for the dispatch-level cover.
from fathom.integrations.openai_agents import (
    PolicyViolation,
    _build_tool_request_facts,
    _evaluate_tool_call,
    fathom_tool_guardrail,
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
    engine.evaluate_once.return_value = result
    return engine


TOOL_NAME = "web_search"
INPUT_JSON = '{"query": "hello"}'
INPUT_PLAIN = "some plain text"
AGENT_ID = "agent-007"


# ---------------------------------------------------------------------------
# 1. _build_tool_request_facts
# ---------------------------------------------------------------------------


def _scoped_fact(engine: MagicMock) -> tuple[str, dict]:
    """Return the single ``(template, slots)`` pair passed to ``evaluate_once``.

    Adapters go through :meth:`Engine.evaluate_once` so the request's fact is
    asserted, evaluated and withdrawn under one lock with refraction reset.
    """
    engine.evaluate_once.assert_called_once()
    facts = engine.evaluate_once.call_args[0][0]
    assert len(facts) == 1, facts
    return facts[0]


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
        facts = _build_tool_request_facts(TOOL_NAME, None, AGENT_ID)
        assert facts["arguments"] == "None"


# ---------------------------------------------------------------------------
# 2. _evaluate_tool_call -- shared evaluation logic
# ---------------------------------------------------------------------------


class TestEvaluateToolCall:
    """Tests for the shared evaluation helper."""

    def test_allow_does_not_raise(self) -> None:
        engine = _make_engine(decision="allow")
        _evaluate_tool_call(engine, AGENT_ID, TOOL_NAME, INPUT_JSON)
        engine.evaluate_once.assert_called_once()

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
# 4. fathom_tool_guardrail
# ---------------------------------------------------------------------------


def _data(tool_name: str = TOOL_NAME, arguments: str = INPUT_JSON) -> ToolInputGuardrailData:
    """Build the payload the Agents SDK runner hands a tool input guardrail."""
    return ToolInputGuardrailData(
        context=ToolContext(
            context=None,
            tool_name=tool_name,
            tool_call_id="call-1",
            tool_arguments=arguments,
        ),
        agent=Agent(name="unit-test-agent"),
    )


class TestFathomToolGuardrail:
    """Tests for the fathom_tool_guardrail factory function."""

    def test_factory_returns_a_tool_input_guardrail(self) -> None:
        """The SDK calls ``.run()`` on it; a bare callable is never invoked."""
        guardrail = fathom_tool_guardrail(engine=_make_engine(), agent_id=AGENT_ID)
        assert isinstance(guardrail, ToolInputGuardrail)

    def test_allow_passes(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="allow")
            guardrail = fathom_tool_guardrail(engine=engine, agent_id=AGENT_ID)
            outcome = await guardrail.run(_data())
            assert outcome.behavior["type"] == "allow"
            engine.evaluate_once.assert_called_once()

        asyncio.run(_run())

    def test_deny_raises_exception_behavior(self) -> None:
        """Blocking is a behavior on the return value, not a raise."""

        async def _run() -> None:
            engine = _make_engine(decision="deny", reason="forbidden", rule_trace=["deny-rule"])
            guardrail = fathom_tool_guardrail(engine=engine, agent_id=AGENT_ID)
            outcome = await guardrail.run(_data())
            assert outcome.behavior["type"] == "raise_exception"
            assert isinstance(outcome.output_info, PolicyViolation)
            assert outcome.output_info.decision == "deny"
            assert outcome.output_info.reason == "forbidden"

        asyncio.run(_run())

    def test_escalate_raises_exception_behavior(self) -> None:
        async def _run() -> None:
            engine = _make_engine(
                decision="escalate", reason="human review", rule_trace=["esc-rule"]
            )
            guardrail = fathom_tool_guardrail(engine=engine, agent_id=AGENT_ID)
            outcome = await guardrail.run(_data())
            assert outcome.behavior["type"] == "raise_exception"
            assert outcome.output_info.decision == "escalate"
            assert outcome.output_info.reason == "human review"

        asyncio.run(_run())

    def test_fact_dict_passed_to_engine(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="allow")
            guardrail = fathom_tool_guardrail(engine=engine, agent_id=AGENT_ID)
            await guardrail.run(_data(tool_name="calculator", arguments='{"expr": "1+1"}'))
            call_args = _scoped_fact(engine)
            assert call_args[0] == "tool_request"
            fact = call_args[1]
            assert fact["tool_name"] == "calculator"
            assert fact["agent_id"] == AGENT_ID

        asyncio.run(_run())

    def test_non_json_arguments_are_forwarded_verbatim(self) -> None:
        async def _run() -> None:
            engine = _make_engine(decision="allow")
            guardrail = fathom_tool_guardrail(engine=engine, agent_id=AGENT_ID)
            await guardrail.run(_data(arguments="not json"))
            assert _scoped_fact(engine)[1]["arguments"] == "not json"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. ImportError when openai-agents not installed
# ---------------------------------------------------------------------------


class TestImportGuard:
    """Test that missing openai-agents raises ImportError with message."""

    def test_import_error_when_agents_missing(self) -> None:
        # Remove the module from cache so re-import triggers the guard
        mod_name = "fathom.integrations.openai_agents"
        saved_modules: dict[str, Any] = {}
        for key in list(sys.modules):
            if key == mod_name or key.startswith("agents"):
                saved_modules[key] = sys.modules.pop(key)

        try:
            with (
                patch.dict(
                    sys.modules,
                    {"agents": None},
                ),
                pytest.raises(ImportError, match="openai-agents >= 0.4 is required"),
            ):
                importlib.import_module(mod_name)
        finally:
            # Restore original modules
            sys.modules.update(saved_modules)
