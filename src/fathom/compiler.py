"""Compiler for transforming YAML-based definitions into CLIPS constructs."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path
from pydantic import ValidationError as PydanticValidationError

from fathom.errors import CompilationError
from fathom.models import (
    FactPattern,
    FunctionDefinition,
    HierarchyDefinition,
    ModuleDefinition,
    RuleDefinition,
    RulesetDefinition,
    SlotType,
    TemplateDefinition,
    ThenBlock,
)

# Mapping from SlotType to CLIPS type strings
_CLIPS_TYPE_MAP: dict[SlotType, str] = {
    SlotType.STRING: "STRING",
    SlotType.SYMBOL: "SYMBOL",
    SlotType.FLOAT: "FLOAT",
    SlotType.INTEGER: "INTEGER",
}

# Mapping from SlotType to the CLIPS allowed-values directive name
_CLIPS_ALLOWED_MAP: dict[SlotType, str] = {
    SlotType.STRING: "allowed-strings",
    SlotType.SYMBOL: "allowed-symbols",
}


class Compiler:
    """Compiles Fathom YAML definitions into CLIPS construct strings."""

    def __init__(self) -> None:
        # Track the first hierarchy loaded for backward-compat unscoped shims
        self._first_hierarchy_name: str | None = None

    @staticmethod
    def _escape_clips_string(value: str) -> str:
        """Escape special characters for embedding in a CLIPS quoted string.

        CLIPS strings use ``"`` delimiters.  Backslashes and double-quotes
        inside the value must be escaped so CLIPS parses them correctly.

        Args:
            value: The raw Python string.

        Returns:
            The escaped string (without surrounding quotes).
        """
        # Escape backslash first, then double-quote
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _emit_slot_value(value: str) -> str:
        """Emit a slot value for a user-declared assert per FR-6.

        Emission rules:

        * Values starting with ``?`` are emitted verbatim (CLIPS variable
          reference, e.g. ``?sid``).
        * Values starting with ``(`` are emitted verbatim (CLIPS expression,
          e.g. ``(f ?a)``).
        * All other values are emitted as CLIPS-quoted string literals with
          backslashes and double-quotes escaped.

        Args:
            value: The raw slot value from an ``AssertSpec``.

        Returns:
            The CLIPS token to embed inside a slot expression.
        """
        if value.startswith("?") or value.startswith("("):
            return value
        return f'"{Compiler._escape_clips_string(value)}"'

    def compile_template(self, defn: TemplateDefinition) -> str:
        """Generate a CLIPS deftemplate string from a TemplateDefinition.

        Args:
            defn: The template definition to compile.

        Returns:
            A CLIPS deftemplate string.

        Raises:
            CompilationError: If the template name is empty or has no slots.
        """
        if not defn.name:
            raise CompilationError(
                "[fathom.compiler] compile template failed: template name cannot be empty",
                construct="template:<empty>",
            )
        if not defn.slots:
            raise CompilationError(
                f"[fathom.compiler] compile template failed: template '{defn.name}' has no slots",
                construct=f"template:{defn.name}",
            )
        lines: list[str] = [f"(deftemplate MAIN::{defn.name}"]
        for slot in defn.slots:
            parts = [f"(type {_CLIPS_TYPE_MAP[slot.type]})"]
            if slot.allowed_values is not None:
                directive = _CLIPS_ALLOWED_MAP.get(slot.type)
                if directive:
                    if slot.type == SlotType.STRING:
                        escaped = [
                            f'"{self._escape_clips_string(v)}"' for v in slot.allowed_values
                        ]
                        values_str = " ".join(escaped)
                    else:
                        values_str = " ".join(slot.allowed_values)
                    parts.append(f"({directive} {values_str})")
            if slot.default is not None:
                if slot.type == SlotType.STRING:
                    escaped_default = self._escape_clips_string(str(slot.default))
                    parts.append(f'(default "{escaped_default}")')
                else:
                    parts.append(f"(default {slot.default})")
            slot_str = f"(slot {slot.name} " + " ".join(parts) + ")"
            lines.append("    " + slot_str)
        lines.append(")")
        return "\n".join(lines)

    def compile_rule(self, defn: RuleDefinition, module: str) -> str:
        """Generate a CLIPS defrule string from a RuleDefinition.

        Args:
            defn: The rule definition to compile.
            module: The CLIPS module name to scope this rule under.

        Returns:
            A CLIPS defrule string.

        Raises:
            CompilationError: If rule name is empty, has no conditions, or
                a condition expression uses an unsupported operator.
        """
        if not defn.name:
            raise CompilationError(
                "[fathom.compiler] compile rule failed: rule name cannot be empty",
                construct="rule:<empty>",
            )
        if not defn.when:
            raise CompilationError(
                "[fathom.compiler] compile rule failed: "
                f"rule '{defn.name}' has no conditions (when)",
                construct=f"rule:{defn.name}",
            )
        full_name = f"{module}::{defn.name}"
        lines: list[str] = [f"(defrule {full_name}"]

        # Salience declaration
        if defn.salience != 0:
            lines.append(f"    (declare (salience {defn.salience}))")

        # Build alias map from fact patterns
        aliases: dict[str, str] = {}
        for pattern in defn.when:
            if pattern.alias:
                aliases[pattern.alias] = pattern.template

        # LHS: fact patterns and test CEs
        all_test_ces: list[str] = []
        for pattern in defn.when:
            lhs, test_ces = self._compile_fact_pattern(pattern, aliases)
            lines.append(f"    {lhs}")
            all_test_ces.extend(test_ces)

        # Append test CEs after all pattern CEs
        for test_ce in all_test_ces:
            lines.append(f"    {test_ce}")

        # Arrow separator
        lines.append("    =>")

        # RHS: action assertion
        rhs = self._compile_action(defn.then, full_name)
        lines.append(rhs)

        lines.append(")")
        return "\n".join(lines)

    def _compile_fact_pattern(
        self,
        pattern: FactPattern,
        aliases: dict[str, str],
    ) -> tuple[str, list[str]]:
        """Compile a FactPattern into a CLIPS LHS pattern string.

        Returns:
            A tuple of (pattern_string, list_of_test_CEs).  The test CEs
            are ``(test ...)`` strings that must appear after all pattern
            CEs on the rule LHS.
        """
        if not pattern.conditions:
            return f"({pattern.template})", []

        slot_parts: list[str] = []
        test_ces: list[str] = []
        for cond in pattern.conditions:
            # Slot is guaranteed empty here — model validator rejects slot+test-only.
            if not cond.expression and not cond.bind and cond.test is not None:
                test_ces.append(f"(test {cond.test.strip()})")
                continue
            result = self._compile_condition(
                cond.slot, cond.expression, aliases, pattern.alias, cond.bind
            )
            if isinstance(result, tuple):
                slot_parts.append(result[0])
                test_ces.append(result[1])
            else:
                slot_parts.append(result)
            if cond.test is not None:
                test_ces.append(f"(test {cond.test.strip()})")
        if not slot_parts:
            return f"({pattern.template})", test_ces
        slots_str = " ".join(slot_parts)
        return f"({pattern.template} {slots_str})", test_ces

    @staticmethod
    def _compile_reason(reason: str) -> str:
        """Compile a reason string, interpolating ``{variable}`` references.

        If the reason contains ``{variable}`` placeholders, produce a CLIPS
        ``(str-cat ...)`` expression that concatenates literal text segments
        with CLIPS variable references (``?variable``).  If no placeholders
        are present, return a simple quoted string.

        Args:
            reason: The reason string, possibly containing ``{var}`` refs.

        Returns:
            A CLIPS expression: either ``"literal"`` or
            ``(str-cat "text " ?var " more")``.
        """
        # Split on {variable} patterns, capturing the variable names
        parts = re.split(r"\{(\w+)\}", reason)
        # parts alternates: [literal, var, literal, var, ...]
        # If only one part (no variables), return quoted string
        if len(parts) == 1:
            escaped = Compiler._escape_clips_string(reason)
            return f'"{escaped}"'

        # Build str-cat arguments
        str_cat_args: list[str] = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Literal text segment
                if part:
                    escaped = Compiler._escape_clips_string(part)
                    str_cat_args.append(f'"{escaped}"')
            else:
                # Variable reference
                str_cat_args.append(f"?{part}")

        return "(str-cat " + " ".join(str_cat_args) + ")"

    def _compile_action(self, then: ThenBlock, rule_name: str) -> str:
        """Compile a ThenBlock into a CLIPS RHS assert string.

        Args:
            then: The ThenBlock from the rule definition.
            rule_name: The fully-qualified rule name (module::rulename).

        Returns:
            A CLIPS assert statement string for ``__fathom_decision``.
        """
        indent = "    "
        lines: list[str] = []

        # Emit __fathom_decision only when an action is declared (FR-7).
        # Assert-only rules (action=None) skip this block entirely.
        if then.action is not None:
            # Action is a SYMBOL (unquoted), reason is a STRING (quoted)
            action_str = then.action.value
            reason_expr = self._compile_reason(then.reason)
            log_level_str = then.log.value
            notify_str = self._escape_clips_string(
                ", ".join(then.notify) if then.notify else ""
            )
            attestation_str = "TRUE" if then.attestation else "FALSE"
            metadata_str = (
                self._escape_clips_string(json.dumps(then.metadata, sort_keys=True))
                if then.metadata
                else ""
            )
            rule_name_escaped = self._escape_clips_string(rule_name)

            lines.extend(
                [
                    f"{indent}(assert (__fathom_decision",
                    f"{indent}    (action {action_str})",
                    f"{indent}    (reason {reason_expr})",
                    f'{indent}    (rule "{rule_name_escaped}")',
                    f"{indent}    (log-level {log_level_str})",
                    f'{indent}    (notify "{notify_str}")',
                    f"{indent}    (attestation {attestation_str})",
                    f'{indent}    (metadata "{metadata_str}")))',
                ]
            )

        # Emit user-declared asserts after the decision line.  Slot values are
        # routed through ``_emit_slot_value`` so CLIPS variables (``?x``) and
        # expressions (``(f ?a)``) pass through verbatim while string literals
        # get quoted and escaped (FR-6).
        # AC-1.3: __fathom_decision MUST precede user asserts in YAML doc order.
        for spec in then.asserts:
            slot_parts = [
                f"({slot} {self._emit_slot_value(value)})"
                for slot, value in spec.slots.items()
            ]
            if slot_parts:
                lines.append(
                    f"{indent}(assert ({spec.template} " + " ".join(slot_parts) + "))"
                )
            else:
                lines.append(f"{indent}(assert ({spec.template}))")

        return "\n".join(lines)

    def compile_module(self, defn: ModuleDefinition) -> str:
        """Generate a CLIPS defmodule string from a ModuleDefinition.

        All non-MAIN modules import ``__fathom_decision`` from MAIN so that
        rules in any module can assert decision facts.

        Args:
            defn: The module definition to compile.

        Returns:
            A CLIPS defmodule string.

        Raises:
            CompilationError: If the module name is empty.
        """
        if not defn.name:
            raise CompilationError(
                "[fathom.compiler] compile module failed: module name cannot be empty",
                construct="module:<empty>",
            )
        return f"(defmodule {defn.name} (import MAIN ?ALL))"

    def compile_function(
        self,
        defn: FunctionDefinition,
        hierarchy: dict[str, HierarchyDefinition] | None = None,
    ) -> str:
        """Generate CLIPS deffunction string(s) from a FunctionDefinition.

        Args:
            defn: The function definition to compile.
            hierarchy: Mapping of hierarchy names to HierarchyDefinition
                objects. Required when ``defn.type == "classification"``.

        Returns:
            A string containing one or more CLIPS deffunctions.

        Raises:
            CompilationError: If hierarchy_ref is missing or unresolvable.
        """
        if not defn.name:
            raise CompilationError(
                "[fathom.compiler] compile function failed: function name cannot be empty",
                construct="function:<empty>",
            )
        if defn.type == "raw":
            if defn.body is None:
                raise CompilationError(
                    "[fathom.compiler] compile function failed: "
                    f"function '{defn.name}' has type 'raw' but no body",
                    construct=f"function:{defn.name}",
                )
            return defn.body

        if defn.type == "temporal":
            # Temporal functions are registered as Python external functions
            # (handled in a later task). Return empty stub.
            return ""

        # classification type
        if not defn.hierarchy_ref:
            raise CompilationError(
                "[fathom.compiler] compile function failed: "
                f"classification function '{defn.name}' requires hierarchy_ref",
                construct=f"function:{defn.name}",
            )

        # Extract hierarchy name from ref (e.g. "classification.yaml" -> "classification")
        hier_name = defn.hierarchy_ref.rsplit(".", 1)[0]

        if hierarchy is None or hier_name not in hierarchy:
            raise CompilationError(
                "[fathom.compiler] compile function failed: "
                f"hierarchy '{hier_name}' not found for function '{defn.name}'",
                construct=f"function:{defn.name}",
            )

        hier_def = hierarchy[hier_name]
        levels = hier_def.levels

        return self._compile_classification_functions(defn.name, levels)

    def compile_all_classification_functions(
        self,
        hierarchies: dict[str, HierarchyDefinition],
    ) -> str:
        """Compile classification deffunctions for multiple hierarchies.

        Iterates over all hierarchies, emitting scoped deffunctions for each.
        The first hierarchy also gets backward-compatible unscoped shims
        (``below``, ``meets-or-exceeds``, ``within-scope``).

        Args:
            hierarchies: Mapping of hierarchy names to HierarchyDefinition objects.

        Returns:
            A string containing all CLIPS deffunctions, separated by double newlines.
        """
        parts: list[str] = []
        for hier_name, hier_def in hierarchies.items():
            result = self._compile_classification_functions(hier_name, hier_def.levels)
            parts.append(result)
        return "\n\n".join(parts)

    def _compile_classification_functions(self, name: str, levels: list[str]) -> str:
        """Generate rank, below, meets-or-exceeds, within-scope deffunctions.

        Emits scoped deffunctions namespaced by hierarchy name (e.g.
        ``classification-below``, ``classification-meets-or-exceeds``) plus
        backward-compatible unscoped versions (``below``, ``meets-or-exceeds``,
        ``within-scope``) that delegate to the first loaded hierarchy.

        Args:
            name: The classification hierarchy name (e.g. "classification").
            levels: Ordered list of level names, lowest to highest.

        Returns:
            A string containing CLIPS deffunctions (scoped + optional unscoped shims).
        """
        rank_name = f"{name}-rank"

        # Build rank deffunction with switch cases
        cases: list[str] = []
        for idx, level in enumerate(levels):
            cases.append(f"        (case {level} then {idx})")
        cases_str = "\n".join(cases)

        rank_fn = (
            f"(deffunction MAIN::{rank_name} (?level)\n"
            f"    (switch ?level\n"
            f"{cases_str}\n"
            f"        (default -1)))"
        )

        # Scoped deffunctions namespaced by hierarchy name
        scoped_below = (
            f"(deffunction MAIN::{name}-below (?a ?b)\n    (< ({rank_name} ?a) ({rank_name} ?b)))"
        )

        scoped_meets = (
            f"(deffunction MAIN::{name}-meets-or-exceeds (?a ?b)\n"
            f"    (>= ({rank_name} ?a) ({rank_name} ?b)))"
        )

        scoped_scope = (
            f"(deffunction MAIN::{name}-within-scope (?a ?b)\n"
            f"    (and (>= ({rank_name} ?a) 0) (>= ({rank_name} ?b) 0)))"
        )

        parts = [rank_fn, scoped_below, scoped_meets, scoped_scope]

        # Backward-compat unscoped shims delegate to first loaded hierarchy
        if self._first_hierarchy_name is None:
            self._first_hierarchy_name = name

            below_fn = f"(deffunction MAIN::below (?a ?b)\n    ({name}-below ?a ?b))"

            meets_fn = (
                f"(deffunction MAIN::meets-or-exceeds (?a ?b)\n"
                f"    ({name}-meets-or-exceeds ?a ?b))"
            )

            scope_fn = f"(deffunction MAIN::within-scope (?a ?b)\n    ({name}-within-scope ?a ?b))"

            parts.extend([below_fn, meets_fn, scope_fn])

        return "\n\n".join(parts)

    def compile_focus_stack(self, focus_order: list[str]) -> str:
        """Generate a CLIPS focus command string from a focus order list.

        CLIPS uses push semantics for ``(focus ...)``, so the YAML order
        ``[A, B, C]`` must be reversed to ``(focus C B A)`` so that A ends
        up on top of the stack and executes first.

        Args:
            focus_order: Module names in desired execution order.

        Returns:
            A CLIPS ``(focus ...)`` command string.
        """
        reversed_names = " ".join(reversed(focus_order))
        return f"(focus {reversed_names})"

    def parse_template_file(self, path: Path) -> list[TemplateDefinition]:
        """Parse a YAML template file into TemplateDefinition objects.

        Args:
            path: Path to a YAML file containing template definitions.

        Returns:
            A list of validated TemplateDefinition objects.

        Raises:
            CompilationError: On invalid YAML, missing fields, unknown types,
                or duplicate template names.
        """
        file_str = str(path)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse template failed: invalid YAML in {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse template failed: cannot read file {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc

        if not isinstance(data, dict) or "templates" not in data:
            raise CompilationError(
                "[fathom.compiler] parse template failed: "
                "YAML file must contain a top-level 'templates' key",
                file=file_str,
            )

        raw_templates = data["templates"]
        if not isinstance(raw_templates, list):
            raise CompilationError(
                "[fathom.compiler] parse template failed: 'templates' must be a list",
                file=file_str,
            )

        results: list[TemplateDefinition] = []
        seen_names: set[str] = set()
        for idx, raw in enumerate(raw_templates):
            if not isinstance(raw, dict):
                raise CompilationError(
                    f"[fathom.compiler] parse template failed: entry {idx} is not a mapping",
                    file=file_str,
                )
            try:
                defn = TemplateDefinition(**raw)
            except PydanticValidationError as exc:
                name = raw.get("name", f"<entry {idx}>")
                raise CompilationError(
                    f"[fathom.compiler] parse template failed: invalid template '{name}'",
                    file=file_str,
                    construct=f"template:{name}",
                    detail=str(exc),
                ) from exc

            if defn.name in seen_names:
                raise CompilationError(
                    "[fathom.compiler] parse template failed: "
                    f"duplicate template name '{defn.name}'",
                    file=file_str,
                    construct=f"template:{defn.name}",
                )
            seen_names.add(defn.name)
            results.append(defn)

        return results

    def parse_rule_file(self, path: Path) -> RulesetDefinition:
        """Parse a YAML rule file into a RulesetDefinition.

        Expected YAML format::

            module: governance
            ruleset: my-rules
            version: "1.0"
            rules:
              - name: deny-test
                salience: 100
                when:
                  - template: agent
                    conditions:
                      - slot: clearance
                        expression: "equals(secret)"
                then:
                  action: deny
                  reason: "test deny"

        Args:
            path: Path to a YAML file containing rule definitions.

        Returns:
            A validated RulesetDefinition object.

        Raises:
            CompilationError: On invalid YAML, missing fields, or validation errors.
        """
        file_str = str(path)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse rules failed: invalid YAML in {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse rules failed: cannot read file {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc

        if not isinstance(data, dict) or "rules" not in data:
            raise CompilationError(
                "[fathom.compiler] parse rules failed: "
                "YAML file must contain a top-level 'rules' key",
                file=file_str,
            )

        if "module" not in data:
            raise CompilationError(
                "[fathom.compiler] parse rules failed: "
                "YAML file must contain a top-level 'module' key",
                file=file_str,
            )

        # Default ruleset name from filename stem if not provided
        ruleset_name = data.get("ruleset", path.stem)
        version = data.get("version", "1.0")

        try:
            defn = RulesetDefinition(
                ruleset=ruleset_name,
                version=str(version),
                module=data["module"],
                rules=data["rules"],
            )
        except PydanticValidationError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse rules failed: invalid ruleset in {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc

        # Check for duplicate rule names within the file
        seen_names: set[str] = set()
        for rule in defn.rules:
            if rule.name in seen_names:
                raise CompilationError(
                    f"[fathom.compiler] parse rules failed: duplicate rule name '{rule.name}'",
                    file=file_str,
                    construct=f"rule:{rule.name}",
                )
            seen_names.add(rule.name)

        return defn

    def parse_module_file(self, path: Path) -> tuple[list[ModuleDefinition], list[str]]:
        """Parse a YAML module file into ModuleDefinitions and focus order.

        Expected YAML format::

            modules:
              - name: governance
                description: ...
            focus_order:
              - classification
              - governance
              - routing

        Args:
            path: Path to a YAML file containing module definitions.

        Returns:
            A tuple of (list of ModuleDefinitions, focus_order list).

        Raises:
            CompilationError: On invalid YAML, missing keys, or validation errors.
        """
        file_str = str(path)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse module failed: invalid YAML in {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse module failed: cannot read file {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc

        if not isinstance(data, dict) or "modules" not in data:
            raise CompilationError(
                "[fathom.compiler] parse module failed: "
                "YAML file must contain a top-level 'modules' key",
                file=file_str,
            )

        raw_modules = data["modules"]
        if not isinstance(raw_modules, list):
            raise CompilationError(
                "[fathom.compiler] parse module failed: 'modules' must be a list",
                file=file_str,
            )

        results: list[ModuleDefinition] = []
        seen_names: set[str] = set()
        for idx, raw in enumerate(raw_modules):
            if not isinstance(raw, dict):
                raise CompilationError(
                    f"[fathom.compiler] parse module failed: entry {idx} is not a mapping",
                    file=file_str,
                )
            try:
                defn = ModuleDefinition(**raw)
            except PydanticValidationError as exc:
                name = raw.get("name", f"<entry {idx}>")
                raise CompilationError(
                    f"[fathom.compiler] parse module failed: invalid module '{name}'",
                    file=file_str,
                    construct=f"module:{name}",
                    detail=str(exc),
                ) from exc

            if defn.name in seen_names:
                raise CompilationError(
                    f"[fathom.compiler] parse module failed: duplicate module name '{defn.name}'",
                    file=file_str,
                    construct=f"module:{defn.name}",
                )
            seen_names.add(defn.name)
            results.append(defn)

        focus_order: list[str] = data.get("focus_order", [])
        if not isinstance(focus_order, list):
            raise CompilationError(
                "[fathom.compiler] parse module failed: 'focus_order' must be a list",
                file=file_str,
            )

        return results, focus_order

    def parse_function_file(self, path: Path) -> list[FunctionDefinition]:
        """Parse a YAML function file into FunctionDefinition objects.

        Expected YAML format::

            functions:
              - name: classification
                params: [a, b]
                hierarchy_ref: classification.yaml
                type: classification

        Args:
            path: Path to a YAML file containing function definitions.

        Returns:
            A list of validated FunctionDefinition objects.

        Raises:
            CompilationError: On invalid YAML, missing fields, or validation errors.
        """
        file_str = str(path)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse function failed: invalid YAML in {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise CompilationError(
                f"[fathom.compiler] parse function failed: cannot read file {file_str}",
                file=file_str,
                detail=str(exc),
            ) from exc

        if not isinstance(data, dict) or "functions" not in data:
            raise CompilationError(
                "[fathom.compiler] parse function failed: "
                "YAML file must contain a top-level 'functions' key",
                file=file_str,
            )

        raw_functions = data["functions"]
        if not isinstance(raw_functions, list):
            raise CompilationError(
                "[fathom.compiler] parse function failed: 'functions' must be a list",
                file=file_str,
            )

        results: list[FunctionDefinition] = []
        seen_names: set[str] = set()
        for idx, raw in enumerate(raw_functions):
            if not isinstance(raw, dict):
                raise CompilationError(
                    f"[fathom.compiler] parse function failed: entry {idx} is not a mapping",
                    file=file_str,
                )
            try:
                defn = FunctionDefinition(**raw)
            except PydanticValidationError as exc:
                name = raw.get("name", f"<entry {idx}>")
                raise CompilationError(
                    f"[fathom.compiler] parse function failed: invalid function '{name}'",
                    file=file_str,
                    construct=f"function:{name}",
                    detail=str(exc),
                ) from exc

            if defn.name in seen_names:
                raise CompilationError(
                    "[fathom.compiler] parse function failed: "
                    f"duplicate function name '{defn.name}'",
                    file=file_str,
                    construct=f"function:{defn.name}",
                )
            seen_names.add(defn.name)
            results.append(defn)

        return results

    @staticmethod
    def _parse_operator(expr: str) -> tuple[str, str]:
        """Parse an operator expression like 'equals(value)' into (op, arg).

        Args:
            expr: The expression string, e.g. ``equals(secret)``.

        Returns:
            A tuple of (operator_name, argument).

        Raises:
            CompilationError: If the expression cannot be parsed.
        """
        paren_idx = expr.find("(")
        if paren_idx == -1 or not expr.endswith(")"):
            raise CompilationError(
                "[fathom.compiler] parse condition failed: "
                f"invalid expression {expr!r}. Expected format: operator(value)",
                detail="Expected format: operator(value)",
            )
        op = expr[:paren_idx].strip()
        arg = expr[paren_idx + 1 : -1].strip()
        return op, arg

    @staticmethod
    def _parse_list_arg(arg: str) -> list[str]:
        """Parse a bracketed list argument like '[a, b, c]' into items.

        Args:
            arg: The argument string, e.g. ``[secret, top-secret]``.

        Returns:
            A list of stripped string items.

        Raises:
            CompilationError: If the argument is not a valid list.
        """
        stripped = arg.strip()
        if not stripped.startswith("[") or not stripped.endswith("]"):
            raise CompilationError(
                "[fathom.compiler] parse condition failed: "
                f"expected list argument like [a, b], got: {arg!r}",
                detail="List arguments must be enclosed in brackets",
            )
        inner = stripped[1:-1].strip()
        if not inner:
            raise CompilationError(
                "[fathom.compiler] parse condition failed: "
                "empty list argument. "
                "List arguments must contain at least one item",
                detail="List arguments must contain at least one item",
            )
        return [item.strip() for item in inner.split(",")]

    @staticmethod
    def _resolve_cross_refs(arg: str) -> str | None:
        """Resolve a ``$alias.field`` reference to a CLIPS variable name.

        If *arg* is a cross-fact reference (starts with ``$`` and contains
        a ``.``), return the CLIPS variable ``?alias-field``.  Otherwise
        return ``None`` to indicate the argument is a plain literal.

        Examples:
            ``$agent.id``  -> ``?agent-id``
            ``$data.level`` -> ``?data-level``
            ``secret``      -> ``None``
        """
        if not arg.startswith("$") or "." not in arg:
            return None
        # Strip leading '$' and split on '.'
        ref = arg[1:]  # e.g. "agent.id"
        alias, field = ref.split(".", 1)
        return f"?{alias}-{field}"

    # Classification operators that produce a slot binding + test CE
    _CLASSIFICATION_OPS: dict[str, str] = {
        "below": "below",
        "meets_or_exceeds": "meets-or-exceeds",
        "within_scope": "within-scope",
        "dominates": "fathom-dominates",
        "in_compartment": "fathom-has-compartment",
        "has_compartments": "fathom-compartments-superset",
    }

    # Temporal operators that produce test CEs calling external functions
    _TEMPORAL_OPS: set[str] = {
        "changed_within",
        "count_exceeds",
        "rate_exceeds",
        "last_n",
        "distinct_count",
        "sequence_detected",
    }

    @staticmethod
    def _inject_bind_into_pattern(slot: str, pattern: str, bind: str) -> str:
        """Inject a CLIPS bind variable into a compiled slot pattern.

        Transforms ``(slot <body>)`` into ``(slot <bind>&<body>)`` so the bind
        variable participates in the CLIPS pattern-binding chain alongside
        whatever constraint the expression already emitted. See design
        §LHS Bind Emission.
        """
        prefix = f"({slot} "
        if pattern.startswith(prefix) and pattern.endswith(")"):
            body = pattern[len(prefix) : -1]
            return f"({slot} {bind}&{body})"
        return f"({slot} {bind}&{pattern})"

    def _compile_condition(
        self,
        slot: str,
        expr: str,
        aliases: dict[str, str],
        pattern_alias: str | None = None,
        bind: str | None = None,
    ) -> str | tuple[str, str]:
        """Compile a single condition expression into CLIPS pattern syntax.

        Supported operators: ``equals``, ``not_equals``, ``greater_than``,
        ``less_than``, ``in``, ``not_in``, ``contains``, ``matches``,
        ``below``, ``meets_or_exceeds``, ``within_scope``,
        ``changed_within``, ``count_exceeds``, ``rate_exceeds``,
        ``last_n``, ``distinct_count``, ``sequence_detected``.

        Args:
            slot: The slot name in the template.
            expr: The condition expression, e.g. ``equals(secret)``.
            aliases: Mapping of alias names to template names (unused for
                basic operators but needed for cross-reference operators).
            pattern_alias: The ``$alias`` of the enclosing fact pattern,
                used to generate variable names for classification ops.
            bind: Optional LHS bind variable (``?name``) to capture the
                slot's value. See design §LHS Bind Emission.

        Returns:
            A CLIPS slot constraint string, or a tuple of
            ``(slot_binding, test_CE)`` for classification operators.

        Raises:
            CompilationError: If the operator is unsupported.
        """
        # Case A: bind only, no expression -> emit straight slot-variable binding.
        if bind is not None and not expr:
            return f"({slot} {bind})"

        # Case B: bind + expression -> compile the expression normally, then
        # inject ``{bind}&`` into the slot-pattern body so the bind variable
        # participates in the CLIPS pattern-binding chain.
        if bind is not None:
            inner = self._compile_condition(slot, expr, aliases, pattern_alias)
            if isinstance(inner, tuple):
                return self._inject_bind_into_pattern(slot, inner[0], bind), inner[1]
            return self._inject_bind_into_pattern(slot, inner, bind)

        # Case C: expression only -> existing path unchanged.
        op, arg = self._parse_operator(expr)

        # Classification operators: below, meets_or_exceeds, within_scope
        if op in self._CLASSIFICATION_OPS:
            clips_fn = self._CLASSIFICATION_OPS[op]
            # Build variable name for the slot value
            alias_prefix = pattern_alias.lstrip("$") if pattern_alias else "v"
            slot_var = f"?{alias_prefix}-{slot}"
            # Resolve the argument (cross-ref or literal)
            cross_ref = self._resolve_cross_refs(arg)
            arg_var = cross_ref if cross_ref is not None else arg
            slot_binding = f"({slot} {slot_var})"
            test_ce = f"(test ({clips_fn} {slot_var} {arg_var}))"
            return slot_binding, test_ce

        # Temporal operators: changed_within, count_exceeds, rate_exceeds
        if op in self._TEMPORAL_OPS:
            return self._compile_temporal_condition(op, arg, slot, pattern_alias)

        # Check for cross-fact variable reference ($alias.field)
        cross_ref = self._resolve_cross_refs(arg)

        # Use slot-specific variable name to avoid CLIPS binding conflicts
        # when multiple conditions in the same rule use constraint bindings.
        slot_var = f"?s_{slot}"

        if op == "equals":
            if cross_ref is not None:
                return f"({slot} {cross_ref})"
            # Empty arg means match empty string ""
            if not arg:
                return f'({slot} "")'
            # Simple symbol literal: direct pattern match
            return f"({slot} {arg})"
        elif op == "not_equals":
            if cross_ref is not None:
                return f"({slot} {slot_var}&:(neq {slot_var} {cross_ref}))"
            return f"({slot} {slot_var}&:(neq {slot_var} {arg}))"
        elif op == "greater_than":
            if cross_ref is not None:
                return f"({slot} {slot_var}&:(> {slot_var} {cross_ref}))"
            return f"({slot} {slot_var}&:(> {slot_var} {arg}))"
        elif op == "less_than":
            if cross_ref is not None:
                return f"({slot} {slot_var}&:(< {slot_var} {cross_ref}))"
            return f"({slot} {slot_var}&:(< {slot_var} {arg}))"
        elif op == "in":
            items = self._parse_list_arg(arg)
            or_clauses = " ".join(f"(eq {slot_var} {item})" for item in items)
            return f"({slot} {slot_var}&:(or {or_clauses}))"
        elif op == "not_in":
            items = self._parse_list_arg(arg)
            negations = "".join(f"&~{item}" for item in items)
            return f"({slot} {slot_var}{negations})"
        elif op == "contains":
            return f"({slot} {slot_var}&:(str-index {arg} {slot_var}))"
        elif op == "matches":
            escaped_arg = self._escape_clips_string(arg)
            return f'({slot} {slot_var}&:(fathom-matches {slot_var} "{escaped_arg}"))'
        else:
            raise CompilationError(
                "[fathom.compiler] compile rule failed: "
                f"unsupported condition operator {op!r} in expression: {expr}",
                detail=f"Expression: {expr}",
            )

    @staticmethod
    def _compile_temporal_condition(
        op: str,
        arg: str,
        slot: str,
        pattern_alias: str | None,
    ) -> tuple[str, str]:
        """Compile a temporal operator into a slot binding + test CE.

        Temporal operators:
        - ``changed_within(window)`` → ``(test (fathom-changed-within ?var window))``
        - ``count_exceeds(template, slot, value, threshold)`` →
          ``(test (fathom-count-exceeds "template" "slot" "value" threshold))``
        - ``rate_exceeds(template, slot, value, threshold, window[, timestamp_slot])`` →
          ``(test (fathom-rate-exceeds "template" "slot" "value" threshold window "ts_slot"))``
          Optional ``timestamp_slot`` defaults to ``ts``.
        - ``last_n(template, slot, value, n)`` →
          ``(test (fathom-last-n "template" "slot" "value" n))``
        - ``distinct_count(template, group_slot, count_slot, threshold)`` →
          ``(test (fathom-distinct-count "template" "group_slot" "count_slot" threshold))``
        - ``sequence_detected(events_json, window_seconds)`` →
          ``(test (fathom-sequence-detected "events_json" window_seconds))``

        Args:
            op: The temporal operator name.
            arg: The comma-separated arguments string.
            slot: The slot name in the template.
            pattern_alias: The ``$alias`` of the enclosing fact pattern.

        Returns:
            A tuple of ``(slot_binding, test_CE)``.
        """
        alias_prefix = pattern_alias.lstrip("$") if pattern_alias else "v"
        slot_var = f"?{alias_prefix}-{slot}"
        slot_binding = f"({slot} {slot_var})"

        if op == "changed_within":
            # changed_within(window) — single numeric arg
            window = arg.strip()
            test_ce = f"(test (fathom-changed-within {slot_var} {window}))"
            return slot_binding, test_ce

        # Parse comma-separated args for count_exceeds / rate_exceeds
        args = [a.strip() for a in arg.split(",")]

        if op == "count_exceeds":
            # count_exceeds(template, slot, value, threshold)
            # First 3 args are strings (quoted), last is numeric
            tmpl, slot_arg, value, threshold = args[0], args[1], args[2], args[3]
            tmpl_e = Compiler._escape_clips_string(tmpl)
            slot_e = Compiler._escape_clips_string(slot_arg)
            value_e = Compiler._escape_clips_string(value)
            test_ce = (
                f'(test (fathom-count-exceeds "{tmpl_e}" "{slot_e}" "{value_e}" {threshold}))'
            )
            return slot_binding, test_ce

        if op == "rate_exceeds":
            # rate_exceeds(template, slot, value, threshold, window[, timestamp_slot])
            # First 3 args are strings (quoted), last 2 numeric, optional 6th string
            tmpl, slot_arg, value, threshold, window = (
                args[0],
                args[1],
                args[2],
                args[3],
                args[4],
            )
            ts_slot = args[5] if len(args) > 5 else "ts"
            tmpl_e = Compiler._escape_clips_string(tmpl)
            slot_e = Compiler._escape_clips_string(slot_arg)
            value_e = Compiler._escape_clips_string(value)
            ts_slot_e = Compiler._escape_clips_string(ts_slot)
            test_ce = (
                f'(test (fathom-rate-exceeds "{tmpl_e}" "{slot_e}" "{value_e}"'
                f' {threshold} {window} "{ts_slot_e}"))'
            )
            return slot_binding, test_ce

        if op == "last_n":
            # last_n(template, slot, value, n)
            # First 3 args are strings (quoted), last is numeric
            tmpl, slot_arg, value, n = args[0], args[1], args[2], args[3]
            tmpl_e = Compiler._escape_clips_string(tmpl)
            slot_e = Compiler._escape_clips_string(slot_arg)
            value_e = Compiler._escape_clips_string(value)
            test_ce = f'(test (fathom-last-n "{tmpl_e}" "{slot_e}" "{value_e}" {n}))'
            return slot_binding, test_ce

        if op == "distinct_count":
            # distinct_count(template, group_slot, count_slot, threshold)
            # First 3 args are strings (quoted), last is numeric
            tmpl, group_slot, count_slot, threshold = (
                args[0],
                args[1],
                args[2],
                args[3],
            )
            tmpl_e = Compiler._escape_clips_string(tmpl)
            group_e = Compiler._escape_clips_string(group_slot)
            count_e = Compiler._escape_clips_string(count_slot)
            test_ce = (
                f'(test (fathom-distinct-count "{tmpl_e}" "{group_e}" "{count_e}" {threshold}))'
            )
            return slot_binding, test_ce

        # sequence_detected(events_json, window_seconds)
        # First arg is a JSON string (quoted), second is numeric
        events_json, window_seconds = args[0], args[1]
        events_e = Compiler._escape_clips_string(events_json)
        test_ce = f'(test (fathom-sequence-detected "{events_e}" {window_seconds}))'
        return slot_binding, test_ce
