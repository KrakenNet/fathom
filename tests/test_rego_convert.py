"""Rego -> Fathom conversion.

A policy converter's dangerous output is not a crash, it is a plausible file
that says something different from the policy it came from. So most of this
suite is about refusal: that the constructs outside the supported subset are
declined and reported rather than approximated, and that a rule missing one of
its conditions is dropped whole rather than shipped matching more broadly than
the original.

The fixtures are real `opa parse --format json` output, checked in beside the
`.rego` that produced them, so the tests do not need the `opa` binary. One
test regenerates them when `opa` is present, so they cannot quietly rot.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.rego import ConversionResult, convert_ast, parse_rego

FIXTURES = Path(__file__).parent / "fixtures" / "rego"


def _load(name: str) -> ConversionResult:
    return convert_ast(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def _expressions(result: ConversionResult, rule_name: str) -> list[str]:
    rule = next(r for r in result.rules if r["name"] == rule_name)
    return [c["expression"] for c in rule["when"][0]["conditions"]]


def _slot_types(result: ConversionResult) -> dict[str, str]:
    if not result.templates:
        return {}
    return {s["name"]: s["type"] for s in result.templates[0]["slots"]}


def _reasons(result: ConversionResult) -> str:
    return "\n".join(str(s) for s in result.skipped)


def _load_into_engine(result: ConversionResult) -> Engine:
    """Write the conversion out as a pack and load it, as a user would."""
    root = Path(tempfile.mkdtemp())
    payloads = {
        "templates": {"templates": result.templates},
        "modules": {"modules": result.modules, "focus_order": [result.module]},
        "rules": {"module": result.module, "ruleset": result.module, "rules": result.rules},
    }
    for kind, payload in payloads.items():
        (root / kind).mkdir()
        (root / kind / "converted.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
    return Engine.from_rules(str(root))


# ---------------------------------------------------------------------------
# What converts
# ---------------------------------------------------------------------------


class TestSupportedSubset:
    def test_comparisons(self) -> None:
        assert _expressions(_load("basic"), "allow-1") == [
            "equals(admin)",
            "not_equals(delete)",
        ]

    def test_package_becomes_the_module(self) -> None:
        result = _load("basic")
        assert result.package == "authz.basic"
        assert result.module == "authz_basic"

    def test_nested_input_paths_flatten_into_slot_names(self) -> None:
        """`input.user.role` has to become one flat slot; the name says which."""
        assert "user_role" in _slot_types(_load("basic"))

    def test_every_rego_number_infers_one_slot_type(self) -> None:
        """Rego has a single `number`, so `> 3` must not imply an int slot.

        Inferring `integer` from a whole-number literal produced a template
        that rejects the input the policy was written for: `input.score > 1`
        would refuse to assert `{"score": 1.5}`, which OPA answers `true`.
        """
        assert _slot_types(_load("numeric")) == {
            "attempts": "float",
            "resource_level": "float",
            "score": "float",
        }

    def test_reversed_operands_flip_the_comparison(self) -> None:
        """`3 < input.attempts` is `attempts > 3`, not `attempts < 3`."""
        assert _expressions(_load("numeric"), "allow-3") == ["greater_than(3)"]

    def test_set_membership(self) -> None:
        assert _expressions(_load("strings_and_sets"), "allow-1")[0].startswith("in([")

    def test_startswith_becomes_an_anchored_regex(self) -> None:
        assert "matches(^/public)" in _expressions(_load("strings_and_sets"), "allow-1")

    def test_endswith_escapes_the_literal(self) -> None:
        """`.key` as a regex would match any character; the dot has to be escaped."""
        assert _expressions(_load("strings_and_sets"), "deny-2") == [r"matches(\.key$)"]

    def test_contains_and_re_match(self) -> None:
        assert _expressions(_load("strings_and_sets"), "deny-3") == ["contains(DROP TABLE)"]
        assert _expressions(_load("strings_and_sets"), "deny-4") == ["matches(^tmp-[0-9]+$)"]

    def test_one_bad_rule_does_not_lose_the_good_ones(self) -> None:
        """Partial conversion is the common case; all-or-nothing is `--strict`."""
        result = _load("mixed")
        assert [r["name"] for r in result.rules] == ["allow-1", "allow-2"]
        assert len(result.skipped) == 2

    def test_each_rego_body_becomes_its_own_rule(self) -> None:
        """Rego ORs the bodies of one rule name; Fathom ORs separate rules."""
        names = [r["name"] for r in _load("strings_and_sets").rules]
        assert names == ["allow-1", "deny-2", "deny-3", "deny-4"]


# ---------------------------------------------------------------------------
# What it refuses, and why
# ---------------------------------------------------------------------------


class TestRefusals:
    def test_nothing_convertible_converts_nothing(self) -> None:
        result = _load("refusals")
        assert result.rules == []
        assert result.converted_anything is False

    def test_negation(self) -> None:
        assert "no negation" in _reasons(_load("refusals"))

    def test_inclusive_comparison_is_not_rewritten(self) -> None:
        """`>= 3` as `> 2` is right for integers and wrong for everything else."""
        reasons = _reasons(_load("refusals"))
        assert "`>= n` as `> n-1`" in reasons
        assert "`<= n` as `< n+1`" in reasons

    def test_reference_against_reference(self) -> None:
        assert "both operands are references" in _reasons(_load("refusals"))

    def test_data_reference_is_named_as_such(self) -> None:
        """`data` is not a field of `input`; saying "both are references" hides that."""
        assert "reads `data`" in _reasons(_load("refusals"))

    def test_function_call_operand_is_named_as_such(self) -> None:
        assert "function call or a computed reference" in _reasons(_load("refusals"))

    def test_bare_truthiness(self) -> None:
        assert "bare truthiness check" in _reasons(_load("refusals"))

    def test_a_rule_that_is_not_allow_or_deny(self) -> None:
        assert "only rules named 'allow' or 'deny'" in _reasons(_load("refusals"))

    def test_a_partial_rule_is_dropped_whole(self) -> None:
        """The failure that matters: half a rule permits more than the whole one."""
        assert "matches more broadly than the policy it came from" in _reasons(_load("refusals"))

    def test_a_dropped_rule_leaves_no_slots_behind(self) -> None:
        """Every slot in the emitted template is one a converted rule reads."""
        assert _slot_types(_load("refusals")) == {}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class TestNotes:
    def test_default_decision_is_reported_not_silently_dropped(self) -> None:
        notes = " ".join(_load("basic").notes)
        assert "default allow := false" in notes

    def test_booleans_carry_the_warning_that_they_became_symbols(self) -> None:
        """A Python `True` will not match `equals(true)`; say so at conversion."""
        notes = " ".join(_load("basic").notes)
        assert "Rego booleans" in notes
        assert _slot_types(_load("basic"))["user_suspended"] == "symbol"


# ---------------------------------------------------------------------------
# The output is a real ruleset
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize("fixture", ["basic", "strings_and_sets", "numeric"])
    def test_the_conversion_loads_into_an_engine(self, fixture: str) -> None:
        engine = _load_into_engine(_load(fixture))
        assert engine.rule_registry

    def test_the_converted_policy_decides_the_same_way(self) -> None:
        """The point of the exercise: same input, same answer as the Rego."""
        engine = _load_into_engine(_load("basic"))
        allowed = engine.evaluate_once(
            [("input", {"user_role": "admin", "action": "read", "user_suspended": "false"})]
        )
        assert allowed.decision == "allow"
        denied = engine.evaluate_once(
            [("input", {"user_role": "admin", "action": "delete", "user_suspended": "true"})]
        )
        assert denied.decision == "deny"

    def test_a_non_matching_input_fires_nothing(self) -> None:
        engine = _load_into_engine(_load("basic"))
        result = engine.evaluate_once(
            [("input", {"user_role": "guest", "action": "delete", "user_suspended": "false"})]
        )
        assert result.rule_trace == []


# ---------------------------------------------------------------------------
# The parser boundary
# ---------------------------------------------------------------------------


class TestParsing:
    def test_a_missing_opa_binary_says_where_to_get_it(self, monkeypatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _: None)
        with pytest.raises(CompilationError, match="'opa' binary is required"):
            parse_rego("package p")

    @pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
    def test_opa_rejects_invalid_rego(self) -> None:
        with pytest.raises(CompilationError, match="opa rejected the policy"):
            parse_rego("package p\nallow if { ==== }")

    @pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
    @pytest.mark.parametrize("fixture", sorted(p.stem for p in FIXTURES.glob("*.rego")))
    def test_checked_in_asts_still_match_what_opa_produces(self, fixture: str) -> None:
        """Fixtures are a cache of another program's output, so they can rot."""
        source = (FIXTURES / f"{fixture}.rego").read_text(encoding="utf-8")
        committed = json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
        fresh = parse_rego(source, filename=f"{fixture}.rego")
        # `comments` records the absolute path of the file OPA read, which is a
        # temp directory here and the repo path when the fixture was generated.
        # Nothing downstream reads comments, so the paths are noise.
        fresh.pop("comments", None)
        committed.pop("comments", None)
        assert fresh == committed


