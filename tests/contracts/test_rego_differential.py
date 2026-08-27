"""Converted policies must answer what OPA answers -- on inputs nobody chose.

Structural check F from the audit post-mortem. ``tests/test_rego_parity.py``
already runs OPA and the converted pack against the same document, but the
documents are hand-written, and every hand-written document is complete: it
carries a value for every field the policy reads. The divergences all lived
in the documents nobody thought to write.

So the documents are derived here instead of chosen. For every ``input``
reference in the policy the generator emits:

- the **baseline** -- every referenced path present, holding a value taken
  from the policy's own literal;
- **absent** -- the same document with that one path removed, which is the
  case Rego answers by leaving the rule body undefined;
- **off-value** -- the same document with that path holding something the
  literal does not match;
- **shadow** -- for a nested path, the same document plus a top-level key
  spelled the way the path flattens (``user.role`` and ``user_role``), which
  are two unrelated paths in Rego and must stay unrelated here.

Each document is put to the real ``opa`` binary and to the converted pack,
and the answers must agree. A policy the converter declines to translate in
full is not compared -- ``skipped`` must be empty, because a partial
conversion that reports nothing is the failure this check exists to catch.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from fathom.engine import Engine
from fathom.errors import ValidationError as FathomValidationError
from fathom.rego import convert_file, export_engine, flatten_input
from tests.test_rego_parity import _fathom_engine, _opa_decision

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")

#: Ceiling on documents per policy. The generator is quadratic in references
#: and the point is coverage of shapes, not of every combination.
MAX_DOCUMENTS = 500

EQUALITY = """
package authz

default allow := false

allow if {
    input.user.role == "admin"
}
"""

NEGATION = """
package authz

default allow := false

allow if {
    input.action != "delete"
}
"""

NUMERIC = """
package authz

default allow := false

allow if {
    input.amount < 100
}
"""

MEMBERSHIP = """
package authz

default allow := false

allow if {
    input.city in {"Paris", "Berlin"}
}
"""

PREFIX = """
package authz

default allow := false

allow if {
    startswith(input.path, "/public")
    input.method == "GET"
}
"""

CONJUNCTION = """
package authz

default allow := false

allow if {
    input.user.role == "admin"
    input.region == "us"
    input.amount < 100
}
"""

ALLOW_AND_DENY = """
package authz

allow if {
    input.user.role == "admin"
}

deny if {
    input.user.suspended == true
}
"""

POLICIES = {
    "equality": EQUALITY,
    "negation": NEGATION,
    "numeric": NUMERIC,
    "membership": MEMBERSHIP,
    "prefix": PREFIX,
    "conjunction": CONJUNCTION,
    "allow_and_deny": ALLOW_AND_DENY,
}

_REFERENCE = re.compile(r"input((?:\.[A-Za-z_]\w*)+)")


def _matching_value(policy: str, path: str) -> Any:
    """A value for *path* taken from the policy's own literal, if it has one.

    Deliberately dumb: the point is a document the policy plausibly matches,
    not a solver. Anything unrecognised gets a string, which the converted
    template's slot type will accept or the comparison will simply not match
    -- and OPA is asked the same question either way.
    """
    reference = re.escape(f"input.{path}")
    for pattern, convert in (
        (rf"{reference}\s*==\s*\"([^\"]*)\"", str),
        (rf"{reference}\s*==\s*(true|false)", lambda t: t == "true"),
        (rf"{reference}\s*==\s*(-?\d+(?:\.\d+)?)", float),
        (rf"{reference}\s*!=\s*\"([^\"]*)\"", lambda s: f"{s}-other"),
        (rf"{reference}\s*[<>]=?\s*(-?\d+(?:\.\d+)?)", float),
        (rf"{reference}\s+in\s+\{{\s*\"([^\"]*)\"", str),
        (rf"startswith\({reference},\s*\"([^\"]*)\"", lambda s: f"{s}/x"),
    ):
        found = re.search(pattern, policy)
        if found:
            return convert(found.group(1))
    return "unset"


def _off_value(value: Any) -> Any:
    """Something the policy's literal does not match, of the same Rego type."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return float(value) + 1000.0
    return f"{value}-off"


