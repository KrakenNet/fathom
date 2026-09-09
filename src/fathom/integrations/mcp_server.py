"""Fathom MCP tool server — exposes Engine operations as MCP tools."""

from __future__ import annotations

import importlib
from typing import Any

from fathom.engine import Engine


class FathomMCPServer:
    """MCP tool server backed by a single process-wide Engine.

    Wraps a :class:`~mcp.server.fastmcp.FastMCP` instance and registers
    four tools: ``fathom.evaluate``, ``fathom.assert_fact``,
    ``fathom.query``, and ``fathom.retract``.

    There is **no** per-connection isolation and **no** authentication on
    the tools: every caller shares one Engine and can read, inject, or
    retract another caller's working memory. That is safe under the stdio
    transport, which runs one server process per client, and only under
    stdio — :meth:`run` therefore refuses the network transports.

    Args:
        rules_path: Optional path to a rules directory or file.
            When provided, :meth:`Engine.from_rules` is used to
            bootstrap the engine on first access.
    """

    def __init__(self, rules_path: str | None = None) -> None:
        self._rules_path = rules_path
        self._engine: Engine | None = None
        self._mcp = _create_mcp_app(self)

    def _get_engine(self) -> Engine:
        """Return the process-wide Engine, creating it lazily."""
        if self._engine is None:
            if self._rules_path:
                self._engine = Engine.from_rules(self._rules_path)
            else:
                self._engine = Engine()
        return self._engine

    # -- Tool methods (also registered as MCP tools) -----------------------

    def evaluate(self) -> dict[str, Any]:
        """Run forward-chain evaluation and return the decision."""
        result = self._get_engine().evaluate()
        return {
            "decision": result.decision,
            "reason": result.reason,
            "rule_trace": result.rule_trace,
            "module_trace": result.module_trace,
            "duration_us": result.duration_us,
        }

    def assert_fact(self, template: str, data: dict[str, Any]) -> dict[str, str]:
        """Assert a fact into working memory."""
        self._get_engine().assert_fact(template, data)
        return {"status": "ok"}

    def query(
        self, template: str, fact_filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Query working memory for facts matching a template."""
        return self._get_engine().query(template, fact_filter)

    def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> dict[str, int]:
        """Retract facts from working memory."""
        count = self._get_engine().retract(template, fact_filter)
        return {"retracted": count}

    def run(self, transport: str = "stdio") -> None:
        """Start the MCP server (blocking).

        Args:
            transport: Transport protocol. Only ``"stdio"`` is supported.

        Raises:
            ValueError: A network transport was requested. The tools are
                unauthenticated and share one Engine, so serving several
                clients over ``sse`` / ``streamable-http`` would let any
                caller read and retract another's working memory.
        """
        if transport != "stdio":
            raise ValueError(
                f"unsupported MCP transport {transport!r}: the Fathom MCP tools are "
                "unauthenticated and share a single Engine, so only 'stdio' "
                "(one server process per client) is supported"
            )
        self._mcp.run(transport=transport)


def _mcp_server_class() -> Any:
    """Return the server class for whichever MCP SDK major version is installed.

    mcp 2.0 renamed ``FastMCP`` to ``MCPServer`` and moved it from
    ``mcp.server.fastmcp`` to ``mcp.server.mcpserver``. Importing the old path
    unconditionally broke every MCP tool under 2.x, even though the dependency
    range allows it.

    Only the name and location changed for what this module uses. The ``tool``
    decorator and ``run(transport=...)`` keep their signatures, and the tool
    manager still answers ``_tool_manager.list_tools()``, which is what the
    manifest script reads. So one lookup covers both majors, newest first.

    Resolved through :func:`importlib.import_module` rather than two ``import``
    statements on purpose: under 2.x the old module still exists as a stub that
    raises on import, so a static ``from mcp.server.fastmcp import FastMCP``
    fails type checking on 2.x and a plain module-missing check does not
    describe the situation on either version.
    """
    candidates = (("mcp.server.mcpserver", "MCPServer"), ("mcp.server.fastmcp", "FastMCP"))
    for module_name, attribute in candidates:
        try:
            return getattr(importlib.import_module(module_name), attribute)
        except (ImportError, AttributeError):
            continue
    raise ImportError(
        "no supported MCP server class found: install the 'mcp' extra "
        "(pip install 'fathom-rules[mcp]'). Looked for "
        + " and ".join(f"{module}.{attribute}" for module, attribute in candidates)
    )


def _create_mcp_app(server: FathomMCPServer) -> Any:
    """Create the MCP app and register Fathom tools."""
    mcp = _mcp_server_class()("fathom")

    @mcp.tool(name="fathom.evaluate", description="Run forward-chain evaluation")
    def tool_evaluate() -> dict[str, Any]:
        return server.evaluate()

    @mcp.tool(name="fathom.assert_fact", description="Assert a fact into working memory")
    def tool_assert_fact(template: str, data: dict[str, Any]) -> dict[str, str]:
        return server.assert_fact(template, data)

    @mcp.tool(name="fathom.query", description="Query working memory")
    def tool_query(
        template: str, fact_filter: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return server.query(template, fact_filter)

    @mcp.tool(name="fathom.retract", description="Retract facts from working memory")
    def tool_retract(template: str, fact_filter: dict[str, Any] | None = None) -> dict[str, int]:
        return server.retract(template, fact_filter)

    return mcp
