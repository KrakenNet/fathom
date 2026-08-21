"""LangChain callback handler for Fathom policy enforcement.

Provides :class:`FathomCallbackHandler` which intercepts LangChain tool
calls, evaluates them against loaded Fathom rules, and raises
:class:`PolicyViolation` unless the decision is ``allow``.

Requires ``langchain-core >= 0.2``.  Install via::

    pip install fathom-rules[langchain]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

# Re-exported: `from fathom.integrations.<adapter> import PolicyViolation`
# was the only import path before this class was shared.
from fathom.integrations import PolicyViolation as PolicyViolation

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
    asserts it into the engine, runs evaluation, retracts the fact, and
    raises :class:`PolicyViolation` unless the decision is ``allow``.

    Args:
        engine: Configured Fathom engine.
        agent_id: Identifier for the calling agent.
        serialized: Serialized tool metadata from LangChain.
        input_str: Tool input arguments as a string.
    """
    facts = _build_tool_request_facts(serialized, input_str, agent_id)

    # Assert tool_request fact into working memory
    # Request-scoped: assert, run, retract — all under one engine lock, with
    # CLIPS refraction reset afterwards.
    #
    # The hand-rolled assert/evaluate/retract this replaces had three holes.
    # (1) Retraction alone does not clear refraction, so a rule that matched
    # only long-lived facts (an `agent` fact, say) fired on call 1 and stayed
    # refracted for calls 2..N — a deny rule silently stopped denying, which
    # is a fail-open. (2) Taking the lock three separate times let a second
    # thread retract the (de-duplicated) fact before the first thread
    # evaluated, permitting hard-denied tools under concurrency. (3) The
    # retract-by-value matched a caller-owned identical fact and deleted it.
    # `evaluate_once` closes all three.
    result = engine.evaluate_once([("tool_request", facts)])

    # Fail closed: only an explicit allow permits the call
    if result.decision != "allow":
        raise PolicyViolation(
            decision=result.decision,
            reason=result.reason,
            rule_trace=result.rule_trace,
        )


class FathomCallbackHandler(BaseCallbackHandler):
    """Synchronous LangChain callback handler for Fathom policy enforcement.

    Intercepts ``on_tool_start`` events, asserts a ``tool_request`` fact
    into the Fathom engine, evaluates rules, retracts the fact, and raises
    :class:`PolicyViolation` unless the decision is ``allow``.

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
        Raises :class:`PolicyViolation` unless the decision is ``allow``.

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
        explanation or empty string).  When evaluation yields no decision
        the node fails closed and reports ``"deny"``.
    """
    tool_name = state.get("tool_name", "unknown")
    arguments = state.get("arguments", "")

    facts = {
        "tool_name": str(tool_name),
        "arguments": str(arguments),
        "agent_id": agent_id,
    }

    # Request-scoped: assert, run, retract — all under one engine lock, with
    # CLIPS refraction reset afterwards.
    #
    # The hand-rolled assert/evaluate/retract this replaces had three holes.
    # (1) Retraction alone does not clear refraction, so a rule that matched
    # only long-lived facts (an `agent` fact, say) fired on call 1 and stayed
    # refracted for calls 2..N — a deny rule silently stopped denying, which
    # is a fail-open. (2) Taking the lock three separate times let a second
    # thread retract the (de-duplicated) fact before the first thread
    # evaluated, permitting hard-denied tools under concurrency. (3) The
    # retract-by-value matched a caller-owned identical fact and deleted it.
    # `evaluate_once` closes all three.
    result = engine.evaluate_once([("tool_request", facts)])

    return {
        # Fail closed: never manufacture a permit out of a missing decision
        "fathom_decision": result.decision or "deny",
        "fathom_reason": result.reason or "",
    }
