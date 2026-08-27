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
from typing import TYPE_CHECKING, Any

from fathom.compiler import _ARG_TOKEN_RE, Compiler
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "ConversionResult",
    "ExportResult",
    "OPA_DOWNLOAD_URL",
    "Skipped",
    "convert_ast",
    "convert_file",
    "export_engine",
    "flatten_input",
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

#: Salience for a converted `deny`. Fathom is last-write-wins, so the lower
#: salience is what makes deny beat a matching allow instead of the outcome
#: depending on the order the Rego file happened to list them in.
_DENY_SALIENCE = -10

#: What a converted slot holds when the input document leaves the field out.
#: Rego leaves an absent reference undefined and the rule body simply fails; a
#: CLIPS slot always has a value, and the type's derived default ("" or 0.0)
#: happily satisfies `not_equals(delete)` and `less_than(100)` -- so a partial
#: document was ALLOWED here and denied by OPA. Absence is therefore given a
#: value of its own, and every converted rule guards the slots it reads
#: against it. A document that really does carry the sentinel is treated as
#: not carrying the field, which is the one case this encoding gets wrong.
_ABSENT: dict[str, str | float] = {
    "string": "__fathom_absent__",
    "symbol": "__fathom_absent__",
    "float": -1.7976931348623157e308,
}


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


def _set_members(term: dict[str, Any]) -> list[str | int | float | bool] | None:
    """The scalar members of a set or array term, with their types intact.

    Stringifying them here lost the distinction between the number 1 and the
    string "1", and the slot type was then inferred from whichever member
    happened to sort first.
    """
    if term.get("type") not in ("set", "array"):
        return None
    members: list[str | int | float | bool] = []
    for member in term.get("value", []):
        value = _literal(member)
        if value is None:
            return None
        members.append(value)
    return members


# ---------------------------------------------------------------------------
# Slot naming and typing
# ---------------------------------------------------------------------------


def _escape_segment(segment: str) -> str:
    """Double any `_` in one path segment so the join stays reversible.

    Without this, `input.user.role` and a literal top-level `input.user_role`
    flatten to the same slot -- two unrelated paths in Rego, one slot here,
    and whichever the document mentions last wins. A caller who controlled any
    string field escalated by naming it `user_role`.
    """
    return segment.replace("_", "__")


def _slot_name(path: list[str]) -> str:
    """`["input", "user", "role"]` -> `user_role`.

    Rego's `input` is an arbitrary nested document and a Fathom template is
    flat, so the nesting is flattened into the slot name. The mapping is
    documented rather than clever: a reader has to be able to look at
    `user_role` and know which Rego reference it came from. A segment that
    itself contains `_` is escaped to `__`, which keeps the mapping one-to-one
    (see :func:`_escape_segment`).
    """
    return "_".join(_escape_segment(segment) for segment in path[1:])


def flatten_input(document: dict[str, Any], _prefix: str = "") -> dict[str, Any]:
    """Flatten an OPA `input` document into Fathom slot values.

    The inverse of what :func:`_slot_name` does at conversion time, and it has
    to stay the inverse: a policy converted here is served facts built here,
    so `{"user": {"role": "admin"}}` must produce `user_role` and nothing
    else. Booleans become the symbols `true` / `false` because Fathom has no
    boolean slot type -- the same substitution the converter warns about.

    Values Fathom has no slot type for (lists, null, nested nulls) are left
    out. No rule can match on them, so carrying them through would only make
    the assert fail on a field nothing reads.

    Key segments are escaped exactly as :func:`_slot_name` escapes them, so no
    two input paths can land in the same slot: `{"user": {"role": x}}` fills
    `user_role` and a top-level `"user_role"` fills `user__role`, which is the
    slot a policy reading `input.user_role` was converted against.
    """
    flat: dict[str, Any] = {}
    for key, value in document.items():
        name = f"{_prefix}{_escape_segment(key)}"
        if isinstance(value, dict):
            flat.update(flatten_input(value, f"{name}_"))
        elif isinstance(value, bool):
            flat[name] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            # One Rego number type, one Fathom slot type (see `_slot_type`).
            # A converted template declares `float`, which rejects a Python
            # int; an `integer` slot accepts a whole float, so this is safe
            # in both directions.
            flat[name] = float(value)
        elif isinstance(value, str):
            flat[name] = value
    return flat


