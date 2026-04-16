"""Shared test fixtures for the fathom test suite."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from fathom.compiler import Compiler
from fathom.engine import Engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_clips(s: str) -> str:
    """Collapse whitespace runs to a single space and strip the result.

    Used by snapshot tests that compare CLIPS-compiled output to an expected
    string. Per design Risks mitigation for snapshot brittleness, this avoids
    failures caused by incidental formatting differences (e.g., indentation,
    trailing newlines) while still catching meaningful token changes.
    """
    return _WHITESPACE_RE.sub(" ", s).strip()


# ---------------------------------------------------------------------------
# Basic instances
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Engine:
    """Fresh Engine instance for each test."""
    return Engine()


@pytest.fixture
def compiler() -> Compiler:
    """Fresh Compiler instance for each test."""
    return Compiler()


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_template_path() -> Path:
    """Path to sample template YAML file."""
    return FIXTURES_DIR / "templates" / "agent.yaml"


@pytest.fixture
def sample_rules_path() -> Path:
    """Path to sample rules YAML file."""
    return FIXTURES_DIR / "rules" / "access-control.yaml"


@pytest.fixture
def sample_modules_path() -> Path:
    """Path to sample modules YAML file."""
    return FIXTURES_DIR / "modules" / "modules.yaml"


@pytest.fixture
def sample_functions_path() -> Path:
    """Path to sample functions directory."""
    return FIXTURES_DIR / "functions"


@pytest.fixture
def sample_hierarchies_path() -> Path:
    """Path to sample hierarchies directory."""
    return FIXTURES_DIR / "hierarchies"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the fixtures root directory."""
    return FIXTURES_DIR


# ---------------------------------------------------------------------------
# Pre-configured Engine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_fixture(fixtures_dir: Path) -> Engine:
    """Engine loaded with the full governance rule set from test fixtures.

    Loads templates, modules, functions, and rules from the fixtures directory.
    """
    e = Engine()
    e.load_templates(str(fixtures_dir / "templates"))
    e.load_modules(str(fixtures_dir / "modules"))
    e.load_functions(str(fixtures_dir / "functions"))
    e.load_rules(str(fixtures_dir / "rules"))
    return e


# ---------------------------------------------------------------------------
# Sample YAML data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_hierarchy() -> dict[str, Any]:
    """Sample classification hierarchy as a Python dict.

    Mirrors ``tests/fixtures/hierarchies/classification.yaml``.
    """
    return {
        "name": "classification",
        "levels": [
            "unclassified",
            "cui",
            "confidential",
            "secret",
            "top-secret",
        ],
    }


@pytest.fixture
def sample_rules() -> dict[str, Any]:
    """Sample ruleset as a Python dict.

    A minimal deny rule for testing purposes.
    """
    return {
        "module": "test_mod",
        "rules": [
            {
                "name": "deny-api",
                "salience": 50,
                "when": [
                    {
                        "template": "request",
                        "conditions": [
                            {"slot": "type", "expression": "equals(api)"},
                        ],
                    },
                ],
                "then": {
                    "action": "deny",
                    "reason": "API requests denied",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Temp YAML file factory
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_yaml_file(tmp_path: Path):
    """Factory fixture: write a YAML dict/string to a temp file and return its path.

    Usage::

        def test_example(tmp_yaml_file):
            path = tmp_yaml_file({"templates": [...]}, name="templates.yaml")
            engine.load_templates(str(path))

    Parameters
    ----------
    content : dict | str
        YAML content. Dicts are serialised via ``yaml.safe_dump``.
    name : str, optional
        Filename inside ``tmp_path`` (default ``"data.yaml"``).

    Returns
    -------
    Path
        Absolute path to the written file.
    """

    def _factory(content: dict[str, Any] | str, name: str = "data.yaml") -> Path:
        text = yaml.safe_dump(content) if isinstance(content, dict) else content
        p = tmp_path / name
        p.write_text(text)
        return p

    return _factory
