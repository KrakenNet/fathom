"""Strict YAML loading: a typo in a policy file must fail the load.

Each case here used to load silently and change what the policy decides:
a rule pattern on a misspelled template that can never match, an unknown
top-level key that drops ``focus_order``, a duplicate mapping key that
keeps the last value, and a ``hierarchies:`` block that was never read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml
from typer.testing import CliRunner

from fathom.cli import app
from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.yaml_utils import safe_load, safe_load_all, validate_document

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATES = """\
templates:
  - name: req
    slots:
      - {name: role, type: symbol}
"""
MODULES = "modules:\n  - name: m\n"
RULES = """\
ruleset: rs
module: m
rules:
  - name: allow_admin
    when:
      - template: req
        conditions:
          - {slot: role, expression: equals(admin)}
    then: {action: allow}
"""
TYPO_TEMPLATE_RULES = """\
ruleset: rs
module: m
rules:
  - name: deny_alert
    when:
      - template: req
        conditions: []
      - template: alertt
        conditions:
          - test: (eq 1 1)
    then: {action: deny}
"""
DUP_KEY_RULES = """\
ruleset: rs
module: m
rules:
  - name: deny_non_admin
    when:
      - template: req
        conditions:
          - slot: role
            expression: not_equals(admin)
            expression: equals(admin)
    then: {action: deny}