def _slot_type(value: object) -> str:
    """The Fathom slot type for one Rego scalar.

    Rego has a single `number` type: `1` and `1.5` are the same kind of
    thing, and `1 == 1.0` is true. Inferring `integer` from a policy that
    happens to compare against a whole number produced a slot that rejects
    the very input the policy was written for -- `input.score > 1` refusing
    to assert `{"score": 1.5}`, which OPA answers `true`. Every Rego number
    becomes a `float` slot, and :func:`flatten_input` feeds it floats.
    """
    if isinstance(value, bool):
        return "symbol"
    if isinstance(value, (int, float)):
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

    if op in _STRING_BUILTINS and len(args) == 2:
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


#: String built-ins with an exact Fathom operator. `regex.match` is the
#: current name and `re_match` the deprecated alias for the same function;
#: both appear in real policies, so both are read.
_STRING_BUILTINS = ("startswith", "endswith", "contains", "re_match", "regex.match")


def _string_builtin(
    op: str, args: list[dict[str, Any]], rule_name: str
) -> tuple[list[str], str, object] | Skipped:
    """startswith / endswith / contains / regex.match against a literal."""
    if op in ("re_match", "regex.match"):
        # The pattern comes first here, unlike the others.
        pattern, path = _literal(args[0]), _ref_path(args[1])
        if path and isinstance(pattern, str):
            return path, "matches", pattern
        return Skipped(rule_name, op, "pattern or subject is not literal")

    path, needle = _ref_path(args[0]), _literal(args[1])
    if path is None or not isinstance(needle, str):
        return Skipped(rule_name, op, "subject or argument is not literal")
    if op == "contains":
        return path, "contains", needle
    anchored = re.escape(needle)
    return path, "matches", f"^{anchored}" if op == "startswith" else f"{anchored}$"


