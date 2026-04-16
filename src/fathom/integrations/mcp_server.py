"""Fathom MCP tool server — exposes Engine operations as MCP tools."""

from __future__ import annotations

from typing import Any

from fathom.engine import Engine


class FathomMCPServer:
    """MCP tool server with per-connection Engine isolation.

    Wraps a :class:`~mcp.server.fastmcp.FastMCP` instance and registers
    four tools: ``fathom.evaluate``, ``fathom.assert_fact``,
    ``fathom.query``, and ``fathom.retract``.

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
        """Return the per-connection Engine, creating it lazily."""
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
            transport: Transport protocol. Defaults to ``"stdio"``.
        """
        self._mcp.run(transport=transport)


def _create_mcp_app(server: FathomMCPServer) -> Any:
    """Create a FastMCP app and register Fathom tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("fathom")

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