def _put(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = document
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _drop(document: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    cursor = document
    for part in parts[:-1]:
        cursor = cursor.get(part)
        if not isinstance(cursor, dict):
            return
    cursor.pop(parts[-1], None)


def _documents(policy: str) -> list[tuple[str, dict[str, Any]]]:
    """Every derived document for *policy*, labelled by how it was derived."""
    paths = sorted({found.group(1).lstrip(".") for found in _REFERENCE.finditer(policy)})
    baseline: dict[str, Any] = {}
    for path in paths:
        _put(baseline, path, _matching_value(policy, path))

    derived: list[tuple[str, dict[str, Any]]] = [("baseline", baseline)]
    for path in paths:
        absent = copy.deepcopy(baseline)
        _drop(absent, path)
        derived.append((f"absent:{path}", absent))

        off = copy.deepcopy(baseline)
        _put(off, path, _off_value(_matching_value(policy, path)))
        derived.append((f"off:{path}", off))

        if "." in path:
            shadow = copy.deepcopy(baseline)
            shadow[path.replace(".", "_")] = _off_value(_matching_value(policy, path))
            derived.append((f"shadow:{path}", shadow))

            shadow_only = copy.deepcopy(baseline)
            _drop(shadow_only, path)
            shadow_only[path.replace(".", "_")] = _matching_value(policy, path)
            derived.append((f"shadow-only:{path}", shadow_only))

    return derived[:MAX_DOCUMENTS]


def _decision(engine: Engine, document: dict[str, Any]) -> str:
    """What the converted pack answers, the way the OPA Data API answers it.

    A document that does not fit the templates is not an error in Rego: the
    reference is undefined, the body fails, and the policy falls to its
    default. `POST /v1/data/...` resolves it the same way, so the comparison
    has to as well or it would be testing a shape no caller sees.
    """
    declared = {slot.name for slot in engine.template_registry["input"].slots}
    fact = {k: v for k, v in flatten_input(document).items() if k in declared}
    try:
        result = engine.evaluate_once([("input", fact)])
    except FathomValidationError:
        return engine.default_decision or "undefined"
    return result.decision or "undefined"


@pytest.mark.parametrize("name", sorted(POLICIES), ids=sorted(POLICIES))
def test_a_converted_policy_answers_what_opa_answers(name: str) -> None:
    policy = POLICIES[name]
    engine, skipped = _fathom_engine(policy)
    assert skipped == [], f"{name} was not fully converted: {skipped}"

    documents = _documents(policy)
    assert len(documents) > 1, f"{name} produced no derived documents"

    divergences = [
        f"{label} {json.dumps(document, sort_keys=True)}: "
        f"opa={_opa_decision(policy, document, 'authz')} "
        f"fathom={_decision(engine, document)}"
        for label, document in documents
        if _opa_decision(policy, document, "authz") != _decision(engine, document)
    ]

    assert divergences == []


def _pack_engine(tmp_path: Path, templates: list, rules: list, module: str) -> Engine:
    """Write a pack to disk and load it, the way a migrating user would."""
    for kind, payload in (
        ("templates", {"templates": templates}),
        ("modules", {"modules": [{"name": module}], "focus_order": [module]}),
        ("rules", {"module": module, "ruleset": module, "rules": rules}),
    ):
        (tmp_path / kind).mkdir(parents=True, exist_ok=True)
        (tmp_path / kind / "p.yaml").write_text(yaml.safe_dump(payload, sort_keys=False))
    return Engine.from_rules(str(tmp_path))


def _opa_parses(source: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "exported.rego"
    path.write_text(source, encoding="utf-8")
    return subprocess.run(
        ["opa", "parse", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("name", sorted(POLICIES), ids=sorted(POLICIES))
def test_an_exported_policy_is_a_policy_opa_accepts(name: str, tmp_path: Path) -> None:
    """Round trip: convert to a pack, export it back, and let OPA parse it."""
    converted = convert_file(POLICIES[name])
    assert converted.skipped == []

    engine = _pack_engine(tmp_path, converted.templates, converted.rules, converted.module)
    exported = export_engine(engine, package="authz.export")

    result = _opa_parses(exported.source, tmp_path)
    assert result.returncode == 0, f"{result.stderr}\n---\n{exported.source}"


MULTILINE_REASONS = [
    "Denied: the request exceeded its quota.\nContact ops to raise it.\n",
    'gold tier\nallow if { input.anything == "at-all" }\n',
    "line one\n\nline three",
]


@pytest.mark.parametrize("reason", MULTILINE_REASONS, ids=["prose", "rego-shaped", "blank-line"])
def test_every_line_of_a_reason_is_a_comment(reason: str, tmp_path: Path) -> None:
    """A reason is documentation. A second line of it must not become policy."""
    templates = [{"name": "input", "slots": [{"name": "tier", "type": "string"}]}]
    rules = [
        {
            "name": "r1",
            "when": [
                {
                    "template": "input",
                    "conditions": [{"slot": "tier", "expression": "equals(gold)"}],
                }
            ],
            "then": {"action": "allow", "reason": reason},
        }
    ]

    engine = _pack_engine(tmp_path, templates, rules, "gov")
    exported = export_engine(engine, package="authz.export")

    result = _opa_parses(exported.source, tmp_path)
    assert result.returncode == 0, f"{result.stderr}\n---\n{exported.source}"

    for line in reason.splitlines():
        if line.strip():
            assert f"# {line}" in exported.source, exported.source
