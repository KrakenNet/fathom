"""Converted policies must decide the way OPA decides.

Everything else in the Rego suite checks the conversion's *shape*: the slot
names, the expression text, that the output parses, that a round trip lands
on the same rules. None of it ever asked the only question that matters --
given the same input document, does the converted policy answer what the
original answered?

It did not, in four separate ways, all of them invisible to a shape test:

* a policy whose `allow` and `deny` rules both matched decided by the order
  the rules happened to be written in, so a suspended admin was allowed or
  denied depending on the file;
* every Rego number was inferred as an `integer` slot, so `input.score > 1`
  refused to assert `{"score": 1.5}` -- OPA answers `true`;
* a set member holding a comma was split into two members;
* `else` was dropped without a word.

The tests here run OPA and Fathom against the same inputs and compare the
answers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from fathom.engine import Engine
from fathom.rego import convert_file, flatten_input

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")


def _opa_decision(policy: str, document: dict[str, Any], package: str) -> str:
    """What OPA answers for `data.<package>.allow` / `.deny`, as a decision.

    Rego holds the two in separate documents and leaves the precedence to
    the caller. This resolves it fail-closed -- deny beats allow -- which is
    the same resolution the converter bakes into the deny rules' salience.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "policy.rego").write_text(policy, encoding="utf-8")
        (root / "input.json").write_text(json.dumps(document), encoding="utf-8")
        result = subprocess.run(
            [
                "opa",
                "eval",
                "--data",
                str(root / "policy.rego"),
                "--input",
                str(root / "input.json"),
                "--format",
                "json",
                f"data.{package}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    bindings = json.loads(result.stdout).get("result") or []
    document_value: dict[str, Any] = {}
    for binding in bindings:
        for expression in binding.get("expressions") or []:
            document_value = expression.get("value") or {}
    if document_value.get("deny") is True:
        return "deny"
    if document_value.get("allow") is True:
        return "allow"
    return "undefined"


def _skips(policy: str) -> list[str]:
    """What the converter declined to translate, as text."""
    return [str(skip) for skip in convert_file(policy).skipped]


def _fathom_engine(policy: str) -> tuple[Engine, list[str]]:
    """Convert *policy* and load the result as a real engine."""
    converted = convert_file(policy)
    root = Path(tempfile.mkdtemp()) / "pack"
    for subdir in ("templates", "modules", "rules"):
        (root / subdir).mkdir(parents=True)
    (root / "templates" / "t.yaml").write_text(
        yaml.safe_dump({"templates": converted.templates}), encoding="utf-8"
    )
    (root / "modules" / "m.yaml").write_text(
        yaml.safe_dump({"modules": converted.modules, "focus_order": [converted.module]}),
        encoding="utf-8",
    )
    (root / "rules" / "r.yaml").write_text(
        yaml.safe_dump(
            {"ruleset": "converted", "module": converted.module, "rules": converted.rules}
        ),
        encoding="utf-8",
    )
    # default_decision=None: "undefined" has to stay distinguishable from a
    # rule that actually rendered a deny, or a policy that decides nothing
    # compares equal to one that denies.
    engine = Engine.from_rules(str(root), default_decision=None)
    return engine, [str(skip) for skip in converted.skipped]


def _fathom_decision(engine: Engine, document: dict[str, Any]) -> str:
    result = engine.evaluate_once([("input", flatten_input(document))])
    return result.decision or "undefined"


def _assert_parity(policy: str, package: str, documents: Iterable[dict[str, Any]]) -> None:
    engine, skipped = _fathom_engine(policy)
    assert skipped == [], f"policy was not fully converted: {skipped}"
    for document in documents:
        expected = _opa_decision(policy, document, package)
        actual = _fathom_decision(engine, document)
        assert actual == expected, f"input {document!r}: opa said {expected}, fathom said {actual}"


ALLOW_AND_DENY = """
package authz

allow if { input.role == "admin" }

deny if { input.suspended == true }
"""

DENY_WRITTEN_FIRST = """
package authz

deny if { input.suspended == true }

allow if { input.role == "admin" }
"""

NUMERIC = """
package authz

allow if { input.score > 1 }
"""

COMMA_IN_A_SET = """
package authz

allow if { input.city in {"Paris, France", "Berlin"} }
"""

STRINGS = """
package authz

allow if {
    startswith(input.path, "/public")
    input.method == "GET"
}
"""


class TestParity:
    def test_deny_beats_a_matching_allow(self) -> None:
        """A suspended admin matches both rules; the answer must not be a coin flip."""
        _assert_parity(
            ALLOW_AND_DENY,
            "authz",
            [
                {"role": "admin", "suspended": True},
                {"role": "admin", "suspended": False},
                {"role": "guest", "suspended": True},
                {"role": "guest", "suspended": False},
            ],
        )

    def test_the_answer_does_not_depend_on_the_order_the_rules_were_written(self) -> None:
        """Same policy, rules swapped. Fathom is last-write-wins; Rego is not."""
        _assert_parity(
            DENY_WRITTEN_FIRST,
            "authz",
            [
                {"role": "admin", "suspended": True},
                {"role": "admin", "suspended": False},
            ],
        )

    def test_a_fractional_number_reaches_the_policy(self) -> None:
        """`input.score > 1` is a claim about numbers, not about integers."""
        _assert_parity(
            NUMERIC,
            "authz",
            [{"score": 1.5}, {"score": 0.5}, {"score": 2}, {"score": 1}],
        )

    def test_a_set_member_holding_a_comma_stays_one_member(self) -> None:
        _assert_parity(
            COMMA_IN_A_SET,
            "authz",
            [
                {"city": "Paris, France"},
                {"city": "Berlin"},
                {"city": "Paris"},
                {"city": "France"},
            ],
        )

    def test_string_builtins(self) -> None:
        _assert_parity(
            STRINGS,
            "authz",
            [
                {"path": "/public/index.html", "method": "GET"},
                {"path": "/public/index.html", "method": "POST"},
                {"path": "/private/index.html", "method": "GET"},
            ],
        )


class TestRefusals:
    """What the converter declines has to be declined loudly, not silently."""

    def test_an_else_branch_is_reported_not_dropped(self) -> None:
        skipped = _skips(
            "package authz\n"
            'allow if { input.user == "admin" } else = false if { input.user == "guest" }\n'
        )
        assert any("else" in entry for entry in skipped)

    def test_a_mixed_type_set_is_reported(self) -> None:
        skipped = _skips('package authz\nallow if { input.level in {1, "two", 3} }\n')
        assert any("mixes" in entry for entry in skipped)
