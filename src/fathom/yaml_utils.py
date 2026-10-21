"""Strict YAML loading, and the validation behind the CLI ``validate`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from fathom.models import (
    FunctionDefinition,
    HierarchyDefinition,
    ModuleDefinition,
    RuleDefinition,
    RulesetDefinition,
    TemplateDefinition,
)

#: The keys each kind of YAML file may hold at its top level. The models
#: inside are `extra="forbid"`, but the file around them was not checked, so
#: a misspelled `focus_order:` was dropped and declaration order used instead.
TOP_LEVEL_KEYS: dict[str, frozenset[str]] = {
    "templates": frozenset({"templates"}),
    "modules": frozenset({"modules", "focus_order"}),
    "functions": frozenset({"functions", "hierarchies"}),
    "rules": frozenset({"ruleset", "version", "module", "rules"}),
}


def unknown_top_level_keys(data: dict[str, Any], kind: str) -> str | None:
    """Describe the keys of *data* a *kind* file may not hold, or None."""
    unknown = sorted(str(key) for key in data if key not in TOP_LEVEL_KEYS[kind])
    if not unknown:
        return None
    noun = "key" if len(unknown) == 1 else "keys"
    return (
        f"unknown top-level {noun} {', '.join(repr(k) for k in unknown)} in a {kind} file "
        f"(allowed: {', '.join(sorted(TOP_LEVEL_KEYS[kind]))})"
    )


def file_kind(data: dict[str, Any]) -> str | None:
    """Name the kind of Fathom file *data* holds by its top-level keys, or None."""
    if "templates" in data:
        return "templates"
    if "modules" in data or "focus_order" in data:
        return "modules"
    if "functions" in data:
        return "functions"
    if "rules" in data or "ruleset" in data:
        return "rules"
    return None


class _StrictLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that rejects a mapping key given twice.

    PyYAML keeps the last of two equal keys, so a condition holding
    ``expression: not_equals(admin)`` and then ``expression: equals(admin)``
    compiled as the second, which reverses the rule. A ``<<`` merge is not a
    duplicate: overriding a merged key is what merging is for.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)  # type: ignore[no-untyped-call]
            try:
                duplicate = key in seen
            except TypeError:
                continue  # unhashable: the base class rejects it
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def safe_load(stream: Any) -> Any:
    """``yaml.safe_load`` that rejects duplicate mapping keys.

    Every place Fathom parses user YAML goes through this or
    :func:`safe_load_all`. The error is a ``yaml.YAMLError``, so callers
    report it as they report any other invalid YAML.
    """
    return yaml.load(stream, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass


def safe_load_all(stream: Any) -> list[Any]:
    """``yaml.safe_load_all`` that rejects duplicate mapping keys."""
    return list(yaml.load_all(stream, Loader=_StrictLoader))  # noqa: S506 - SafeLoader subclass


def _format_errors(
    exc: PydanticValidationError,
    kind: str,
    file_path: Path,
    loc_prefix: str = "",
) -> list[str]:
    """Render a pydantic error set as ``<file>: <kind> validation error ...`` lines."""
    messages: list[str] = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"])
        messages.append(f"{file_path}: {kind} validation error at {loc_prefix}{loc}: {err['msg']}")
    return messages


def _list_entries(
    value: Any,
    key: str,
    file_path: Path,
    errors: list[str],
) -> list[tuple[int, dict[str, Any]]]:
    """Return the ``(index, mapping)`` entries of a top-level list key."""
    if not isinstance(value, list):
        errors.append(f"{file_path}: '{key}' must be a list")
        return []
    entries: list[tuple[int, dict[str, Any]]] = []
    for idx, raw in enumerate(value):
        if not isinstance(raw, dict):
            errors.append(f"{file_path}: '{key}' entry {idx} is not a mapping")
        else:
            entries.append((idx, raw))
    return entries


def _validate_rule_file(data: dict[str, Any], file_path: Path) -> list[str]:
    """Validate a rule file the way the loader does, not just the way pydantic does.

    Re-deriving the shape from the pydantic models alone left ``validate``
    blind to every check that lives OUTSIDE the models, so
    ``fathom validate`` exited 0 on files ``Engine.from_rules`` rejects — a
    missing ``module:`` key, a duplicate rule name, an empty ``when: []``, an
    unknown operator, a temporal operator with the wrong arity. That is worse
    than no validation: it tells an author their ruleset is fine when
    deploying it will fail.

    So this mirrors :meth:`Compiler.parse_rule_file` and then actually
    compiles each rule with :meth:`Compiler.compile_rule`, which is where
    those checks live. Compilation here is throw-away — the CLIPS string is
    discarded; we only want the errors.

    Type-dependent literal emission needs the ruleset's templates, which a
    single-file check does not have. That only affects *how* a literal is
    rendered, never whether the rule is well-formed, so compiling without
    them is sound for validation purposes.
    """
    from fathom.compiler import Compiler
    from fathom.errors import CompilationError

    errors: list[str] = []

    if "module" not in data:
        errors.append(f"{file_path}: rule file must contain a top-level 'module' key")
        return errors

    try:
        ruleset = RulesetDefinition(
            ruleset=data.get("ruleset", file_path.stem),
            version=str(data.get("version", "1.0")),
            module=data["module"],
            rules=data["rules"],
        )
    except PydanticValidationError as exc:
        return _format_errors(exc, "ruleset", file_path)

    seen: set[str] = set()
    compiler = Compiler()
    for rule in ruleset.rules:
        if rule.name in seen:
            errors.append(f"{file_path}: duplicate rule name '{rule.name}'")
            continue
        seen.add(rule.name)
        try:
            compiler.compile_rule(rule, ruleset.module)
        except CompilationError as exc:
            detail = f" ({exc.detail})" if getattr(exc, "detail", None) else ""
            errors.append(f"{file_path}: rule '{rule.name}': {exc}{detail}")

    return errors


def template_slots_in(data: Any) -> dict[str, set[str]]:
    """Slot names of each template a ``templates:`` document declares, by template name."""
    if not isinstance(data, dict) or not isinstance(data.get("templates"), list):
        return {}
    return {
        t["name"]: {
            s["name"]
            for s in (t["slots"] if isinstance(t.get("slots"), list) else [])
            if isinstance(s, dict) and isinstance(s.get("name"), str)
        }
        for t in data["templates"]
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    }


def unregistered_template_errors(
    data: dict[str, Any],
    templates: dict[str, set[str]],
    file_path: Path,
) -> list[str]:
    """Rules in *data* that name a template or slot not in *templates*.

    *templates* maps each template name to its slot names. The loader rejects
    these (``Engine._unregistered_templates_error``); a pattern with no slot
    constraint on a misspelled template would otherwise build and never match.
    ``then.assert`` targets and temporal operator arguments are checked too
    (see :meth:`fathom.compiler.Compiler.template_references`). Needs the
    pack's templates, so ``fathom validate`` calls it once every file has
    been read.
    """
    from fathom.compiler import Compiler  # imports this module

    errors: list[str] = []
    rules = data.get("rules")
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict) or not isinstance(rule.get("when"), list):
            continue
        for pattern in rule["when"]:
            name = pattern.get("template") if isinstance(pattern, dict) else None
            if isinstance(name, str) and name not in templates:
                errors.append(
                    f"{file_path}: rule '{rule.get('name')}' matches template "
                    f"'{name}', which is not registered"
                )
        try:
            refs = Compiler.template_references(RuleDefinition(**rule))
        except (PydanticValidationError, TypeError):
            continue  # validate_document reports the malformed rule
        for template, slot, where in refs:
            if template not in templates:
                problem = f"template '{template}', which is not registered"
            elif slot is not None and slot not in templates[template]:
                problem = f"slot '{slot}' of template '{template}', which it does not declare"
            else:
                continue
            errors.append(f"{file_path}: rule '{rule.get('name')}' names {problem} (in {where})")
    return errors


def validate_document(
    data: dict[str, Any],
    file_path: Path,
) -> list[str]:
    """Validate a single YAML document against known Fathom models.

    Dispatches on the same top-level keys :class:`fathom.compiler.Compiler`
    parses (``templates``, ``modules``, ``functions``, ``rules`` + ``module``,
    and hierarchy files), so a file that fails to compile also fails to
    validate.  The single-model shapes accepted by earlier releases
    (a bare template, rule, or module mapping) still validate.

    Returns a list of error strings (empty on success).
    """
    errors: list[str] = []

    kind = file_kind(data)
    unknown = unknown_top_level_keys(data, kind) if kind else None
    if unknown:
        errors.append(f"{file_path}: {unknown}")

    if "templates" in data:
        for idx, raw in _list_entries(data["templates"], "templates", file_path, errors):
            try:
                TemplateDefinition(**raw)
            except PydanticValidationError as exc:
                errors.extend(
                    _format_errors(exc, "template", file_path, f"templates -> {idx} -> ")
                )
    elif "modules" in data:
        for idx, raw in _list_entries(data["modules"], "modules", file_path, errors):
            try:
                ModuleDefinition(**raw)
            except PydanticValidationError as exc:
                errors.extend(_format_errors(exc, "module", file_path, f"modules -> {idx} -> "))
        if "focus_order" in data and not isinstance(data["focus_order"], list):
            errors.append(f"{file_path}: 'focus_order' must be a list")
    elif "focus_order" in data:
        # The loader reads focus_order only beside the modules it orders.
        errors.append(
            f"{file_path}: 'focus_order' needs a top-level 'modules' key in the same file"
        )
    elif "functions" in data:
        for idx, raw in _list_entries(data["functions"], "functions", file_path, errors):
            try:
                FunctionDefinition(**raw)
            except PydanticValidationError as exc:
                errors.extend(
                    _format_errors(exc, "function", file_path, f"functions -> {idx} -> ")
                )
        for idx, raw in _list_entries(
            data.get("hierarchies", []), "hierarchies", file_path, errors
        ):
            try:
                HierarchyDefinition(**raw)
            except PydanticValidationError as exc:
                errors.extend(
                    _format_errors(exc, "hierarchy", file_path, f"hierarchies -> {idx} -> ")
                )
    elif "rules" in data:
        errors.extend(_validate_rule_file(data, file_path))
    elif "levels" in data and "name" in data:
        try:
            HierarchyDefinition(**data)
        except PydanticValidationError as exc:
            errors.extend(_format_errors(exc, "hierarchy", file_path))
    elif "ruleset" in data:
        try:
            RulesetDefinition(**data)
        except PydanticValidationError as exc:
            errors.extend(_format_errors(exc, "ruleset", file_path))
    elif "slots" in data:
        try:
            TemplateDefinition(**data)
        except PydanticValidationError as exc:
            errors.extend(_format_errors(exc, "template", file_path))
    elif "when" in data and "then" in data:
        try:
            RuleDefinition(**data)
        except PydanticValidationError as exc:
            errors.extend(_format_errors(exc, "rule", file_path))
    elif "name" in data and not data.get("params"):
        try:
            ModuleDefinition(**data)
        except PydanticValidationError as exc:
            errors.extend(_format_errors(exc, "module", file_path))

    return errors
