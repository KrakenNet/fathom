"""Whatever the code keeps a collection of, exercise number two.

Structural check B from the audit post-mortem. The recurring shape: the code
holds a registry — hierarchies, functions, sessions, log writers, connections —
and the suite exercises one entry in it. One is the case where "first" and
"only" cannot be told apart, and every bug in this file lived in that gap. Each
test here adds a second member and asserts on the *answer it produces*, never
on its presence in the registry: `"trust" in engine._hierarchy_registry` was
true the whole time the trust ladder was ranking every level at -1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fathom.engine import Engine
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from pathlib import Path

_TEMPLATES = """
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: trust
        type: symbol
        required: true
      - name: sensitivity
        type: symbol
        required: true
"""

_MODULES = """
modules:
  - name: gate
focus_order:
  - gate
"""

_SENSITIVITY = """
name: sensitivity
levels: [public, internal, confidential, restricted]
"""

_TRUST = """
name: trust
levels: [untrusted, basic, verified, privileged]
"""

_FUNCTIONS = """
functions:
  - name: rank_sensitivity
    type: classification
    params: [a, b]
    hierarchy_ref: sensitivity.yaml
  - name: rank_trust
    type: classification
    params: [a, b]
    hierarchy_ref: trust.yaml
"""

_TRUST_ONLY_FUNCTIONS = """
functions:
  - name: rank_trust
    type: classification
    params: [a, b]
    hierarchy_ref: trust.yaml
"""

# Both rules read `agent.trust` -- the SECOND hierarchy. Under the unscoped
# shims they ranked through the first one's table, where every trust level is
# the -1 default: `meets_or_exceeds` was `-1 >= -1` for everything and `below`
# was `-1 < -1` for nothing.
_RULES = """
module: gate
ruleset: two-hierarchies
version: "1.0"

rules:
  - name: allow-verified-agent
    salience: 100
    when:
      - template: agent
        conditions:
          - slot: trust
            expression: "meets_or_exceeds(verified)"
    then:
      action: allow
      reason: "verified or better"

  - name: deny-below-basic
    salience: 10
    when:
      - template: agent
        conditions:
          - slot: trust
            expression: "below(basic)"
    then:
      action: deny
      reason: "below basic trust"
"""


def _write(root: Path, files: dict[str, tuple[str, str]]) -> Path:
    for subdir, (name, body) in files.items():
        (root / subdir).mkdir(parents=True, exist_ok=True)
        (root / subdir / name).write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def two_hierarchy_pack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    _write(
        root,
        {
            "templates": ("templates.yaml", _TEMPLATES),
            "modules": ("modules.yaml", _MODULES),
            "rules": ("rules.yaml", _RULES),
        },
    )
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "sensitivity.yaml").write_text(_SENSITIVITY, encoding="utf-8")
    (root / "hierarchies" / "trust.yaml").write_text(_TRUST, encoding="utf-8")
    (root / "functions").mkdir()
    (root / "functions" / "functions.yaml").write_text(_FUNCTIONS, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("trust", "expected"),
    [
        ("untrusted", "deny"),
        ("basic", "deny"),
        ("verified", "allow"),
        ("privileged", "allow"),
    ],
)
def test_the_second_hierarchy_ranks_its_own_levels(
    two_hierarchy_pack: Path, trust: str, expected: str
) -> None:
    """Every level, not one: the broken table answered the same for all four."""
    engine = Engine.from_rules(str(two_hierarchy_pack), default_decision="deny")
    engine.assert_fact("agent", {"id": "a-1", "trust": trust, "sensitivity": "internal"})

    assert engine.evaluate().decision == expected


def test_a_level_no_loaded_hierarchy_defines_is_a_compile_error(tmp_path: Path) -> None:
    """The alternative is an operator that silently answers true for everything."""
    root = tmp_path / "pack"
    _write(
        root,
        {
            "templates": ("templates.yaml", _TEMPLATES),
            "modules": ("modules.yaml", _MODULES),
            "rules": (
                "rules.yaml",
                _RULES.replace("meets_or_exceeds(verified)", "below(nonesuch)"),
            ),
        },
    )
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "trust.yaml").write_text(_TRUST, encoding="utf-8")
    (root / "functions").mkdir()
    (root / "functions" / "functions.yaml").write_text(_TRUST_ONLY_FUNCTIONS, encoding="utf-8")

    with pytest.raises(CompilationError, match="nonesuch"):
        Engine.from_rules(str(root))


def test_one_hierarchy_still_compiles_through_the_unscoped_shim(tmp_path: Path) -> None:
    """The single-hierarchy pack every shipped example is, unchanged."""
    root = tmp_path / "pack"
    _write(
        root,
        {
            "templates": ("templates.yaml", _TEMPLATES),
            "modules": ("modules.yaml", _MODULES),
            "rules": ("rules.yaml", _RULES),
        },
    )
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "trust.yaml").write_text(_TRUST, encoding="utf-8")
    (root / "functions").mkdir()
    (root / "functions" / "functions.yaml").write_text(_TRUST_ONLY_FUNCTIONS, encoding="utf-8")

    engine = Engine.from_rules(str(root), default_decision="deny")
    engine.assert_fact("agent", {"id": "a-1", "trust": "untrusted", "sensitivity": "internal"})

    assert engine.evaluate().decision == "deny"


# ---------------------------------------------------------------------------
# A second *kind* of construct in the env: the ones a hot reload forgot.
# ---------------------------------------------------------------------------

_RELOAD_RULES = """
module: gate
ruleset: reloaded
version: "1.0"

