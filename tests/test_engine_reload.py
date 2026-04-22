"""Tests for Engine.reload_rules — hot-reload semantics (C5, FR-16, AC-5.1).

Covers the hash-trajectory contract documented in design.md C5: callers pass
raw ruleset YAML bytes to ``reload_rules`` and receive ``(hash_before,
hash_after)`` bracketing the atomic swap. The REST / gRPC reload endpoints
echo these values as ``ruleset_hash_before`` / ``ruleset_hash_after`` in
their responses and in the signed audit attestation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from fathom.engine import Engine


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
