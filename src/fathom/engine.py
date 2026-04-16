"""Fathom Engine — core runtime wrapping a clipspy CLIPS Environment."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import clips
import yaml

from fathom.audit import AuditLog, AuditSink, NullSink
from fathom.compiler import Compiler
from fathom.errors import CompilationError, ScopeError
from fathom.evaluator import Evaluator
from fathom.facts import FactManager
from fathom.metrics import MetricsCollector
from fathom.models import HierarchyDefinition

if TYPE_CHECKING:
    from collections.abc import Callable

    from fathom.attestation import AttestationService
    from fathom.models import (
        AssertedFact,
        EvaluationResult,
        ModuleDefinition,
        RuleDefinition,
        TemplateDefinition,
    )


# Reserved prefix for fathom-internal CLIPS functions (see Engine.register_function).
RESERVED_FUNCTION_PREFIX = "fathom-"

# Max regex pattern/input length for fathom-matches — bounds catastrophic
# backtracking without adopting a full re2 dependency (see Sec-M6).
_FATHOM_MATCHES_MAX_LEN = 4096

# User-registered CLIPS function names: restrict to the same ASCII subset
# CLIPS itself accepts, so a crafted name cannot inject construct-breaking
# characters into the CLIPS symbol table.
_USER_FN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


# CLIPS deftemplate built on every Engine init (design.md Section 6.1)
_DECISION_TEMPLATE = (
    "(deftemplate MAIN::__fathom_decision"
    "    (slot action (type SYMBOL) (allowed-symbols allow deny escalate scope route))"
    '    (slot reason (type STRING) (default ""))'
    '    (slot rule (type STRING) (default ""))'
    "    (slot log-level (type SYMBOL) (allowed-symbols none summary full) (default summary))"
    '    (slot notify (type STRING) (default ""))'
    "    (slot attestation (type SYMBOL) (allowed-symbols TRUE FALSE) (default FALSE))"
    '    (slot metadata (type STRING) (default "")))'
)


# ---------------------------------------------------------------------------
# Compartment helpers — pure functions, testable in isolation
# ---------------------------------------------------------------------------


def parse_compartments(comps_str: str) -> list[str]:
    """Split a pipe-delimited compartment string into a list of names."""
    s = str(comps_str).strip()
    if not s:
        return []
    return [c.strip() for c in s.split("|") if c.strip()]


def has_compartment(subject_comps: str, required_comp: str) -> bool:
    """Return True if *required_comp* appears in the pipe-delimited *subject_comps*."""
    return str(required_comp).strip() in parse_compartments(subject_comps)


def compartments_superset(subject_comps: str, required_comps: str) -> bool:
    """Return True if every compartment in *required_comps* is present in *subject_comps*."""
    subject_set = set(parse_compartments(subject_comps))
    required_set = set(parse_compartments(required_comps))
    return required_set.issubset(subject_set)


def _diff_user_facts(
    pre: list[AssertedFact],
    post: list[AssertedFact],
) -> list[AssertedFact]:
    """Return facts present in *post* but not in *pre*.

    Equality is computed on a hashable key ``(template, tuple(sorted(slots.items())))``
    so order-insensitive dict comparison is supported. Preserves the order of
    new facts as they appear in *post*.
    """

    def _key(fact: AssertedFact) -> tuple[str, tuple[tuple[str, Any], ...]]:
        return (fact.template, tuple(sorted(fact.slots.items())))

    pre_keys = {_key(f) for f in pre}
    return [f for f in post if _key(f) not in pre_keys]


def dominates(
    level_a: str,
    comps_a: str,
    level_b: str,
    comps_b: str,
    hierarchy_name: str,
    hierarchy_registry: dict[str, HierarchyDefinition],
) -> bool:
    """Bell-LaPadula dominance check.

    Returns True when the subject (*level_a*, *comps_a*) dominates the
    object (*level_b*, *comps_b*) according to the named hierarchy.
    """
    hier_def = hierarchy_registry.get(str(hierarchy_name))
    if hier_def is None:
        return False
    levels = hier_def.levels
    la = str(level_a)
    lb = str(level_b)
    rank_a = levels.index(la) if la in levels else -1
    rank_b = levels.index(lb) if lb in levels else -1
    if rank_a < rank_b:
        return False
    return compartments_superset(str(comps_a), str(comps_b))


class Engine:
    """Deterministic reasoning engine backed by CLIPS."""

    def __init__(
        self,
        default_decision: str | None = "deny",
        audit_sink: AuditSink | None = None,
        session_id: str | None = None,
        experimental_backward_chaining: bool = False,
        attestation_service: AttestationService | None = None,
        metrics: bool = False,
    ) -> None:
        """Initialise a new Engine instance.

        Args:
            default_decision: Decision returned when no rule fires.
                Defaults to ``"deny"`` (fail-closed). Set to ``None``
                to leave the decision unset.
            audit_sink: Pluggable sink for audit records. Defaults to
                :class:`NullSink` (no-op).
            session_id: Optional session identifier. A random UUID is
                generated when omitted.
            experimental_backward_chaining: Enable experimental
                backward-chaining support. Default ``False``.
            attestation_service: Optional attestation service for signing
                evaluation results. When provided, all evaluation results
                are signed with an Ed25519 JWT token.
            metrics: Enable Prometheus metrics collection. Falls back
                to ``FATHOM_METRICS=1`` environment variable when
                ``False``.
        """
        self._env: clips.Environment = clips.Environment()
        self._session_id: str = session_id or str(uuid4())
        self._default_decision: str | None = default_decision
        self._template_registry: dict[str, TemplateDefinition] = {}
        self._module_registry: dict[str, ModuleDefinition] = {}
        self._rule_registry: dict[str, RuleDefinition] = {}
        self._has_asserting_rules: bool = False
        self._hierarchy_registry: dict[str, HierarchyDefinition] = {}
        self._focus_order: list[str] = []

        # Placeholders for subsystems (wired up in later tasks)
        self._compiler = Compiler()
        self._fact_manager = FactManager(self._env, self._template_registry)
        self._evaluator = Evaluator(
            self._env,
            self._default_decision,
            self._focus_order,
            fact_manager=self._fact_manager,
        )
        self._audit_log = AuditLog(audit_sink or NullSink())
        self._experimental_backward_chaining = experimental_backward_chaining
        if experimental_backward_chaining:
            import warnings

            warnings.warn(
                "Backward chaining is experimental and may change in future versions.",
                stacklevel=2,
            )
        self._attestation_service = attestation_service

        # Metrics collector (no-op when disabled or prometheus_client absent)
        metrics = metrics or os.getenv("FATHOM_METRICS") == "1"
        self._metrics = MetricsCollector(enabled=metrics)

        # Build the decision template into the CLIPS environment
        self._safe_build(_DECISION_TEMPLATE, context="__fathom_decision")

        # Register Python external functions into CLIPS
        self._register_external_functions()

    # --- Public property accessors ---

    @property
    def template_registry(self) -> dict[str, TemplateDefinition]:
        """Read-only view of registered template definitions."""
        return self._template_registry

    @property
    def module_registry(self) -> dict[str, ModuleDefinition]:
        """Read-only view of registered module definitions."""
        return self._module_registry

    @property
    def rule_registry(self) -> dict[str, RuleDefinition]:
        """Read-only view of loaded rule definitions, keyed by rule name."""
        return self._rule_registry

    @property
    def focus_order(self) -> list[str]:
        """Ordered list of module names that control evaluation focus."""
        return list(self._focus_order)

    def set_focus(self, modules: list[str]) -> None:
        """Replace the focus order for evaluation.

        Must be called with modules that are already registered. Replaces
        the private reach-through ``engine._evaluator._focus_order = ...``.

        Validation is skipped when no modules have been loaded yet (the module
        registry is empty), allowing pre-load focus configuration.
        """
        if self._module_registry:
            unknown = [m for m in modules if m and m not in self._module_registry]
            if unknown:
                raise ValueError(f"unknown modules in focus order: {unknown}")
        self._focus_order = list(modules)
        self._evaluator.set_focus_order(modules)

    # --- Internal helpers ---

    def _safe_build(self, clips_str: str, context: str = "") -> None:
        """Build a CLIPS construct, wrapping CLIPSError as CompilationError."""
        try:
            self._env.build(clips_str)
        except Exception as exc:
            raise CompilationError(
                f"[fathom.engine] CLIPS build failed: {exc}",
                construct=context,
                detail=str(exc),
            ) from exc

    # --- External functions ---

    def _register_external_functions(self) -> None:
        """Register Python external functions callable from CLIPS rules."""
        env = self._env

        # fathom-matches(str, pattern) — regex search via re.search()
        def fathom_matches(string_value: str, pattern: str) -> bool:
            """Return True when *pattern* matches *string_value* via re.search.

            Pattern is passed verbatim to Python's ``re`` engine. To bound
            catastrophic backtracking, both the pattern and the input are
            capped at ``_FATHOM_MATCHES_MAX_LEN`` characters. Longer inputs
            raise ``ValueError`` — rule authors must pre-truncate or pick a
            more selective slot. With server auth enabled, patterns come
            from trusted rule authors; the cap is belt-and-braces.
            """
            p = str(pattern)
            s = str(string_value)
            if len(p) > _FATHOM_MATCHES_MAX_LEN or len(s) > _FATHOM_MATCHES_MAX_LEN:
                raise ValueError(
                    "fathom-matches input exceeds "
                    f"{_FATHOM_MATCHES_MAX_LEN}-char safety cap"
                )
            return bool(re.search(p, s))

        env.define_function(fathom_matches, "fathom-matches")

        # fathom-count-exceeds(template, slot, value, threshold) — count matching facts
        def fathom_count_exceeds(
            template_name: str,
            slot_name: str,
            slot_value: str,
            threshold: int,
        ) -> bool:
            tmpl = env.find_template(str(template_name))
            count = sum(1 for f in tmpl.facts() if str(f[str(slot_name)]) == str(slot_value))
            return count > int(threshold)

        env.define_function(fathom_count_exceeds, "fathom-count-exceeds")

        # fathom-rate-exceeds — count within time window
        # args: template, slot, value, threshold, window, ts_slot
        def fathom_rate_exceeds(
            template_name: str,
            slot_name: str,
            slot_value: str,
            threshold: int,
            window_seconds: float,
            timestamp_slot: str = "ts",
        ) -> bool:
            tmpl = env.find_template(str(template_name))
            current = time.time()
            count = sum(
                1
                for f in tmpl.facts()
                if str(f[str(slot_name)]) == str(slot_value)
                and (current - float(f[str(timestamp_slot)])) < float(window_seconds)
            )
            return count > int(threshold)

        env.define_function(fathom_rate_exceeds, "fathom-rate-exceeds")

        # fathom-changed-within(timestamp, window) — checks timestamp recency
        def fathom_changed_within(timestamp_value: float, window_seconds: float) -> bool:
            current = time.time()
            return (current - float(timestamp_value)) < float(window_seconds)

        env.define_function(fathom_changed_within, "fathom-changed-within")

        # Compartment functions — delegate to module-level helpers
        env.define_function(parse_compartments, "fathom-parse-compartments")
        env.define_function(has_compartment, "fathom-has-compartment")
        env.define_function(compartments_superset, "fathom-compartments-superset")

        # fathom-dominates needs access to hierarchy_registry via closure
        hierarchy_registry = self._hierarchy_registry

        def fathom_dominates(
            level_a: str,
            comps_a: str,
            level_b: str,
            comps_b: str,
            hierarchy: str,
        ) -> bool:
            return dominates(level_a, comps_a, level_b, comps_b, hierarchy, hierarchy_registry)

        env.define_function(fathom_dominates, "fathom-dominates")

        # fathom-last-n(template, slot, value, n) — true if >= N matching facts
        def fathom_last_n(
            template_name: str,
            slot_name: str,
            slot_value: str,
            n: int,
        ) -> bool:
            tmpl = env.find_template(str(template_name))
            count = sum(1 for f in tmpl.facts() if str(f[str(slot_name)]) == str(slot_value))
            return count >= int(n)

        env.define_function(fathom_last_n, "fathom-last-n")

        # fathom-distinct-count(template, group_slot, count_slot, threshold)
        # — true if unique values of count_slot > threshold
        def fathom_distinct_count(
            template_name: str,
            group_slot: str,
            count_slot: str,
            threshold: int,
        ) -> bool:
            tmpl = env.find_template(str(template_name))
            groups: dict[str, set[str]] = {}
            for f in tmpl.facts():
                key = str(f[str(group_slot)])
                val = str(f[str(count_slot)])
                groups.setdefault(key, set()).add(val)
            return any(len(vals) > int(threshold) for vals in groups.values())

        env.define_function(fathom_distinct_count, "fathom-distinct-count")

        # fathom-sequence-detected(events_json, window_seconds)
        # — detect ordered event pattern within a time window
        def fathom_sequence_detected(
            events_json: str,
            window_seconds: float,
        ) -> bool:
            events = json.loads(str(events_json))
            # Collect all candidate timestamps for each event spec.
            per_event_timestamps: list[list[float]] = []
            for event_spec in events:
                tmpl = env.find_template(event_spec["template"])
                ts_slot = event_spec.get("slot_ts", "ts")
                candidates = [
                    float(f[ts_slot])
                    for f in tmpl.facts()
                    if str(f[event_spec["slot"]]) == event_spec["value"]
                ]
                if not candidates:
                    return False
                candidates.sort()
                per_event_timestamps.append(candidates)

            # Greedy ordered pick: for each event i, take the earliest timestamp
            # that is strictly greater than the one chosen for event i-1.
            chosen: list[float] = []
            for timestamps in per_event_timestamps:
                if not chosen:
                    chosen.append(timestamps[0])
                    continue
                last = chosen[-1]
                next_ts = next((t for t in timestamps if t > last), None)
                if next_ts is None:
                    return False
                chosen.append(next_ts)

            current = time.time()
            return (current - chosen[0]) < float(window_seconds)

        env.define_function(fathom_sequence_detected, "fathom-sequence-detected")

    # --- Class methods ---

    @classmethod
    def from_rules(cls, path: str, **kwargs: Any) -> Engine:
        """Load rules from a path and return a configured Engine.

        Discovery strategies (tried in order):

        1. **Subdirectory convention** — if *path* contains ``templates/``,
           ``modules/``, ``functions/``, or ``rules/`` subdirectories, each
           is loaded with the corresponding ``load_*`` method.
        2. **Key inspection fallback** — if no recognised subdirectories
           exist, every ``*.yaml`` file under *path* is opened and its
           top-level key determines the loader (``templates``, ``modules``,
           ``functions``, ``rules``/``ruleset``).

        Loading order (both strategies): templates → modules → functions → rules.

        Args:
            path: Directory containing rule definitions.
            **kwargs: Forwarded to :class:`Engine` constructor.

        Returns:
            A fully-loaded :class:`Engine` instance.
        """
        engine = cls(**kwargs)
        p = Path(path)

        templates_dir = p / "templates"
        modules_dir = p / "modules"
        functions_dir = p / "functions"
        rules_dir = p / "rules"

        # Strategy 1: subdirectory convention
        has_subdirs = any(
            d.is_dir() for d in [templates_dir, modules_dir, functions_dir, rules_dir]
        )

        if has_subdirs:
            if templates_dir.is_dir():
                engine.load_templates(str(templates_dir))
            if modules_dir.is_dir():
                engine.load_modules(str(modules_dir))
            if functions_dir.is_dir():
                engine.load_functions(str(functions_dir))
            if rules_dir.is_dir():
                engine.load_rules(str(rules_dir))
        else:
            # Strategy 2: key inspection — collect files by type, load in order
            template_files: list[Path] = []
            module_files: list[Path] = []
            function_files: list[Path] = []
            rule_files: list[Path] = []

            for yaml_file in sorted(p.glob("*.yaml")):
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    continue
                if "templates" in data:
                    template_files.append(yaml_file)
                elif "modules" in data or "focus_order" in data:
                    module_files.append(yaml_file)
                elif "functions" in data:
                    function_files.append(yaml_file)
                elif "rules" in data or "ruleset" in data:
                    rule_files.append(yaml_file)

            for tf in template_files:
                engine.load_templates(str(tf))
            for mf in module_files:
                engine.load_modules(str(mf))
            for ff in function_files:
                engine.load_functions(str(ff))
            for rf in rule_files:
                engine.load_rules(str(rf))

        return engine

    # --- Template / Module / Function / Rule loading ---

    def load_templates(self, path: str) -> None:
        """Load YAML template definitions from *path*.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.
        """
        count = 0
        try:
            p = Path(path)
            files: list[Path] = list(p.glob("*.yaml")) if p.is_dir() else [p]
            for file in files:
                definitions = self._compiler.parse_template_file(file)
                for defn in definitions:
                    clips_str = self._compiler.compile_template(defn)
                    self._safe_build(clips_str, context=f"template:{defn.name}")
                    self._template_registry[defn.name] = defn
                    if defn.ttl is not None:
                        self._fact_manager.set_ttl(defn.name, defn.ttl)
                    count += 1
        finally:
            if count:
                self._metrics.record_templates_loaded(count)

    def load_modules(self, path: str) -> None:
        """Load YAML module definitions from *path*.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.

        Raises:
            CompilationError: On duplicate module names or invalid YAML.
        """
        count = 0
        try:
            p = Path(path)
            files: list[Path] = list(p.glob("*.yaml")) if p.is_dir() else [p]
            # Ensure MAIN exports all constructs so non-MAIN modules can import them
            if not self._module_registry:
                self._safe_build(
                    "(defmodule MAIN (export ?ALL))",
                    context="module:MAIN",
                )
            for file in files:
                definitions, focus_order = self._compiler.parse_module_file(file)
                for defn in definitions:
                    if defn.name in self._module_registry:
                        raise CompilationError(
                            "[fathom.engine] load module failed: "
                            f"duplicate module name '{defn.name}'",
                            file=str(file),
                            construct=f"module:{defn.name}",
                        )
                    clips_str = self._compiler.compile_module(defn)
                    self._safe_build(clips_str, context=f"module:{defn.name}")
                    self._module_registry[defn.name] = defn
                    count += 1
                if focus_order:
                    self.set_focus(focus_order)
        finally:
            if count:
                self._metrics.record_modules_loaded(count)

    def load_functions(self, path: str) -> None:
        """Load YAML function definitions from *path*.

        Parses function YAML files, resolves hierarchy references for
        classification functions, compiles each to CLIPS deffunctions,
        and builds them into the environment.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.
        """
        count = 0
        try:
            p = Path(path)
            files: list[Path] = list(p.glob("*.yaml")) if p.is_dir() else [p]
            for file in files:
                definitions = self._compiler.parse_function_file(file)

                # Resolve hierarchy references for this file
                hierarchies: dict[str, HierarchyDefinition] = {}
                for defn in definitions:
                    if defn.hierarchy_ref:
                        hier_name = defn.hierarchy_ref.rsplit(".", 1)[0]
                        if hier_name not in hierarchies:
                            hier_def = self._resolve_hierarchy(defn.hierarchy_ref, file)
                            hierarchies[hier_name] = hier_def

                # Store resolved hierarchies for external functions (e.g. fathom-dominates)
                self._hierarchy_registry.update(hierarchies)

                # Compile and build each function
                for defn in definitions:
                    clips_str = self._compiler.compile_function(defn, hierarchies or None)
                    if clips_str:
                        # compile_function may return multi-deffunction string;
                        # build each deffunction separately
                        for block in clips_str.split("\n\n"):
                            block = block.strip()
                            if block:
                                self._safe_build(block, context=f"function:{defn.name}")
                        count += 1
        finally:
            if count:
                self._metrics.record_functions_loaded(count)

    def load_rules(self, path: str) -> None:
        """Load YAML rule definitions from *path*.

        Parses YAML rule files, validates that referenced modules exist
        in the module registry, compiles each rule, and builds it into
        the CLIPS environment.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.

        Raises:
            CompilationError: If a rule references an unregistered module,
                or on YAML/validation errors.
        """
        count = 0
        try:
            p = Path(path)
            files: list[Path] = list(p.glob("*.yaml")) if p.is_dir() else [p]
            for file in files:
                ruleset = self._compiler.parse_rule_file(file)

                # Validate that the referenced module is registered
                if ruleset.module not in self._module_registry:
                    raise CompilationError(
                        "[fathom.engine] load rules failed: "
                        f"module '{ruleset.module}' is not registered. "
                        "Load modules first with load_modules().",
                        file=str(file),
                        construct=f"ruleset:{ruleset.ruleset}",
                    )

                # Compile and build each rule into the CLIPS environment
                for rule_defn in ruleset.rules:
                    clips_str = self._compiler.compile_rule(rule_defn, ruleset.module)
                    self._safe_build(clips_str, context=f"rule:{rule_defn.name}")
                    self._rule_registry[rule_defn.name] = rule_defn
                    count += 1
        finally:
            if count:
                self._metrics.record_rules_loaded(count)
            # Recompute the cached flag used by evaluate() to short-circuit
            # snapshotting when no loaded rule emits user-declared asserts.
            self._has_asserting_rules = any(
                bool(r.then.asserts) for r in self._rule_registry.values()
            )

    def load_clips_function(self, clips_string: str) -> None:
        """Load a raw CLIPS function string into the environment.

        Args:
            clips_string: A valid CLIPS deffunction string.
        """
        self._safe_build(clips_string, context="clips_function")

    def register_function(
        self,
        name: str,
        fn: Callable[..., Any],
    ) -> None:
        """Register a Python callable as a CLIPS external function.

        The callable becomes invokable from CLIPS rule LHS and RHS as
        ``(name arg1 arg2 ...)``.

        Args:
            name: CLIPS function name. Must be non-empty, contain no
                whitespace, and not start with the reserved
                ``fathom-`` prefix (which is reserved for builtins
                registered by the Engine itself).
            fn: Python callable. Positional args only.

        Raises:
            ValueError: If the name is empty, contains whitespace, or
                starts with ``fathom-``.

        Notes:
            Re-registering an existing name overwrites the prior
            binding. This matches clipspy's semantics and is
            documented, not an error (AC-3.4).

        Example:
            >>> engine.register_function("overlaps", lambda a, b: bool(set(a) & set(b)))
            >>> # Rule LHS may now use: expression: "overlaps(?needed ?have)"
        """
        if not name:
            raise ValueError("register_function: name must be non-empty")
        if not _USER_FN_NAME_RE.match(name):
            raise ValueError(
                f"register_function: name must match "
                f"[A-Za-z][A-Za-z0-9_-]* (got {name!r})"
            )
        if name.startswith(RESERVED_FUNCTION_PREFIX):
            raise ValueError(
                f"register_function: name must not start with reserved "
                f"prefix {RESERVED_FUNCTION_PREFIX!r} (got {name!r})"
            )
        self._env.define_function(fn, name)

    @staticmethod
    def _resolve_hierarchy(
        hierarchy_ref: str,
        function_file: Path,
    ) -> HierarchyDefinition:
        """Resolve a hierarchy_ref filename to a HierarchyDefinition.

        Searches for the hierarchy YAML file relative to the function
        file's directory, then in a sibling ``hierarchies/`` directory.

        Args:
            hierarchy_ref: Filename like ``classification.yaml``.
            function_file: Path to the function YAML file that references it.

        Returns:
            A validated HierarchyDefinition.

        Raises:
            CompilationError: If the hierarchy file cannot be found or parsed.
        """
        parent = function_file.parent
        candidates = [
            parent / hierarchy_ref,
            parent / "hierarchies" / hierarchy_ref,
            parent.parent / "hierarchies" / hierarchy_ref,
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    with open(candidate) as f:
                        data = yaml.safe_load(f)
                except (yaml.YAMLError, OSError) as exc:
                    raise CompilationError(
                        f"[fathom.engine] resolve hierarchy failed: cannot read file {candidate}",
                        file=str(candidate),
                        detail=str(exc),
                    ) from exc
                if not isinstance(data, dict):
                    continue
                # Skip files that are not hierarchy definitions
                if "name" not in data or "levels" not in data:
                    continue
                return HierarchyDefinition(**data)

        raise CompilationError(
            f"[fathom.engine] resolve hierarchy failed: file '{hierarchy_ref}' not found",
            file=str(function_file),
            detail=f"Searched: {', '.join(str(c) for c in candidates)}",
        )

    def load_pack(self, pack_name: str) -> None:
        """Load a rule pack by name."""
        from fathom.packs import RulePackLoader

        RulePackLoader.load(self, pack_name)

    # --- Fact management ---

    def assert_fact(self, template: str, data: dict[str, Any]) -> None:
        """Assert a single fact into working memory.

        Args:
            template: Name of a previously loaded template.
            data: Slot name-to-value mapping for the fact.
        """
        tmpl_def = self._template_registry.get(template)
        if tmpl_def is not None and tmpl_def.scope == "fleet":
            raise ScopeError(
                f"template '{template}' is fleet-scoped; use FleetEngine.assert_fact "
                "so the fact is also written through to the shared FactStore."
            )
        try:
            self._fact_manager.assert_fact(template, data)
        finally:
            self._metrics.record_fact_asserted(template)

    def assert_facts(self, facts: list[tuple[str, dict[str, Any]]]) -> None:
        """Assert multiple facts atomically.

        All facts are validated before any are asserted. If validation
        fails for any fact, none are asserted.

        Args:
            facts: List of ``(template_name, slot_data)`` tuples.
        """
        try:
            self._fact_manager.assert_facts(facts)
        finally:
            for template, _ in facts:
                self._metrics.record_fact_asserted(template)

    def query(
        self,
        template: str,
        fact_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query working memory for facts matching *template* and optional *fact_filter*.

        Args:
            template: Template name to query.
            fact_filter: Optional slot name-to-value filter.

        Returns:
            List of matching facts as dictionaries.
        """
        return self._fact_manager.query(template, fact_filter)

    def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching *template* and optional *fact_filter*.

        Args:
            template: Template name to count.
            fact_filter: Optional slot name-to-value filter.
        """
        return self._fact_manager.count(template, fact_filter)

    def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Retract facts matching *template* and optional *fact_filter*.

        Returns count retracted.
        """
        retracted = self._fact_manager.retract(template, fact_filter)
        try:
            return retracted
        finally:
            if retracted:
                self._metrics.record_facts_retracted(retracted)

    # --- Evaluation ---

    def _snapshot_user_facts(self) -> list[AssertedFact]:
        """Capture a snapshot of user-asserted facts for audit purposes.

        Iterates registered user templates and queries working memory for
        each, returning a flat list of :class:`AssertedFact`. The internal
        ``__fathom_decision`` template is built via :meth:`_safe_build` and
        never registered in ``_template_registry``, so it is automatically
        excluded from the snapshot.
        """
        from fathom.models import AssertedFact

        snapshot: list[AssertedFact] = []
        for template_name in self._template_registry:
            for row in self._fact_manager.query(template_name):
                snapshot.append(AssertedFact(template=template_name, slots=row))
        return snapshot

    def evaluate(self) -> EvaluationResult:
        """Run the CLIPS engine to quiescence and return the evaluation result.

        Fires all eligible rules, records an audit entry, and returns
        the final decision with rule and module traces. When an
        attestation service is configured, the result is signed with
        an Ed25519 JWT token.

        Returns:
            :class:`EvaluationResult` with decision, reason, and traces.
        """
        # Pre-snapshot user facts when any loaded rule declares `asserts`,
        # so newly-asserted facts can be captured for the audit record.
        pre_snapshot = self._snapshot_user_facts() if self._has_asserting_rules else None

        result = self._evaluator.evaluate()
        try:
            # Sign attestation if service is configured
            if self._attestation_service is not None:
                result.attestation_token = self._attestation_service.sign(result, self._session_id)

            asserted_facts = None
            if pre_snapshot is not None:
                post_snapshot = self._snapshot_user_facts()
                diff = _diff_user_facts(pre_snapshot, post_snapshot)
                asserted_facts = diff or None

            self._audit_log.record(
                result,
                self._session_id,
                asserted_facts=asserted_facts,
            )
            return result
        finally:
            self._metrics.record_evaluation(result, self._session_id)

    # --- Session management ---

    def reset(self) -> None:
        """Reset the CLIPS environment.

        Calls ``env.reset()`` which clears all facts and re-asserts
        ``(initial-fact)``, then re-builds the ``__fathom_decision``
        template since ``reset()`` preserves deftemplates.
        """
        self._env.reset()
        self._fact_manager.clear_timestamps()
        # __fathom_decision template survives reset (deftemplates persist),
        # but re-build is safe (CLIPS ignores duplicate identical deftemplates).
        self._safe_build(_DECISION_TEMPLATE, context="__fathom_decision")

    def clear_facts(self) -> None:
        """Retract all user facts from working memory.

        Iterates registered templates and retracts their facts,
        leaving internal CLIPS facts (initial-fact, __fathom_decision) intact.
        """
        self._fact_manager.clear_all()