def _argument_text(value: object) -> str:
    """One Rego scalar as a Fathom operator argument.

    A member that is not a bare token has to be quoted or the expression
    means something else: `{"Paris, France", "Berlin"}` rendered unquoted
    became a three-member list, two of them nonsense.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _ARG_TOKEN_RE.match(text):
        return text
    return json.dumps(text)


def _expression_text(operator: str, value: object) -> str:
    """Render a Fathom condition expression string."""
    if operator == "in":
        members = value if isinstance(value, list) else [value]
        return f"in([{', '.join(_argument_text(m) for m in members)}])"
    if operator in ("contains", "matches"):
        # The argument is a regex or a substring, not a token: it is escaped
        # and quoted by the compiler, and quoting it here would make the
        # quotes part of the pattern.
        return f"{operator}({value})"
    return f"{operator}({_argument_text(value)})"


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
    guarded: list[tuple[dict[str, Any], dict[str, str]]] = []

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

        if rego_rule.get("else"):
            # The else branch is a whole second body with its own head value.
            # Converting only the primary body produces a rule that is silent
            # where the policy was explicit, which is the mistranslation this
            # module exists to refuse.
            result.skipped.append(
                Skipped(
                    name or f"rule[{index}]",
                    f"rule '{name}' else branch",
                    "an `else` branch is a second rule body with its own "
                    "value; write it as a separate Fathom rule with a "
                    "salience that orders it",
                )
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
            if operator in ("matches", "contains"):
                inferred = "string"
            elif operator == "in" and isinstance(value, list):
                member_types = {_slot_type(member) for member in value}
                if len(member_types) > 1:
                    # A Fathom slot has one type. `{1, "two"}` is legal Rego
                    # and there is no slot that holds both, so widening to
                    # `string` would leave the numbers unmatchable rather
                    # than merely imprecise.
                    result.skipped.append(
                        Skipped(
                            name,
                            _expression_text(operator, value),
                            "the set mixes "
                            + ", ".join(sorted(member_types))
                            + " members; a Fathom slot holds one type",
                        )
                    )
                    failed = True
                    continue
                inferred = member_types.pop()
            else:
                inferred = _slot_type(value)
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

        rule: dict[str, Any] = {
            "name": f"{name}-{len(result.rules) + 1}",
            "when": [{"template": template, "conditions": conditions}],
            "then": {
                "action": action,
                "reason": f"{package}.{name} (converted from Rego)",
            },
        }
        if action == "deny":
            # Rego keeps `allow` and `deny` in separate documents and leaves
            # the precedence to whoever queries them. Fathom renders one
            # decision, last write wins, so without a salience the outcome
            # for an input matching both came down to which rule happened to
            # be written first -- a suspended admin was allowed or denied by
            # file order. Deny fires last and wins.
            rule["salience"] = _DENY_SALIENCE
        result.rules.append(rule)
        guarded.append((rule, dict(rule_slots)))

    # Presence guards go on last, using the slot types as finally widened: a
    # slot widened to `string` by a later rule needs the string sentinel, not
    # the one its own rule inferred.
    for rule, rule_slots in guarded:
        conditions = rule["when"][0]["conditions"]
        rule["when"][0]["conditions"] = [
            {"slot": slot, "expression": _expression_text("not_equals", _ABSENT[slots[slot]])}
            for slot in sorted(rule_slots)
            if slots[slot] in _ABSENT
        ] + conditions

    if slots:
        result.templates.append(
            {
                "name": template,
                "slots": [
                    {"name": slot, "type": slot_type, "default": _ABSENT[slot_type]}
                    if slot_type in _ABSENT
                    else {"name": slot, "type": slot_type}
                    for slot, slot_type in sorted(slots.items())
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
    if slots:
        result.notes.append(
            "Every rule guards the fields it reads against the sentinel each "
            "slot defaults to, so a document that omits a field decides the "
            "way OPA decides it -- the rule does not fire. Send the sentinel "
            f"({_ABSENT['string']!r}, {_ABSENT['float']!r}) as a real value "
            "and it will be read as the field being absent."
        )
    actions = {rule["then"]["action"] for rule in result.rules}
    if {"allow", "deny"} <= actions:
        result.notes.append(
            "The policy has both `allow` and `deny` rules. Rego holds them in "
            "separate documents and leaves the precedence to the caller; "
            "Fathom renders one decision, so the converted `deny` rules carry "
            f"salience {_DENY_SALIENCE} and win over a matching `allow`. "
            "Change the salience if your caller resolved it the other way."
        )
    if result.rules:
        result.modules.append({"name": module, "description": f"Converted from {package}"})
    return result


def convert_file(source: str, *, filename: str = "policy.rego") -> ConversionResult:
    """Parse *source* with OPA and convert it. See :func:`convert_ast`."""
    return convert_ast(parse_rego(source, filename=filename))


# ---------------------------------------------------------------------------
# Export: Fathom -> Rego
# ---------------------------------------------------------------------------
#
# The other direction, under the same rule: refuse rather than guess. Most of
# what makes Fathom worth using -- facts that persist, cross-fact joins, the
# temporal and classification operators -- has no Rego counterpart at all, so
# the exportable subset is narrow by nature. A rule that leaves it is reported,
# never flattened into a Rego rule that means something else.

#: Fathom operators with an exact Rego form. Everything else -- the temporal
#: and classification families -- is refused, because Rego evaluates one input
#: document and has nowhere to put a question about history or a hierarchy.
_REGO_COMPARISONS = {
    "equals": "==",
    "not_equals": "!=",
    "greater_than": ">",
    "less_than": "<",
}


@dataclass
class ExportResult:
    """One ruleset's worth of Rego, including what did not make it."""

    package: str = ""
    source: str = ""
    skipped: list[Skipped] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rule_count: int = 0

    @property
    def exported_anything(self) -> bool:
        return self.rule_count > 0


def _unquote(raw: str) -> str:
    """A Fathom operator argument's value, with its own quoting removed.

    `equals("Paris, France")` reaches here as the eight-and-a-bit characters
    including the quotes. Re-encoding that whole text as a Rego string put
    literal quote marks inside the value.
    """
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        try:
            unquoted = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(unquoted, str):
            return unquoted
    return raw


def _rego_literal(raw: str, slot_type: str) -> str:
    """Render a Fathom condition argument as a Rego term.

    The declared slot type decides, not the shape of the text: `equals(5)` on
    a `string` slot is the string "5" in Fathom and has to stay one here.
    A `symbol` slot holding `true` or `false` is the exception -- that is what
    :func:`flatten_input` turns a Rego boolean into, so it goes back.
    """
    value = _unquote(raw)
    if slot_type == "symbol" and value in ("true", "false"):
        return value
    if slot_type in ("integer", "float"):
        return value
    return json.dumps(value)


