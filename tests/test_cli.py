"""Unit tests for the Fathom CLI commands.

Tests all 6 subcommands: validate, compile, info, test, bench, repl.
Uses typer.testing.CliRunner for subprocess-free invocation.

Some commands (info, test, bench) use Engine.from_rules which hits pre-existing
CLIPS engine bugs (deftemplate redefinition on reset, missing rule.salience).
Those tests mock Engine.from_rules to isolate CLI logic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from typer.testing import CliRunner

from fathom.cli import app
from fathom.models import EvaluationResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, data: dict | list | str, name: str = "data.yaml") -> Path:
    """Write YAML content to a temp file."""
    text = yaml.safe_dump(data) if not isinstance(data, str) else data
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _make_rule_pack(tmp_path: Path) -> Path:
    """Create a minimal valid rule pack directory structure."""
    pack = tmp_path / "pack"
    (pack / "templates").mkdir(parents=True)
    (pack / "modules").mkdir(parents=True)
    (pack / "rules").mkdir(parents=True)

    templates = {
        "templates": [
            {
                "name": "request",
                "slots": [
                    {"name": "action", "type": "symbol"},
                    {"name": "user", "type": "symbol"},
                ],
            }
        ]
    }
    (pack / "templates" / "request.yaml").write_text(yaml.safe_dump(templates), encoding="utf-8")

    modules = {
        "modules": [
            {"name": "governance", "description": "Test governance module"},
        ],
        "focus_order": ["governance"],
    }
    (pack / "modules" / "modules.yaml").write_text(yaml.safe_dump(modules), encoding="utf-8")

    rules = {
        "module": "governance",
        "rules": [
            {
                "name": "allow-read",
                "salience": 10,
                "when": [
                    {
                        "template": "request",
                        "conditions": [
                            {"slot": "action", "expression": "equals(read)"},
                        ],
                    },
                ],
                "then": {"action": "allow", "reason": "read allowed"},
            }
        ],
    }
    (pack / "rules" / "access.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    return pack


def _mock_engine(**overrides):
    """Create a mock Engine for CLI testing.

    Avoids CLIPS environment issues (template redefinition, missing attrs).
    """
    engine = MagicMock(unsafe=True)
    _templates = overrides.get(
        "templates",
        {
            "request": SimpleNamespace(
                name="request",
                slots=[
                    SimpleNamespace(name="action", type=SimpleNamespace(value="symbol")),
                    SimpleNamespace(name="user", type=SimpleNamespace(value="symbol")),
                ],
            ),
        },
    )
    _modules = overrides.get(
        "modules",
        {
            "governance": SimpleNamespace(name="governance", priority=0),
        },
    )
    _focus = overrides.get("focus_order", ["governance"])
    _rules_reg = overrides.get(
        "rule_registry",
        {
            "allow-read": SimpleNamespace(name="allow-read", salience=10),
        },
    )

    engine._template_registry = _templates
    engine._module_registry = _modules
    engine._focus_order = _focus

    # Public property aliases (used by cli.info after M2 refactor)
    engine.template_registry = _templates
    engine.module_registry = _modules
    engine.focus_order = _focus
    engine.rule_registry = _rules_reg

    # Mock CLIPS rules with name, module, and salience attributes
    mock_rule = SimpleNamespace(
        name="allow-read",
        module=SimpleNamespace(name="governance"),
        salience=10,
    )
    mock_env = MagicMock()
    mock_env.rules.return_value = overrides.get("rules", [mock_rule])
    mock_env.functions.return_value = overrides.get("functions", [])
    mock_env.facts.return_value = []
    engine._env = mock_env

    # Default evaluate returns a deny decision (no rules fired)
    engine.evaluate.return_value = overrides.get(
        "eval_result",
        EvaluationResult(decision="deny", reason="default deny"),
    )

    return engine


# ===========================================================================
# --version
# ===========================================================================


class TestVersion:
    """Tests for the --version flag."""

    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "fathom" in result.output

    def test_version_short_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert "fathom" in result.output


# ===========================================================================
# validate
# ===========================================================================


class TestValidate:
    """Tests for the validate command."""

    def test_validate_valid_yaml(self, tmp_path: Path) -> None:
        data = {
            "templates": [
                {
                    "name": "agent",
                    "slots": [
                        {"name": "id", "type": "string", "required": True},
                    ],
                }
            ]
        }
        path = _write_yaml(tmp_path, data, "templates.yaml")
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 0
        assert "Validation passed" in result.output

    def test_validate_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        bad_yaml = "key: [unclosed bracket"
        path = _write_yaml(tmp_path, bad_yaml, "bad.yaml")
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code != 0

    def test_validate_nonexistent_path(self) -> None:
        result = runner.invoke(app, ["validate", "/nonexistent/path/file.yaml"])
        assert result.exit_code != 0

    def test_validate_directory_with_no_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not yaml", encoding="utf-8")
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code != 0

    def test_validate_directory_with_valid_files(self, tmp_path: Path) -> None:
        data = {
            "templates": [
                {
                    "name": "item",
                    "slots": [{"name": "id", "type": "string"}],
                }
            ]
        }
        _write_yaml(tmp_path, data, "templates.yaml")
        result = runner.invoke(app, ["validate", str(tmp_path)])
        assert result.exit_code == 0
        assert "Validation passed" in result.output


# ===========================================================================
# compile
# ===========================================================================


class TestCompile:
    """Tests for the compile command."""

    def test_compile_valid_template(self, tmp_path: Path) -> None:
        data = {
            "templates": [
                {
                    "name": "request",
                    "slots": [
                        {"name": "type", "type": "string"},
                        {"name": "user", "type": "string"},
                    ],
                }
            ]
        }
        path = _write_yaml(tmp_path, data, "templates.yaml")
        result = runner.invoke(app, ["compile", str(path)])
        assert result.exit_code == 0
        assert "deftemplate" in result.output
        assert "request" in result.output

    def test_compile_invalid_input(self, tmp_path: Path) -> None:
        bad_yaml = "key: [unclosed"
        path = _write_yaml(tmp_path, bad_yaml, "bad.yaml")
        result = runner.invoke(app, ["compile", str(path)])
        assert result.exit_code != 0

    def test_compile_no_yaml_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("nothing", encoding="utf-8")
        result = runner.invoke(app, ["compile", str(tmp_path)])
        assert result.exit_code != 0

    def test_compile_pretty_format(self, tmp_path: Path) -> None:
        data = {
            "templates": [
                {
                    "name": "item",
                    "slots": [{"name": "id", "type": "string"}],
                }
            ]
        }
        path = _write_yaml(tmp_path, data, "templates.yaml")
        result = runner.invoke(app, ["compile", "--format", "pretty", str(path)])
        assert result.exit_code == 0
        assert "deftemplate" in result.output

    def test_compile_rules(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        result = runner.invoke(app, ["compile", str(pack / "templates")])
        assert result.exit_code == 0
        assert "deftemplate" in result.output


# ===========================================================================
# info
# ===========================================================================


class TestInfo:
    """Tests for the info command."""

    def test_info_shows_constructs(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["info", str(pack)])
        assert result.exit_code == 0
        assert "Templates" in result.output
        assert "Modules" in result.output
        assert "Rules" in result.output
        assert "Functions" in result.output

    def test_info_shows_template_names(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["info", str(pack)])
        assert result.exit_code == 0
        assert "request" in result.output

    def test_info_shows_module_priority(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["info", str(pack)])
        assert result.exit_code == 0
        assert "governance" in result.output
        assert "priority=" in result.output

    def test_info_nonexistent_path(self) -> None:
        result = runner.invoke(app, ["info", "/nonexistent/path"])
        assert result.exit_code != 0


# ===========================================================================
# test
# ===========================================================================


class TestTestCommand:
    """Tests for the test command."""

    def test_passing_test(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        test_cases = [
            {
                "name": "read-allowed",
                "facts": [
                    {"template": "request", "data": {"action": "read", "user": "alice"}},
                ],
                "expected_decision": "allow",
            }
        ]
        test_file = _write_yaml(tmp_path, test_cases, "tests.yaml")

        mock_eng = _mock_engine(
            eval_result=EvaluationResult(decision="allow", reason="read allowed"),
        )
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["test", str(pack), str(test_file)])
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "read-allowed" in result.output

    def test_failing_test(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        test_cases = [
            {
                "name": "expect-deny-but-allow",
                "facts": [
                    {"template": "request", "data": {"action": "read", "user": "bob"}},
                ],
                "expected_decision": "deny",
            }
        ]
        test_file = _write_yaml(tmp_path, test_cases, "tests.yaml")

        mock_eng = _mock_engine(
            eval_result=EvaluationResult(decision="allow", reason="read allowed"),
        )
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["test", str(pack), str(test_file)])
        assert result.exit_code != 0
        assert "FAIL" in result.output

    def test_no_test_files(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        empty_dir = tmp_path / "empty_tests"
        empty_dir.mkdir()
        (empty_dir / "readme.txt").write_text("not yaml", encoding="utf-8")
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["test", str(pack), str(empty_dir)])
        assert result.exit_code != 0

    def test_missing_rules_path(self) -> None:
        result = runner.invoke(app, ["test", "/nonexistent", "/also-nonexistent"])
        assert result.exit_code != 0

    def test_multiple_cases_mixed(self, tmp_path: Path) -> None:
        """Test with multiple cases where some pass and some fail."""
        pack = _make_rule_pack(tmp_path)
        test_cases = [
            {
                "name": "case-pass",
                "facts": [
                    {"template": "request", "data": {"action": "read", "user": "a"}},
                ],
                "expected_decision": "allow",
            },
            {
                "name": "case-fail",
                "facts": [
                    {"template": "request", "data": {"action": "read", "user": "b"}},
                ],
                "expected_decision": "deny",
            },
        ]
        test_file = _write_yaml(tmp_path, test_cases, "tests.yaml")

        mock_eng = _mock_engine(
            eval_result=EvaluationResult(decision="allow", reason="read allowed"),
        )
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(app, ["test", str(pack), str(test_file)])
        assert result.exit_code != 0
        assert "PASS" in result.output
        assert "FAIL" in result.output


# ===========================================================================
# bench
# ===========================================================================


class TestBench:
    """Tests for the bench command."""

    def test_bench_runs_iterations(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(
                app,
                ["bench", str(pack), "--iterations", "10", "--warmup", "2"],
            )
        assert result.exit_code == 0
        assert "Results (10 iterations)" in result.output
        assert "p50" in result.output
        assert "p95" in result.output

    def test_bench_shows_percentiles(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(
                app,
                ["bench", str(pack), "-n", "5", "-w", "1"],
            )
        assert result.exit_code == 0
        assert "p99" in result.output
        assert "mean" in result.output

    def test_bench_nonexistent_path(self) -> None:
        result = runner.invoke(app, ["bench", "/nonexistent/path"])
        assert result.exit_code != 0

    def test_bench_custom_iterations(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        mock_eng = _mock_engine()
        with patch("fathom.cli.Engine.from_rules", return_value=mock_eng):
            result = runner.invoke(
                app,
                ["bench", str(pack), "-n", "3", "-w", "0"],
            )
        assert result.exit_code == 0
        assert "Results (3 iterations)" in result.output


# ===========================================================================
# repl
# ===========================================================================


class TestRepl:
    """Tests for the repl command."""

    def test_repl_starts_and_exits_on_eof(self) -> None:
        """REPL should start and exit cleanly when stdin sends EOF."""
        result = runner.invoke(app, ["repl"], input="")
        assert result.exit_code == 0
        assert "Fathom REPL" in result.output

    def test_repl_quit_command(self) -> None:
        result = runner.invoke(app, ["repl"], input="quit\n")
        assert result.exit_code == 0

    def test_repl_help_command(self) -> None:
        result = runner.invoke(app, ["repl"], input="help\nquit\n")
        assert result.exit_code == 0
        assert "Commands:" in result.output
        assert "assert" in result.output

    def test_repl_evaluate_command(self) -> None:
        result = runner.invoke(app, ["repl"], input="evaluate\nquit\n")
        assert result.exit_code == 0
        assert "decision:" in result.output

    def test_repl_with_rules(self, tmp_path: Path) -> None:
        pack = _make_rule_pack(tmp_path)
        result = runner.invoke(
            app,
            ["repl", "--rules", str(pack)],
            input="quit\n",
        )
        assert result.exit_code == 0
        assert "Loaded rules" in result.output

    def test_repl_unknown_command(self) -> None:
        result = runner.invoke(app, ["repl"], input="foobar\nquit\n")
        assert result.exit_code == 0
        assert "Unknown command" in result.output

    def test_repl_reset_command(self) -> None:
        result = runner.invoke(app, ["repl"], input="reset\nquit\n")
        assert result.exit_code == 0
        assert "Engine state reset" in result.output