"""


def _pack(root: Path, rules: str = RULES, **overrides: str) -> Path:
    files = {"templates": TEMPLATES, "modules": MODULES, "rules": rules, **overrides}
    for kind, text in files.items():
        (root / kind).mkdir(parents=True, exist_ok=True)
        (root / kind / "a.yaml").write_text(text)
    return root


# --- 1. rule pattern on an unregistered template --------------------------


def test_bare_pattern_on_unregistered_template_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CompilationError, match="'alertt', which is not registered"):
        Engine.from_rules(str(_pack(tmp_path, TYPO_TEMPLATE_RULES)))


def test_reload_rules_rejects_unregistered_template(tmp_path: Path) -> None:
    engine = Engine.from_rules(str(_pack(tmp_path)))
    with pytest.raises(CompilationError, match="'alertt', which is not registered"):
        engine.reload_rules(TYPO_TEMPLATE_RULES.encode())


def test_validate_rejects_unregistered_template(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path, TYPO_TEMPLATE_RULES))])
    assert result.exit_code != 0
    assert "alertt" in result.output


def test_validate_single_rule_file_uses_sibling_templates(tmp_path: Path) -> None:
    pack = _pack(tmp_path, TYPO_TEMPLATE_RULES)
    result = CliRunner().invoke(app, ["validate", str(pack / "rules" / "a.yaml")])
    assert result.exit_code != 0
    assert "alertt" in result.output


def test_validate_accepts_registered_templates(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path))])
    assert result.exit_code == 0, result.output


def _rule(expression: str = "equals(admin)", then: str = "{action: allow}") -> str:
    return (
        "ruleset: rs\nmodule: m\nrules:\n  - name: r\n"
        "    when: [{template: req, conditions:\n"
        f"      [{{slot: role, expression: '{expression}'}}]}}]\n"
        f"    then: {then}\n"
    )


# Templates and slots named outside a `when:` pattern: a `then.assert` target
# and the template/slot arguments of a temporal operator. Each used to pass
# load and validate; the bare assert made CLIPS invent the template, and the
# temporal ones raised on every evaluation that reached them.
UNKNOWN_REFERENCES = [
    pytest.param(_rule(then="{action: deny, assert: [{template: flg}]}"), "'flg'", id="assert"),
    pytest.param(
        _rule(then="{action: deny, assert: [{template: flg, slots: {who: x}}]}"),
        "'flg'",
        id="assert-slots",
    ),
    pytest.param(
        _rule(then="{action: deny, assert: [{template: req, slots: {rol: x}}]}"),
        "'rol'",
        id="assert-slot",
    ),
    pytest.param(_rule("count_exceeds(reqs, role, admin, 3)"), "'reqs'", id="count-template"),
    pytest.param(_rule("count_exceeds(req, rol, admin, 3)"), "'rol'", id="count-slot"),
    pytest.param(_rule("rate_exceeds(req, role, admin, 3, 60, tss)"), "'tss'", id="rate-ts"),
    pytest.param(_rule("distinct_count(req, role, rolee, 1)"), "'rolee'", id="distinct"),
    pytest.param(
        _rule('sequence_detected([{"template": "req", "slot": "rol", "value": "a"}], 60)'),
        "'rol'",
        id="sequence",
    ),
]


@pytest.mark.parametrize(("rules", "name"), UNKNOWN_REFERENCES)
def test_unknown_reference_is_rejected_at_load(tmp_path: Path, rules: str, name: str) -> None:
    with pytest.raises(CompilationError, match=name):
        Engine.from_rules(str(_pack(tmp_path, rules)))


@pytest.mark.parametrize(("rules", "name"), UNKNOWN_REFERENCES)
def test_unknown_reference_is_rejected_by_reload(tmp_path: Path, rules: str, name: str) -> None:
    engine = Engine.from_rules(str(_pack(tmp_path)))
    with pytest.raises(CompilationError, match=name):
        engine.reload_rules(rules.encode())


@pytest.mark.parametrize(("rules", "name"), UNKNOWN_REFERENCES)
def test_unknown_reference_is_rejected_by_validate(tmp_path: Path, rules: str, name: str) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path, rules))])
    assert result.exit_code != 0
    assert name in result.output


@pytest.mark.parametrize(
    "rules",
    [
        _rule(then="{action: deny, assert: [{template: req, slots: {role: x}}]}"),
        _rule("count_exceeds(req, role, admin, 3)"),
        _rule(
            'sequence_detected([{"template": "req", "slot": "role", "value": "a",'
            ' "slot_ts": "role"}], 60)'
        ),
    ],
)
def test_known_references_load_and_validate(tmp_path: Path, rules: str) -> None:
    pack = _pack(tmp_path, rules)
    Engine.from_rules(str(pack))
    result = CliRunner().invoke(app, ["validate", str(pack)])
    assert result.exit_code == 0, result.output


# --- 2. unknown top-level keys ---------------------------------------------


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("templates", TEMPLATES + "templatez: []\n"),
        ("modules", "modules:\n  - name: m\nfocus_ordr: [m]\n"),
        ("rules", RULES + "rulez: []\n"),
    ],
)
def test_unknown_top_level_key_is_rejected(tmp_path: Path, kind: str, text: str) -> None:
    pack = _pack(tmp_path, **{kind: text})
    bad_key = text.rstrip().rsplit("\n", 1)[-1].split(":")[0]
    with pytest.raises(CompilationError, match=f"unknown top-level key.*'{bad_key}'"):
        Engine.from_rules(str(pack))
    errors = CliRunner().invoke(app, ["validate", str(pack)])
    assert errors.exit_code != 0
    assert bad_key in errors.output


def test_unknown_top_level_key_in_function_file(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(
        "functions:\n  - {name: dbl, type: raw, params: [x],"
        ' body: "(deffunction MAIN::dbl (?x) (* ?x 2))"}\nhierarchy: []\n'
    )
    with pytest.raises(CompilationError, match="'hierarchy'"):
        Compiler().parse_function_file(path)
    assert validate_document(
        {"functions": [], "hierarchy": []},
        path,
    )


def test_unknown_top_level_key_in_flat_pack(tmp_path: Path) -> None:
    (tmp_path / "t.yaml").write_text(TEMPLATES)
    (tmp_path / "m.yaml").write_text("modules:\n  - name: m\nfocus_ordr: [m]\n")
    (tmp_path / "r.yaml").write_text(RULES)
    with pytest.raises(CompilationError, match="'focus_ordr'"):
        Engine().load_pack_dir(tmp_path)


def test_reload_rules_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    engine = Engine.from_rules(str(_pack(tmp_path)))
    with pytest.raises(CompilationError, match="'rulez'"):
        engine.reload_rules((RULES + "rulez: []\n").encode())


# --- 3. duplicate mapping keys ---------------------------------------------


def test_duplicate_key_is_rejected_at_load(tmp_path: Path) -> None:
    with pytest.raises(CompilationError) as info:
        Engine.from_rules(str(_pack(tmp_path, DUP_KEY_RULES)))
    assert "duplicate key 'expression'" in (info.value.detail or "")


def test_duplicate_key_is_rejected_by_reload(tmp_path: Path) -> None:
    engine = Engine.from_rules(str(_pack(tmp_path)))
    with pytest.raises(CompilationError, match="duplicate key 'expression'"):
        engine.reload_rules(DUP_KEY_RULES.encode())


def test_duplicate_key_is_rejected_by_validate(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["validate", str(_pack(tmp_path, DUP_KEY_RULES))])
    assert result.exit_code != 0
    assert "duplicate key 'expression'" in result.output


def test_duplicate_key_is_rejected_by_test_runner(tmp_path: Path) -> None:
    pack = _pack(tmp_path / "pack")
    cases = tmp_path / "t.yaml"
    cases.write_text(
        "- name: c\n  expected_decision: allow\n  expected_decision: deny\n  facts: []\n"
    )
    result = CliRunner().invoke(app, ["test", str(pack), str(cases)])
    assert result.exit_code != 0
    assert "duplicate key 'expected_decision'" in result.output


def test_yaml_merge_key_override_is_not_a_duplicate(tmp_path: Path) -> None:
    rules = RULES.replace(
        "    then: {action: allow}",
        "    then:\n      <<: {action: deny}\n      action: allow",
    )
    engine = Engine.from_rules(str(_pack(tmp_path, rules)))
    assert engine.evaluate_once([("req", {"role": "admin"})]).decision == "allow"


# --- 4. hierarchies: in the function bundle --------------------------------

BUNDLE = """\
hierarchies:
  - name: clearance
    levels: [unclassified, confidential, secret, top-secret]