# ---------------------------------------------------------------------------
# Non-AST edges
# ---------------------------------------------------------------------------


class TestEdges:
    def test_an_empty_module_converts_to_nothing(self) -> None:
        result = convert_ast({"package": {"path": []}, "rules": []})
        assert result.rules == []
        assert result.templates == []
        assert result.module == "policy"

    def test_the_template_name_is_configurable(self) -> None:
        result = convert_ast(
            json.loads((FIXTURES / "basic.json").read_text(encoding="utf-8")),
            template="request",
        )
        assert result.templates[0]["name"] == "request"
        assert result.rules[0]["when"][0]["template"] == "request"


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not installed")
def test_opa_parse_reports_the_callers_filename() -> None:
    """OPA is handed a temp file; its diagnostics must still name the real one."""
    with pytest.raises(CompilationError) as caught:
        parse_rego("package p\nallow if { ==== }", filename="my-policy.rego")
    assert "my-policy.rego" in (caught.value.detail or "") + str(caught.value)


def test_opa_parse_timeout_is_reported_not_hung(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="opa", timeout=30)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/opa")
    monkeypatch.setattr("subprocess.run", _boom)
    with pytest.raises(CompilationError, match="could not run 'opa parse'"):
        parse_rego("package p")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    """`fathom convert rego`, with the parse step stubbed to the fixture AST.

    The binary is OPA's business; what needs pinning here is the plumbing --
    exit codes, where output lands, and that skips reach stderr.
    """

    @staticmethod
    def _run(tmp_path, fixture: str, *args: str):
        from typer.testing import CliRunner

        from fathom.cli import app

        policy = tmp_path / f"{fixture}.rego"
        policy.write_text((FIXTURES / f"{fixture}.rego").read_text(encoding="utf-8"))
        ast = json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr("fathom.cli.parse_rego", lambda _s, **_k: ast)
            runner = CliRunner(mix_stderr=False)
            return runner.invoke(app, ["convert", "rego", str(policy), *args])

    def test_prints_yaml_without_an_output_directory(self, tmp_path) -> None:
        result = self._run(tmp_path, "basic")
        assert result.exit_code == 0
        assert yaml.safe_load(result.stdout)["module"] == "authz_basic"

    def test_writes_a_loadable_pack_with_an_output_directory(self, tmp_path) -> None:
        out = tmp_path / "pack"
        assert self._run(tmp_path, "basic", "-o", str(out)).exit_code == 0
        assert Engine.from_rules(str(out)).rule_registry

    def test_a_policy_with_nothing_convertible_exits_nonzero(self, tmp_path) -> None:
        """Silence plus exit 0 would read as "converted fine"."""
        assert self._run(tmp_path, "refusals").exit_code != 0

    def test_skips_are_reported_on_stderr(self, tmp_path) -> None:
        """Skips must not land on stdout, where they would corrupt the YAML."""
        result = self._run(tmp_path, "mixed")
        assert "convert skipped" in result.stderr
        assert "negation" in result.stderr
        assert "convert skipped" not in result.stdout

    def test_strict_fails_on_a_partial_conversion(self, tmp_path) -> None:
        """Default is best-effort; --strict is for pipelines that want all or nothing."""
        assert self._run(tmp_path, "mixed").exit_code == 0
        assert self._run(tmp_path, "mixed", "--strict").exit_code != 0

    def test_a_missing_policy_file_is_rejected_before_anything_runs(self, tmp_path) -> None:
        from typer.testing import CliRunner

        from fathom.cli import app

        result = CliRunner().invoke(app, ["convert", "rego", str(tmp_path / "nope.rego")])
        assert result.exit_code != 0