def _rego_set(raw: str, slot_type: str) -> str:
    """`[a, b]` -> `{"a", "b"}`."""
    inner = raw.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    # Top-level commas only: a member may legitimately contain one, and
    # splitting on every comma turned `["Paris, France"]` into two members.
    members = [m for m in Compiler._split_operator_args(inner) if m]
    return "{" + ", ".join(_rego_literal(m, slot_type) for m in members) + "}"


def _rego_condition(reference: str, op: str, arg: str, slot_type: str) -> str | None:
    """One Fathom condition as a Rego body expression, or None if it has none."""
    if op in _REGO_COMPARISONS:
        return f"{reference} {_REGO_COMPARISONS[op]} {_rego_literal(arg, slot_type)}"
    if op == "in":
        return f"{reference} in {_rego_set(arg, slot_type)}"
    if op == "not_in":
        return f"not {reference} in {_rego_set(arg, slot_type)}"
    if op == "contains":
        return f"contains({reference}, {json.dumps(_unquote(arg))})"
    if op == "matches":
        return f"regex.match({json.dumps(_unquote(arg))}, {reference})"
    return None


#: The conditions :func:`convert_ast` adds to stand in for "the field is
#: present". They carry no meaning outside the converted pack.
_ABSENCE_GUARDS = frozenset(_expression_text("not_equals", value) for value in _ABSENT.values())


def _why_not_exportable(op: str) -> str:
    """Name the family an operator belongs to, not just that it is unsupported."""
    if op in Compiler._TEMPORAL_OPS:
        return (
            f"`{op}` asks a question about history, and Rego evaluates one "
            "input document with no memory of the last one"
        )
    if op in Compiler._CLASSIFICATION_OPS:
        return (
            f"`{op}` resolves against a classification hierarchy, which is "
            "engine state Rego has no counterpart for"
        )
    return f"`{op}` has no Rego equivalent"


def _export_rule(
    rule: Any,
    templates: dict[str, Any],
    reference: Callable[[str, str], str],
) -> tuple[str, list[str]] | Skipped:
    """One Fathom rule as (document_name, body_lines), or why not."""
    name = rule.name
    if rule.then.asserts:
        return Skipped(
            name,
            "then.assert",
            "the rule asserts new facts; Rego derives documents from one input "
            "and cannot add to working memory",
        )
    if rule.then.action is None:
        return Skipped(
            name,
            "assert-only rule",
            "the rule produces no decision, only inference, which is the part "
            "of Fathom Rego does not have",
        )
    if rule.then.scope is not None:
        return Skipped(
            name,
            "then.scope",
            "the decision carries a scope value; a Rego document is a boolean "
            "here and has nowhere to put it",
        )
    if len(rule.when) != 1:
        return Skipped(
            name,
            f"{len(rule.when)} fact patterns",
            "the rule joins across facts, and Rego has one input document to join against",
        )

    pattern = rule.when[0]
    template = templates.get(pattern.template)
    if template is None:
        return Skipped(name, pattern.template, "the template is not declared by this ruleset")
    slot_types = {slot.name: str(slot.type) for slot in template.slots}

    body: list[str] = []
    for condition in pattern.conditions:
        if condition.expression in _ABSENCE_GUARDS:
            # Bookkeeping, not policy: the guard exists because a CLIPS slot
            # always holds a value and Rego's `input` field simply may not be
            # there. Exporting it would write the encoding into a language
            # that does not need it -- and a round trip would then guard the
            # guards.
            continue
        if condition.test is not None:
            return Skipped(name, "test:", "a raw CLIPS conditional element cannot be translated")
        if condition.bind is not None:
            return Skipped(
                name,
                "bind:",
                "the condition binds a variable for another condition to use, "
                "which is a join and so has no single-document form",
            )
        if not condition.expression:
            return Skipped(name, condition.slot, "the condition has no expression")
        op, arg = Compiler._parse_operator(condition.expression)
        # `$alias.field`, not any `$` -- a `matches(...)` regex ends with one.
        if Compiler._resolve_cross_refs(arg) is not None:
            return Skipped(
                name,
                condition.expression,
                "the condition references another fact pattern; Rego has one input document",
            )
        rendered = _rego_condition(
            reference(pattern.template, condition.slot),
            op,
            arg,
            slot_types.get(condition.slot, "string"),
        )
        if rendered is None:
            return Skipped(name, condition.expression, _why_not_exportable(op))
        body.append(rendered)

    if not body:
        return Skipped(name, "no conditions", "a rule with an empty body is unconditionally true")
    return str(rule.then.action), body


