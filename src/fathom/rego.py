"""Convert a Rego policy into Fathom YAML.

Rego and Fathom answer different questions. Rego evaluates one `input`
document against a policy and returns a decision; Fathom matches typed facts
in working memory that persist across evaluations. A stateless Rego rule maps
onto a Fathom rule over a single `input` fact, and that is the subset this
converts.

The design rule throughout: **refuse rather than guess.** A policy converter
that mistranslates is worse than one that declines, because the output looks
finished. Every construct outside the supported subset is reported as a
:class:`Skipped` with the reason and the rule it came from, and never turned
into an approximation.

Parsing is delegated to `opa parse --format json`, not reimplemented. Rego's
grammar is large and a second, worse parser for it is exactly the kind of
silent mistranslation this module exists to avoid.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fathom.errors import CompilationError

__all__ = [
    "ConversionResult",
    "OPA_DOWNLOAD_URL",
    "Skipped",
    "convert_ast",
    "convert_file",
    "parse_rego",
]

#: Where to get the parser when it is missing. Named in the error rather than
#: left for the reader to search for.
OPA_DOWNLOAD_URL = "https://www.openpolicyagent.org/docs/latest/#running-opa"

#: Rego built-ins that map onto a Fathom operator without approximation.
#: `gte` and `lte` are deliberately absent: Fathom has `greater_than` and
#: `less_than` only, and rewriting `>= 3` as `> 2` is correct for integers and
#: wrong for everything else.
_COMPARISONS = {
    "equal": "equals",
    "eq": "equals",
    "neq": "not_equals",
    "gt": "greater_than",
    "lt": "less_than",
}

#: Rule head names that become a Fathom decision. A Rego policy names its
#: decision whatever it likes; these are the two conventions with an
#: unambiguous Fathom counterpart.
_DECISIONS = {"allow": "allow", "deny": "deny"}


@dataclass(frozen=True)
class Skipped:
    """One construct the converter declined to translate."""

    rule: str
    construct: str
    reason: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.construct} — {self.reason}"


@dataclass
class ConversionResult:
    """Everything one Rego file produced, including what it did not."""

    package: str = ""
    module: str = ""
    templates: list[dict[str, Any]] = field(default_factory=list)
    modules: list[dict[str, Any]] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def converted_anything(self) -> bool:
        return bool(self.rules)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_rego(source: str, *, filename: str = "policy.rego") -> dict[str, Any]:
    """Return the OPA AST for *source*, by running `opa parse --format json`.

    Args:
        source: Rego policy text.
        filename: Name to hand OPA, so its diagnostics point somewhere real.

    Returns:
        The parsed module AST.

    Raises:
        CompilationError: If the `opa` binary is missing, fails, or emits
            something that is not a JSON object.
    """
    opa = shutil.which("opa")
    if opa is None:
        raise CompilationError(
            "[fathom.rego] parse failed: the 'opa' binary is required to read "
            "Rego and was not found on PATH",
            detail=(
                "Rego is parsed by OPA itself rather than by a second parser "
                f"that could disagree with it. Install OPA: {OPA_DOWNLOAD_URL}"
            ),
        )
    # `opa parse` reads a file, not stdin. Writing the source under its own
    # basename keeps OPA's diagnostics pointing at a name the caller recognises.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / Path(filename).name
            policy.write_text(source, encoding="utf-8")
            completed = subprocess.run(  # noqa: S603
                [opa, "parse", "--format", "json", str(policy)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompilationError(
            "[fathom.rego] parse failed: could not run 'opa parse'",
            file=filename,
            detail=str(exc),
        ) from exc

    if completed.returncode != 0:
        raise CompilationError(
            "[fathom.rego] parse failed: opa rejected the policy",
            file=filename,
            detail=completed.stderr.strip() or completed.stdout.strip(),
        )

    try:
        ast = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CompilationError(
            "[fathom.rego] parse failed: 'opa parse' did not emit JSON",
            file=filename,
            detail=str(exc),
        ) from exc

    if not isinstance(ast, dict):
        raise CompilationError(
            f"[fathom.rego] parse failed: expected a module object, got {type(ast).__name__}",
            file=filename,
        )
    return ast


# ---------------------------------------------------------------------------
# AST readers
#
# Each returns None rather than raising, so an unrecognised shape becomes a
# reported skip at the call site instead of an exception halfway through a
# file.
# ---------------------------------------------------------------------------


def _package_path(ast: dict[str, Any]) -> str:
    """`package authz.access` -> `authz.access` (the leading `data` dropped)."""
    parts = ast.get("package", {}).get("path", [])
    names = [str(p.get("value", "")) for p in parts if p.get("type") == "string"]
    return ".".join(n for n in names if n)


def _ref_path(term: dict[str, Any]) -> list[str] | None:
    """`input.user.role` -> `["input", "user", "role"]`, else None."""
    if term.get("type") != "ref":
        return None
    parts = term.get("value", [])
    if not parts or parts[0].get("type") != "var":
        return None
    path = [str(parts[0].get("value", ""))]
    for part in parts[1:]:
        if part.get("type") != "string":
            return None  # a computed key: input[x] rather than input.x
        path.append(str(part.get("value", "")))
    return path


def _builtin_name(term: dict[str, Any]) -> str | None:
    """The dotted name of the built-in a body expression calls."""
    parts = term.get("value", []) if term.get("type") == "ref" else []
    names = [str(p.get("value", "")) for p in parts if p.get("type") in ("var", "string")]
    return ".".join(names) if names else None


def _literal(term: dict[str, Any]) -> str | int | float | bool | None:
    """The Python value of a scalar term, or None if it is not a scalar."""
    if term.get("type") in ("string", "number", "boolean"):
        value = term.get("value")
        if isinstance(value, str | int | float | bool):
            return value
    return None


def _set_members(term: dict[str, Any]) -> list[str] | None:
    """The scalar members of a set or array term, as strings."""
    if term.get("type") not in ("set", "array"):
        return None
    members: list[str] = []
    for member in term.get("value", []):
        value = _literal(member)
        if value is None:
            return None
        members.append(str(value))
    return members


# ---------------------------------------------------------------------------
# Slot naming and typing
# ---------------------------------------------------------------------------


def _slot_name(path: list[str]) -> str:
    """`["input", "user", "role"]` -> `user_role`.

    Rego's `input` is an arbitrary nested document and a Fathom template is
    flat, so the nesting is flattened into the slot name. The mapping is
    documented rather than clever: a reader has to be able to look at
    `user_role` and know which Rego reference it came from.
    """
    return "_".join(path[1:])


def _slot_type(value: object) -> str:
    if isinstance(value, bool):
        return "symbol"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _widen(existing: str, incoming: str) -> str:
    """Reconcile two inferences for one slot.

    Rego is untyped, so a slot compared against both a number and a string is
    legal there and has no type here. `string` is the type that can hold
    either, so a disagreement widens to it rather than picking a side.
    """
    if existing == incoming:
        return existing
    if {existing, incoming} == {"integer", "float"}:
        return "float"
    return "string"


# ---------------------------------------------------------------------------
# Expression translation
# ---------------------------------------------------------------------------


def _comparison(op: str, args: list[dict[str, Any]]) -> tuple[list[str], str, object] | None:
    """Translate a two-argument comparison into (path, operator, literal)."""
    fathom_op = _COMPARISONS[op]
    left, right = args
    left_path, right_path = _ref_path(left), _ref_path(right)
    left_value, right_value = _literal(left), _literal(right)

    if left_path and right_value is not None:
        return left_path, fathom_op, right_value
    if right_path and left_value is not None:
        # `"admin" == input.role` means the same thing, but the inequality
        # operators reverse when the operands do.
        flipped = {"greater_than": "less_than", "less_than": "greater_than"}
        return right_path, flipped.get(fathom_op, fathom_op), left_value
    return None


def _why_not_comparable(args: list[dict[str, Any]]) -> str:
    """Say what a comparison actually contained, not just that it failed.

    A refusal is this converter's main product, so it has to name the thing
    the reader must go and change.
    """
    for arg in args:
        path = _ref_path(arg)
        if path and path[0] == "data":
            return (
                "one operand reads `data`, which is external state Fathom holds "
                "as its own facts rather than as fields of `input`"
            )
        if arg.get("type") == "call" or (
            arg.get("type") == "ref" and path is None and arg.get("value")
        ):
            return (
                "one operand is a function call or a computed reference; a Fathom "
                "condition compares one slot against a literal"
            )
    return "both operands are references; a Fathom condition compares one slot against a literal"


def _condition(expr: dict[str, Any], rule_name: str) -> tuple[list[str], str, object] | Skipped:
    """One Rego body expression as (path, expression, literal), or why not."""
    if expr.get("negated"):
        return Skipped(
            rule_name,
            "not <expr>",
            "Fathom fact patterns have no negation; a rule cannot match on the absence of a value",
        )

    terms = expr.get("terms")
    if isinstance(terms, dict):
        path = _ref_path(terms)
        described = ".".join(path) if path else terms.get("type", "expression")
        return Skipped(
            rule_name,
            str(described),
            "a bare truthiness check has no Fathom equivalent; compare the value explicitly",
        )
    if not isinstance(terms, list) or len(terms) < 3:
        return Skipped(rule_name, "expression", "unrecognised body expression")

    op = _builtin_name(terms[0])
    args = terms[1:]

    if op in _COMPARISONS and len(args) == 2:
        result = _comparison(op, args)
        if result is not None:
            return result
        return Skipped(rule_name, f"{op}(...)", _why_not_comparable(args))

    if op in ("internal.member_2", "in") and len(args) == 2:
        path = _ref_path(args[0])
        members = _set_members(args[1])
        if path and members is not None:
            return path, "in", members
        return Skipped(rule_name, "in", "the collection is not a set or array of scalars")

    if op in ("startswith", "endswith", "contains", "re_match") and len(args) == 2:
        return _string_builtin(op, args, rule_name)

    if op in ("gte", "lte"):
        written, rewrite = (">=", "> n-1") if op == "gte" else ("<=", "< n+1")
        return Skipped(
            rule_name,
            f"{op}(...)",
            f"Fathom has no inclusive comparison; rewriting `{written} n` as "
            f"`{rewrite}` is right for integers and wrong for everything else, "
            "so it is not done for you",
        )

    return Skipped(rule_name, f"{op or 'expression'}(...)", "unsupported built-in")


def _string_builtin(
    op: str, args: list[dict[str, Any]], rule_name: str
) -> tuple[list[str], str, object] | Skipped:
    """startswith / endswith / contains / re_match against a literal."""
    if op == "re_match":
        # re_match(pattern, value) -- pattern first, unlike the others.
        pattern, path = _literal(args[0]), _ref_path(args[1])
        if path and isinstance(pattern, str):
            return path, "matches", pattern
        return Skipped(rule_name, "re_match", "pattern or subject is not literal")

    path, needle = _ref_path(args[0]), _literal(args[1])
    if path is None or not isinstance(needle, str):
        return Skipped(rule_name, op, "subject or argument is not literal")
    if op == "contains":
        return path, "contains", needle
    anchored = re.escape(needle)
    return path, "matches", f"^{anchored}" if op == "startswith" else f"{anchored}$"


def _expression_text(operator: str, value: object) -> str:
    """Render a Fathom condition expression string."""
    if operator == "in":
        members = value if isinstance(value, list) else [value]
        return f"in([{', '.join(str(m) for m in members)}])"
    if isinstance(value, bool):
        return f"{operator}({'true' if value else 'false'})"
    return f"{operator}({value})"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def convert_ast(ast: dict[str, Any], *, template: str = "input") -> ConversionResult:
    """Convert a parsed Rego module into Fathom template/module/rule dicts.

    Args:
        ast: A module AST as produced by :func:`parse_rego`.
        template: Name for the synthesised template holding Rego's `input`.

    Returns:
        A :class:`ConversionResult`. Check ``skipped`` before trusting the
        output to be the whole policy.
    """
    package = _package_path(ast)
    module = re.sub(r"[^A-Za-z0-9]+", "_", package).strip("_") or "policy"

    result = ConversionResult(package=package, module=module)
    slots: dict[str, str] = {}

    for index, rego_rule in enumerate(ast.get("rules") or []):
        head = rego_rule.get("head") or {}
        name = str(head.get("name") or "")

        if rego_rule.get("default"):
            result.notes.append(
                f"`default {name} := {json.dumps(head.get('value', {}).get('value'))}` "
                "was not converted: Fathom's default decision is set on the "
                "engine, not in the ruleset."
            )
            continue

        action = _DECISIONS.get(name)
        if action is None:
            result.skipped.append(
                Skipped(
                    name or f"rule[{index}]",
                    f"rule '{name}'",
                    "only rules named 'allow' or 'deny' become a Fathom "
                    "decision; give the rule one of those names or convert it "
                    "by hand",
                )
            )
            continue
        if _literal(head.get("value") or {}) is not True:
            result.skipped.append(
                Skipped(
                    name,
                    f"rule '{name}'",
                    "the head assigns a value other than true; Fathom rules "
                    "render a decision, not a computed value",
                )
            )
            continue

        conditions: list[dict[str, str]] = []
        # Buffered, not merged as we go: a rule that turns out to be
        # unconvertible must not leave its slots behind. Every slot in the
        # emitted template is one a converted rule reads.
        rule_slots: dict[str, str] = {}
        failed = False
        for expr in rego_rule.get("body") or []:
            outcome = _condition(expr, name)
            if isinstance(outcome, Skipped):
                result.skipped.append(outcome)
                failed = True
                continue
            path, operator, value = outcome
            if path[0] != "input":
                result.skipped.append(
                    Skipped(
                        name,
                        ".".join(path),
                        "only `input` references convert; `data` is external "
                        "state Fathom holds as its own facts",
                    )
                )
                failed = True
                continue
            slot = _slot_name(path)
            if not slot:
                result.skipped.append(
                    Skipped(name, "input", "a bare `input` reference names no field")
                )
                failed = True
                continue
            sample = value[0] if operator == "in" and isinstance(value, list) else value
            inferred = "string" if operator in ("matches", "contains") else _slot_type(sample)
            rule_slots[slot] = (
                _widen(rule_slots[slot], inferred) if slot in rule_slots else inferred
            )
            conditions.append({"slot": slot, "expression": _expression_text(operator, value)})

        if failed:
            # A partially converted rule is a different policy. Dropping the
            # whole rule keeps the output honest: what is there is faithful,
            # and what is missing is listed.
            result.skipped.append(
                Skipped(
                    name,
                    f"rule '{name}' (body {index})",
                    "dropped whole: a rule missing one of its conditions "
                    "matches more broadly than the policy it came from",
                )
            )
            continue
        if not conditions:
            result.skipped.append(
                Skipped(name, f"rule '{name}'", "empty body; it would match everything")
            )
            continue

        for slot, inferred in rule_slots.items():
            slots[slot] = _widen(slots[slot], inferred) if slot in slots else inferred

        result.rules.append(
            {
                "name": f"{name}-{len(result.rules) + 1}",
                "when": [{"template": template, "conditions": conditions}],
                "then": {
                    "action": action,
                    "reason": f"{package}.{name} (converted from Rego)",
                },
            }
        )

    if slots:
        result.templates.append(
            {
                "name": template,
                "slots": [
                    {"name": slot, "type": slot_type} for slot, slot_type in sorted(slots.items())
                ],
            }
        )
    if any(slot_type == "symbol" for slot_type in slots.values()):
        result.notes.append(
            "Rego booleans became the symbols `true` / `false`. Fathom has no "
            'boolean slot type, so assert them as the strings "true" / "false"; '
            "a Python `True` is rejected by slot validation rather than silently "
            "failing to match."
        )
    if result.rules:
        result.modules.append({"name": module, "description": f"Converted from {package}"})
    return result


def convert_file(source: str, *, filename: str = "policy.rego") -> ConversionResult:
    """Parse *source* with OPA and convert it. See :func:`convert_ast`."""
    return convert_ast(parse_rego(source, filename=filename))
