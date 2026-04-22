"""Tests for Engine.reload_rules — hot-reload semantics (C5, FR-16, AC-5.1).

Covers the hash-trajectory contract documented in design.md C5: callers pass
raw ruleset YAML bytes to ``reload_rules`` and receive ``(hash_before,
hash_after)`` bracketing the atomic swap. The REST / gRPC reload endpoints
echo these values as ``ruleset_hash_before`` / ``ruleset_hash_after`` in
their responses and in the signed audit attestation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fathom.engine import Engine
from fathom.errors import CompilationError


def _write_pack(tmp_path: Path) -> None:
    """Set up a minimal templates + modules pack in *tmp_path*.

    ``reload_rules`` assumes templates and modules are already registered
    (it's a rule-only swap; see learnings from T-2.4). This helper emits
    the shared infrastructure both rulesets A and B compile against.
    """
    (tmp_path / "templates.yaml").write_text(
        "templates:\n"
        "  - name: agent\n"
        "    slots:\n"
        "      - name: id\n"
        "        type: symbol\n"
    )
    (tmp_path / "modules.yaml").write_text(
        "modules:\n  - name: gov\n    priority: 100\nfocus_order: [gov]\n"
    )


def _ruleset_yaml(rule_name: str, subject: str) -> bytes:
    """Build a self-contained ruleset YAML payload for reload_rules."""
    return yaml.safe_dump(
        {
            "ruleset": f"rs-{rule_name}",
            "module": "gov",
            "rules": [
                {
                    "name": rule_name,
                    "when": [
                        {
                            "template": "agent",
                            "conditions": [
                                {"slot": "id", "expression": f"equals({subject})"},
                            ],
                        },
                    ],
                    "then": {"action": "allow", "reason": f"{rule_name} ok"},
                },
            ],
        }
    ).encode("utf-8")


def test_reload_returns_hashes(tmp_path: Path) -> None:
    """reload_rules returns (hash_before, hash_after) matching ruleset_hash trajectory."""
    _write_pack(tmp_path)

    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))

    # Empty engine has the zero sentinel hash.
    empty_sentinel = "sha256:" + "0" * 64
    assert engine.ruleset_hash == empty_sentinel

    # Load ruleset A.
    ruleset_a = _ruleset_yaml("rule-a", "alice")
    (tmp_path / "rules-a.yaml").write_bytes(ruleset_a)
    engine.load_rules(str(tmp_path / "rules-a.yaml"))

    hash_a = engine.ruleset_hash
    assert hash_a != empty_sentinel
    assert hash_a.startswith("sha256:")

    # Reload with ruleset B (different rule name + subject → different bytes).
    ruleset_b = _ruleset_yaml("rule-b", "bob")
    assert ruleset_a != ruleset_b

    hash_before, hash_after = engine.reload_rules(ruleset_b)

    # Returned tuple brackets the swap: before matches pre-reload state,
    # after matches post-reload state, and the two differ.
    assert hash_before == hash_a
    assert hash_after == engine.ruleset_hash
    assert hash_before != hash_after
    assert hash_before.startswith("sha256:")
    assert hash_after.startswith("sha256:")


def test_reload_compile_failure_preserves_old_env(tmp_path: Path) -> None:
    """reload_rules with broken YAML raises CompilationError and leaves the old env intact (NFR-8).

    Design C5 / AC-5.3 / NFR-8: a failed compile on the fresh env must never
    mutate ``self._env`` or any registry. This codifies the "CompilationError
    leaves old env byte-identical" smoke test T-2.4 relied on.
    """
    _write_pack(tmp_path)

    engine = Engine()
    engine.load_templates(str(tmp_path / "templates.yaml"))
    engine.load_modules(str(tmp_path / "modules.yaml"))

    # Load ruleset A — matches agent(id=alice) → allow / "rule-a ok".
    ruleset_a = _ruleset_yaml("rule-a", "alice")
    (tmp_path / "rules-a.yaml").write_bytes(ruleset_a)
    engine.load_rules(str(tmp_path / "rules-a.yaml"))

    hash_before = engine.ruleset_hash
    env_id_before = id(engine._env)

    # Intentionally-broken YAML — unterminated flow sequence. reload_rules
    # wraps yaml.YAMLError as CompilationError (construct="reload_rules:parse").
    broken_yaml = b"ruleset: broken\nmodule: gov\nrules: [{name: broken, when: [{\n"

    with pytest.raises(CompilationError):
        engine.reload_rules(broken_yaml)

    # Invariants after the failure: ruleset_hash unchanged, env identity
    # unchanged (no pointer flip), ruleset A still evaluates to its
    # original decision.
    assert engine.ruleset_hash == hash_before
    assert id(engine._env) == env_id_before

    engine.assert_fact("agent", {"id": "alice"})
    result = engine.evaluate()
    assert result.decision == "allow"
    assert result.reason == "rule-a ok"
    assert result.rule_trace == ["gov::rule-a"]