functions:
  - name: clearance-check
    type: classification
    params: [a, b]
    hierarchy_ref: clearance
"""
SUBJ_TEMPLATES = """\
templates:
  - name: subj
    slots:
      - {name: clearance, type: symbol}
"""
CLEARANCE_RULES = """\
ruleset: rs
module: m
rules:
  - name: cleared
    when:
      - template: subj
        conditions:
          - {slot: clearance, expression: meets_or_exceeds(secret)}
    then: {action: allow}
"""


def test_hierarchies_in_function_bundle_are_loaded(tmp_path: Path) -> None:
    pack = _pack(
        tmp_path,
        CLEARANCE_RULES,
        templates=SUBJ_TEMPLATES,
        functions=BUNDLE,
    )
    engine = Engine.from_rules(str(pack))
    assert engine.evaluate_once([("subj", {"clearance": "top-secret"})]).decision == "allow"
    assert engine.evaluate_once([("subj", {"clearance": "confidential"})]).decision != "allow"
    compiled = CliRunner().invoke(app, ["compile", str(pack)])
    assert compiled.exit_code == 0, compiled.output
    assert "clearance-rank" in compiled.output
    assert CliRunner().invoke(app, ["validate", str(pack)]).exit_code == 0


def test_invalid_bundle_hierarchy_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_text(BUNDLE.replace("levels:", "levelz:"))
    with pytest.raises(CompilationError, match="invalid hierarchy"):
        Engine().load_functions(str(path))


@pytest.mark.parametrize("load", [safe_load, safe_load_all])
def test_strict_loader_is_still_safe(load: Any) -> None:
    # CodeQL flags yaml.load(Loader=_StrictLoader) as unsafe because it cannot
    # see that the loader is a SafeLoader subclass. Pin that it refuses Python
    # object tags the way yaml.safe_load does.
    with pytest.raises(yaml.constructor.ConstructorError):
        load("!!python/object/apply:os.system ['true']")


def test_invalid_ruleset_message_names_the_field(tmp_path: Path) -> None:
    # `reason: no` loads as YAML False. The message used to say only
    # "invalid ruleset in <path>", leaving the reason in `.detail`.
    rules = _rule(then="{action: deny, reason: no}")
    with pytest.raises(CompilationError, match=r"rules\.0\.then\.reason: Input should be"):
        Engine.from_rules(str(_pack(tmp_path, rules)))