def export_engine(engine: Any, *, package: str | None = None) -> ExportResult:
    """Export the stateless subset of a loaded :class:`~fathom.engine.Engine`.

    Args:
        engine: An Engine with rules already loaded.
        package: Rego package name. Defaults to the module the rules declare.

    Returns:
        An :class:`ExportResult` holding the Rego source, the rules that were
        refused with the reason for each, and notes about what the export
        changes even where it succeeded.
    """
    registry = dict(engine.rule_registry)
    rules = list(registry.values())
    templates = dict(engine.template_registry)
    result = ExportResult(package=package or _default_package(registry))

    # Rego's `input` is the document root. When the only template in play is
    # the one `fathom convert rego` synthesises, slots sit at the root and a
    # policy round-trips to the shape it started in. Otherwise the template
    # name has to stay: two rules over different templates can never match the
    # same fact, and collapsing them onto one root would say they can.
    used = {rule.when[0].template for rule in rules if len(rule.when) == 1}
    flat = used == {"input"}

    def reference(template: str, slot: str) -> str:
        return f"input.{slot}" if flat else f"input.{template}.{slot}"

    documents: dict[str, list[tuple[Any, list[str]]]] = {}
    for rule in rules:
        exported = _export_rule(rule, templates, reference)
        if isinstance(exported, Skipped):
            result.skipped.append(exported)
            continue
        document, body = exported
        documents.setdefault(document, []).append((rule, body))
        result.rule_count += 1

    result.notes.extend(_export_notes(rules, documents))
    result.source = _render_rego(result.package, documents, flat)
    return result


def _default_package(registry: dict[str, Any]) -> str:
    """Package name from the module the rules live in.

    The registry is keyed `module::name`, which is the only place the module
    survives -- a RuleDefinition does not carry it. Rules from more than one
    module share a package here; Rego has no equivalent of focus order, so
    splitting them into separate packages would suggest an isolation the
    export does not preserve.
    """
    modules = {key.split("::", 1)[0] for key in registry if "::" in key}
    if len(modules) == 1:
        return modules.pop()
    return "fathom.exported"


def _export_notes(rules: list[Any], documents: dict[str, list[Any]]) -> list[str]:
    """What the export changes even where every rule converted."""
    notes: list[str] = []
    if len(documents) > 1:
        notes.append(
            "This policy defines "
            + ", ".join(f"`{d}`" for d in sorted(documents))
            + ". Fathom picks one decision per evaluation; Rego evaluates every "
            "document independently, so the caller decides precedence — "
            "conventionally deny wins."
        )
    if len({rule.salience for rule in rules}) > 1:
        notes.append(
            "Salience is not exported. Rego has no rule ordering, so a policy "
            "that relies on one rule firing before another does not mean the "
            "same thing here."
        )
    return notes


def _render_rego(package: str, documents: dict[str, list[Any]], flat: bool) -> str:
    """Assemble the Rego source."""
    if not documents:
        return ""
    lines = [
        "# Generated by `fathom convert to-rego`.",
        "#",
        "# The stateless subset only: rules that match one fact against literals.",
        "# Anything the exporter refused was reported on stderr, not written here.",
        "",
        f"package {package}",
        "",
        "import rego.v1",
        "",
    ]
    if not flat:
        lines[3:3] = [
            "# Slots are addressed as `input.<template>.<slot>` because this ruleset",
            "# matches more than one fact template and they must stay distinguishable.",
        ]
    for document in sorted(documents):
        lines.append(f"default {document} := false")
    lines.append("")
    for document in sorted(documents):
        for rule, body in documents[document]:
            if rule.then.reason:
                # Every line, not the first. A reason is prose and prose wraps;
                # the lines after the first used to land in the file as live
                # Rego, which OPA either rejects outright or -- when the text
                # happens to parse -- accepts as a rule the ruleset never had.
                lines.extend(f"# {line}".rstrip() for line in rule.then.reason.splitlines())
            lines.append(f"# fathom rule: {rule.name}")
            lines.append(f"{document} if {{")
            lines.extend(f"\t{expression}" for expression in body)
            lines.append("}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