rules:
  - name: deny-below-basic
    when:
      - template: agent
        conditions:
          - slot: trust
            expression: "below(basic)"
    then:
      action: deny
      reason: "reloaded — below basic trust"
"""


def _one_hierarchy_pack(root: Path) -> Path:
    _write(
        root,
        {
            "templates": ("templates.yaml", _TEMPLATES),
            "modules": ("modules.yaml", _MODULES),
            "rules": ("rules.yaml", _RULES),
        },
    )
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "trust.yaml").write_text(_TRUST, encoding="utf-8")
    (root / "functions").mkdir()
    (root / "functions" / "functions.yaml").write_text(_TRUST_ONLY_FUNCTIONS, encoding="utf-8")
    return root


def test_reload_keeps_the_classification_functions_the_rules_call(tmp_path: Path) -> None:
    """A reload is a rule-only swap onto a fresh env — which had no functions.

    Re-posting a pack's own unmodified rules was rejected with a raw CLIPS
    `Missing function declaration for 'below'`: templates and modules were
    rebuilt onto the new environment from their registries, and nothing held a
    record of the deffunctions at all.
    """
    engine = Engine.from_rules(
        str(_one_hierarchy_pack(tmp_path / "pack")), default_decision="deny"
    )

    engine.reload_rules(_RELOAD_RULES.encode())

    engine.assert_fact("agent", {"id": "a-1", "trust": "untrusted", "sensitivity": "internal"})
    result = engine.evaluate()
    assert result.decision == "deny"
    assert result.reason == "reloaded — below basic trust"


_BLOCKLIST_RULES = """
module: gate
ruleset: reloaded
version: "1.0"

rules:
  - name: deny-blocklisted
    when:
      - template: agent
        conditions:
          - slot: id
            bind: "?aid"
          - test: "(on-blocklist ?aid)"
    then:
      action: deny
      reason: "on the blocklist"
"""


def test_reload_keeps_a_callable_registered_through_the_sdk(tmp_path: Path) -> None:
    """`register_function` bindings live only on the env the reload replaces."""
    root = tmp_path / "pack"
    _write(
        root,
        {
            "templates": ("templates.yaml", _TEMPLATES),
            "modules": ("modules.yaml", _MODULES),
            "rules": ("rules.yaml", _RULES),
        },
    )
    (root / "hierarchies").mkdir()
    (root / "hierarchies" / "trust.yaml").write_text(_TRUST, encoding="utf-8")
    (root / "functions").mkdir()
    (root / "functions" / "functions.yaml").write_text(_TRUST_ONLY_FUNCTIONS, encoding="utf-8")

    engine = Engine.from_rules(str(root), default_decision="allow")
    engine.register_function("on-blocklist", lambda value: str(value) == "a-1")

    engine.reload_rules(_BLOCKLIST_RULES.encode())

    engine.assert_fact("agent", {"id": "a-1", "trust": "verified", "sensitivity": "internal"})
    assert engine.evaluate().decision == "deny"
