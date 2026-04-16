"""LangChain callback handler for Fathom policy enforcement.

Provides :class:`FathomCallbackHandler` which intercepts LangChain tool
calls, evaluates them against loaded Fathom rules, and raises
:class:`PolicyViolation` when a tool call is denied or escalated.

Requires ``langchain-core >= 0.2``.  Install via::

    pip install fathom-rules[langchain]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

try:
    from langchain_core.callbacks import (
        AsyncCallbackHandler,
        BaseCallbackHandler,
    )
except ImportError as _exc:
    raise ImportError(
        "langchain-core is required for the LangChain integration. "
        "Install it with: pip install fathom-rules[langchain]"
    ) from _exc

if TYPE_CHECKING:
    from fathom.engine import Engine


class PolicyViolation(Exception):  # noqa: N818 — name per design spec
    """Raised when Fathom denies or escalates a tool call.

    Attributes:
        decision: The evaluation decision (``"deny"`` or ``"escalate"``).
        reason: Human-readable reason from the matching rule.
        rule_trace: Ordered list of rules that fired during evaluation.
    """

    def __init__(
        self,
        decision: str,
        reason: str | None,
        rule_trace: list[str],
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.rule_trace = rule_trace
        super().__init__(f"Policy violation: {decision} — {reason}")


def _build_tool_request_facts(
    serialized: dict[str, Any],
    input_str: str,
    agent_id: str,
) -> dict[str, str]:
    """Build a ``tool_request`` fact dict from LangChain callback args.

    Extracts the tool name from *serialized*, parses *input_str* as JSON
    (falling back to plain text), and returns a dict suitable for
    :meth:`Engine.assert_fact`.

    Args:
        serialized: Serialized tool metadata from LangChain.
        input_str: Tool input arguments as a string.
        agent_id: Identifier for the calling agent.

    Returns:
        Fact dict with ``tool_name``, ``arguments``, and ``agent_id``.
    """
    tool_name = serialized.get("name", "unknown")

    # Parse arguments — input_str may be JSON or plain text
    try:
        arguments = json.loads(input_str)
    except (json.JSONDecodeError, TypeError):
        arguments = input_str

    return {
        "tool_name": str(tool_name),
        "arguments": str(arguments),
        "agent_id": agent_id,
    }


def _evaluate_tool_call(
    engine: Engine,
    agent_id: str,
    serialized: dict[str, Any],
    input_str: str,
) -> None:
    """Shared fact-mapping and evaluation logic for callback handlers.

    Uses :func:`_build_tool_request_facts` to construct the fact dict,
    asserts it into the engine, runs evaluation, and raises
    :class:`PolicyViolation` on ``deny`` or ``escalate``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        serialized: Serialized tool metadata from LangChain.
        input_str: Tool input arguments as a string.
    """
    facts = _build_tool_request_facts(serialized, input_str, agent_id)

    # Assert tool_request fact into working memory
    engine.assert_fact("tool_request", facts)

    # Evaluate rules
    result = engine.evaluate()

    # Raise on deny or escalate
    if result.decision in ("deny", "escalate"):
        raise PolicyViolation(
            decision=result.decision,
            reason=result.reason,
            rule_trace=result.rule_trace,
        )


class FathomCallbackHandler(BaseCallbackHandler):
    """Synchronous LangChain callback handler for Fathom policy enforcement.

    Intercepts ``on_tool_start`` events, asserts a ``tool_request`` fact
    into the Fathom engine, evaluates rules, and raises
    :class:`PolicyViolation` when the decision is ``deny`` or ``escalate``.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.
        session_id: Optional session identifier for stateful evaluation.
    """

    def __init__(
        self,
        engine: Engine,
        agent_id: str,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._agent_id = agent_id
        self._session_id = session_id

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Evaluate a tool call against Fathom policy rules.

        Extracts the tool name from the serialized dict and the input
        arguments, asserts a ``tool_request`` fact, and runs evaluation.
        Raises :class:`PolicyViolation` if the decision is ``deny`` or
        ``escalate``.

        Args:
            serialized: Serialized tool metadata from LangChain.
            input_str: Tool input arguments as a string.
            **kwargs: Additional keyword arguments from LangChain.
        """
        _evaluate_tool_call(
            self._engine,
            self._agent_id,
            serialized,
            input_str,
        )


class FathomAsyncCallbackHandler(AsyncCallbackHandler):
    """Asynchronous LangChain callback handler for Fathom policy enforcement.

    Provides the same fact-mapping and evaluation logic as
    :class:`FathomCallbackHandler` but implements the async
    ``on_tool_start`` interface for use with async LangChain chains.

    Args:
        engine: A configured :class:`~fathom.engine.Engine` instance with
            rules and templates loaded.
        agent_id: Identifier for the agent making tool calls.
        session_id: Optional session identifier for stateful evaluation.
    """

    def __init__(
        self,
        engine: Engine,
        agent_id: str,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._agent_id = agent_id
        self._session_id = session_id

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Evaluate a tool call against Fathom policy rules (async).

        Shares the same fact-mapping and evaluation logic as the
        synchronous handler.  The underlying CLIPS engine is synchronous,
        so this delegates to the shared helper directly.

        Args:
            serialized: Serialized tool metadata from LangChain.
            input_str: Tool input arguments as a string.
            **kwargs: Additional keyword arguments from LangChain.
        """
        _evaluate_tool_call(
            self._engine,
            self._agent_id,
            serialized,
            input_str,
        )


def fathom_guard(
    state: dict[str, Any],
    engine: Engine,
    agent_id: str,
) -> dict[str, str]:
    """LangGraph node that evaluates Fathom policy rules.

    Designed to be used as a node in a LangGraph graph for conditional
    routing based on policy evaluation.  Asserts the current state as a
    ``tool_request`` fact and returns the evaluation result for
    downstream routing decisions.

    Args:
        state: LangGraph graph state dictionary.  Expected to contain
            ``"tool_name"`` and optionally ``"arguments"``.
        engine: A configured :class:`~fathom.engine.Engine` instance.
        agent_id: Identifier for the agent being evaluated.

    Returns:
        A dictionary with ``"fathom_decision"`` (e.g. ``"allow"``,
        ``"deny"``, ``"escalate"``) and ``"fathom_reason"`` (human-readable
        explanation or empty string).
    """
    tool_name = state.get("tool_name", "unknown")
    arguments = state.get("arguments", "")

    engine.assert_fact(
        "tool_request",
        {
            "tool_name": str(tool_name),
            "arguments": str(arguments),
            "agent_id": agent_id,
        },
    )

    result = engine.evaluate()

    return {
        "fathom_decision": result.decision or "allow",
        "fathom_reason": result.reason or "",
    }
