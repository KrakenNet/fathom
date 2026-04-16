"""MCP tool server tests — verifies FathomMCPServer tool methods."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fathom.errors import ValidationError
from fathom.integrations.mcp_server import FathomMCPServer

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


# ---------------------------------------------------------------------------
# 1. Tool registration
# ---------------------------------------------------------------------------


class TestMCPToolRegistration:
    """Verify the MCP app is created with expected tools."""

    def test_mcp_app_exists(self) -> None:
        server = FathomMCPServer()
        assert server._mcp is not None

    def test_mcp_app_created_without_rules(self) -> None:
        server = FathomMCPServer()
        assert server._rules_path is None
        assert server._mcp is not None

    def test_mcp_app_created_with_rules(self) -> None:
        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        assert server._rules_path == FIXTURES_DIR
        assert server._mcp is not None

    def test_engine_not_created_eagerly(self) -> None:
        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        assert server._engine is None


# ---------------------------------------------------------------------------
# 2. Evaluate tool
# ---------------------------------------------------------------------------


class TestMCPEvaluate:
    """Test fathom.evaluate tool via FathomMCPServer.evaluate()."""

    @pytest.fixture
    def server(self) -> FathomMCPServer:
        return FathomMCPServer(rules_path=FIXTURES_DIR)

    def test_evaluate_returns_dict(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert isinstance(result, dict)

    def test_evaluate_has_decision_key(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert "decision" in result

    def test_evaluate_has_duration_us(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert "duration_us" in result
        assert isinstance(result["duration_us"], int)

    def test_evaluate_has_reason(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert "reason" in result

    def test_evaluate_has_rule_trace(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert "rule_trace" in result
        assert isinstance(result["rule_trace"], list)

    def test_evaluate_has_module_trace(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        result = server.evaluate()
        assert "module_trace" in result
        assert isinstance(result["module_trace"], list)

    def test_evaluate_default_deny_no_facts(self, server: FathomMCPServer) -> None:
        result = server.evaluate()
        assert result["decision"] == "deny"

    def test_evaluate_creates_engine_lazily(self) -> None:
        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        assert server._engine is None
        server.evaluate()
        assert server._engine is not None


# ---------------------------------------------------------------------------
# 3. Assert fact tool
# ---------------------------------------------------------------------------


class TestMCPAssertFact:
    """Test fathom.assert_fact tool via FathomMCPServer.assert_fact()."""

    @pytest.fixture
    def server(self) -> FathomMCPServer:
        return FathomMCPServer(rules_path=FIXTURES_DIR)

    def test_assert_fact_returns_ok(self, server: FathomMCPServer) -> None:
        result = server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert result == {"status": "ok"}

    def test_assert_fact_returns_dict(self, server: FathomMCPServer) -> None:
        result = server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert isinstance(result, dict)
        assert "status" in result

    def test_assert_fact_makes_fact_queryable(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        facts = server.query("agent")
        assert len(facts) == 1

    def test_assert_multiple_facts(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        facts = server.query("agent")
        assert len(facts) == 2

    def test_assert_fact_invalid_template_raises(self, server: FathomMCPServer) -> None:
        with pytest.raises(ValidationError):
            server.assert_fact("nonexistent_template", {"id": "a1"})


# ---------------------------------------------------------------------------
# 4. Query tool
# ---------------------------------------------------------------------------


class TestMCPQuery:
    """Test fathom.query tool via FathomMCPServer.query()."""

    @pytest.fixture
    def server(self) -> FathomMCPServer:
        return FathomMCPServer(rules_path=FIXTURES_DIR)

    def test_query_empty_returns_empty_list(self, server: FathomMCPServer) -> None:
        result = server.query("agent")
        assert result == []

    def test_query_returns_list(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        result = server.query("agent")
        assert isinstance(result, list)

    def test_query_returns_matching_facts(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        facts = server.query("agent")
        assert len(facts) == 1
        assert facts[0]["id"] == "a1"

    def test_query_with_filter(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        facts = server.query("agent", {"clearance": "secret"})
        assert len(facts) == 1
        assert facts[0]["id"] == "a1"

    def test_query_filter_no_match(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        facts = server.query("agent", {"clearance": "top-secret"})
        assert facts == []

    def test_query_different_templates(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        agents = server.query("agent")
        requests = server.query("data_request")
        assert len(agents) == 1
        assert len(requests) == 1


# ---------------------------------------------------------------------------
# 5. Retract tool
# ---------------------------------------------------------------------------


class TestMCPRetract:
    """Test fathom.retract tool via FathomMCPServer.retract()."""

    @pytest.fixture
    def server(self) -> FathomMCPServer:
        return FathomMCPServer(rules_path=FIXTURES_DIR)

    def test_retract_returns_count(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        result = server.retract("agent")
        assert result == {"retracted": 1}

    def test_retract_returns_dict(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        result = server.retract("agent")
        assert isinstance(result, dict)
        assert "retracted" in result

    def test_retract_removes_facts(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.retract("agent")
        facts = server.query("agent")
        assert facts == []

    def test_retract_multiple_facts(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        result = server.retract("agent")
        assert result == {"retracted": 2}

    def test_retract_with_filter(self, server: FathomMCPServer) -> None:
        server.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        server.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        result = server.retract("agent", {"clearance": "secret"})
        assert result == {"retracted": 1}
        remaining = server.query("agent")
        assert len(remaining) == 1
        assert remaining[0]["id"] == "a2"

    def test_retract_zero_when_empty(self, server: FathomMCPServer) -> None:
        result = server.retract("agent")
        assert result == {"retracted": 0}


# ---------------------------------------------------------------------------
# 6. Per-connection engine isolation
# ---------------------------------------------------------------------------


class TestMCPIsolation:
    """Verify separate FathomMCPServer instances have independent engines."""

    def test_separate_servers_independent(self) -> None:
        s1 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s2 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s1.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        assert s2.query("agent") == []

    def test_separate_servers_evaluate_independently(self) -> None:
        s1 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s2 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s1.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        s1.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        r1 = s1.evaluate()
        r2 = s2.evaluate()
        # s1 has facts and rules; s2 has only rules (default deny)
        assert r1["decision"] is not None
        assert r2["decision"] == "deny"

    def test_retract_on_one_does_not_affect_other(self) -> None:
        s1 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s2 = FathomMCPServer(rules_path=FIXTURES_DIR)
        s1.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        s2.assert_fact("agent", {"id": "a2", "clearance": "top-secret"})
        s1.retract("agent")
        assert s1.query("agent") == []
        assert len(s2.query("agent")) == 1


# ---------------------------------------------------------------------------
# 7. Audit log parity with SDK
# ---------------------------------------------------------------------------


class TestMCPAuditParity:
    """MCP evaluations produce same audit structure as SDK Engine."""

    def test_mcp_evaluate_result_keys_match_sdk(self) -> None:
        """MCP evaluate returns same top-level keys as EvaluationResult."""
        from fathom.engine import Engine

        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        sdk_engine = Engine.from_rules(FIXTURES_DIR)

        # MCP result
        mcp_result = server.evaluate()

        # SDK result
        sdk_result = sdk_engine.evaluate()

        expected_keys = {"decision", "reason", "rule_trace", "module_trace", "duration_us"}
        assert expected_keys == set(mcp_result.keys())
        # SDK EvaluationResult has the same fields (plus extras)
        for key in expected_keys:
            assert hasattr(sdk_result, key)

    def test_audit_record_keys_from_file_sink(self, tmp_path: Path) -> None:
        """Verify audit records from SDK have expected keys."""
        from fathom.audit import FileSink
        from fathom.engine import Engine

        audit_file = tmp_path / "audit.jsonl"
        engine = Engine.from_rules(FIXTURES_DIR, audit_sink=FileSink(str(audit_file)))
        engine.assert_fact("agent", {"id": "a1", "clearance": "secret"})
        engine.assert_fact(
            "data_request",
            {"agent_id": "a1", "classification": "cui", "resource": "doc"},
        )
        engine.evaluate()

        record = json.loads(audit_file.read_text().strip())
        expected_keys = {
            "timestamp",
            "session_id",
            "decision",
            "reason",
            "duration_us",
            "modules_traversed",
            "rules_fired",
        }
        assert expected_keys.issubset(set(record.keys()))

    def test_mcp_decision_matches_sdk_decision(self) -> None:
        """Same facts + rules produce same decision via MCP and SDK."""
        from fathom.engine import Engine

        facts = [
            ("agent", {"id": "a1", "clearance": "secret"}),
            (
                "data_request",
                {"agent_id": "a1", "classification": "cui", "resource": "doc"},
            ),
        ]

        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        sdk_engine = Engine.from_rules(FIXTURES_DIR)

        for tmpl, data in facts:
            server.assert_fact(tmpl, data)
            sdk_engine.assert_fact(tmpl, data)

        mcp_result = server.evaluate()
        sdk_result = sdk_engine.evaluate()

        assert mcp_result["decision"] == sdk_result.decision
        assert mcp_result["reason"] == sdk_result.reason

    def test_mcp_rule_trace_matches_sdk(self) -> None:
        """Same scenario produces same rule_trace via MCP and SDK."""
        from fathom.engine import Engine

        facts = [
            ("agent", {"id": "a1", "clearance": "secret"}),
            (
                "data_request",
                {"agent_id": "a1", "classification": "cui", "resource": "doc"},
            ),
        ]

        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        sdk_engine = Engine.from_rules(FIXTURES_DIR)

        for tmpl, data in facts:
            server.assert_fact(tmpl, data)
            sdk_engine.assert_fact(tmpl, data)

        mcp_result = server.evaluate()
        sdk_result = sdk_engine.evaluate()

        assert mcp_result["rule_trace"] == sdk_result.rule_trace

    def test_mcp_module_trace_matches_sdk(self) -> None:
        """Same scenario produces same module_trace via MCP and SDK."""
        from fathom.engine import Engine

        facts = [
            ("agent", {"id": "a1", "clearance": "secret"}),
            (
                "data_request",
                {"agent_id": "a1", "classification": "cui", "resource": "doc"},
            ),
        ]

        server = FathomMCPServer(rules_path=FIXTURES_DIR)
        sdk_engine = Engine.from_rules(FIXTURES_DIR)

        for tmpl, data in facts:
            server.assert_fact(tmpl, data)
            sdk_engine.assert_fact(tmpl, data)

        mcp_result = server.evaluate()
        sdk_result = sdk_engine.evaluate()

        assert mcp_result["module_trace"] == sdk_result.module_trace
