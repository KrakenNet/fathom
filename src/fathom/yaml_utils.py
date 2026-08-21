"""YAML validation behind the CLI ``validate`` command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from fathom.models import (
    FunctionDefinition,
    HierarchyDefinition,
    ModuleDefinition,
    RuleDefinition,
    RulesetDefinition,
    TemplateDefinition,
)


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
    elif "functions" in data:
        for idx, raw in _list_entries(data["functions"], "functions", file_path, errors):
            try:
                FunctionDefinition(**raw)
            except PydanticValidationError as exc:
                errors.extend(
                    _format_errors(exc, "function", file_path, f"functions -> {idx} -> ")
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
