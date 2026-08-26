"""Fathom Engine — core runtime wrapping a clipspy CLIPS Environment."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import clips
import yaml

from fathom.audit import AuditLog, AuditSink, NullSink
from fathom.compiler import Compiler
from fathom.errors import CompilationError, EvaluationLimitError, ScopeError
from fathom.evaluator import Evaluator
from fathom.facts import FactManager
from fathom.metrics import MetricsCollector
from fathom.models import HierarchyDefinition

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from fathom.attestation import AttestationService
    from fathom.models import (
        AssertedFact,
        EvaluationResult,
        ModuleDefinition,
        RuleDefinition,
        TemplateDefinition,
    )


logger = logging.getLogger(__name__)

# Reserved prefix for fathom-internal CLIPS functions (see Engine.register_function).
__all__ = ["Engine", "RESERVED_FUNCTION_PREFIX"]


RESERVED_FUNCTION_PREFIX = "fathom-"

# Default activation budget for a single evaluation. A ruleset whose rules
# assert facts that re-trigger those same rules never reaches quiescence, and
# an unbounded ``env.run()`` would spin until the process is killed — taking
# every other request on a shared server with it. Callers who genuinely want
# an unbounded run pass ``Engine(run_limit=None)``.
_DEFAULT_RUN_LIMIT = 100_000

# Max regex pattern/input length for fathom-matches.
#
# This cap does NOT bound catastrophic backtracking. Python's `re` is a
# backtracking engine, and a pathological pattern blows up on inputs orders
# of magnitude below this limit: `^(a+)+$` against 40 characters of "a"
# followed by "b" runs for minutes. The cap only bounds the *linear* cost of
# a well-behaved pattern and keeps a single call from copying megabytes.
#
# The actual mitigation for ReDoS is the threat model: rule authors are
# trusted (decision D4), so patterns are not attacker-controlled. A caller
# who accepts untrusted regexes needs a real defence — an re2 binding, or
# running evaluation under a wall-clock budget in a separate process.
# See Sec-M6.
_FATHOM_MATCHES_MAX_LEN = 4096

# User-registered CLIPS function names: restrict to the same ASCII subset
# CLIPS itself accepts, so a crafted name cannot inject construct-breaking
# characters into the CLIPS symbol table.
_USER_FN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


# CLIPS deftemplate built on every Engine init (design.md Section 6.1).
#
# Asserted once per firing by every compiled rule, whether or not that rule
# renders a decision. ``action none`` is the assert-only case: the rule fired,
# it belongs in ``rule_trace``, and it is not a candidate for the decision.
# Reading the trace off decision-bearing facts alone dropped every
# forward-chaining rule, so the step that derived the fact a later rule
# decided on was missing from the trace and from the signed audit record.
#
# ``seq`` makes each fact unique. CLIPS suppresses duplicate asserts, so
# without it a rule firing twice would be recorded once whenever its other
# slots happened to match.
_DECISION_TEMPLATE = (
    "(deftemplate MAIN::__fathom_decision"
    "    (slot seq (type INTEGER) (default 0))"
    "    (slot action (type SYMBOL)"
    "        (allowed-symbols none allow deny escalate scope route) (default none))"
    '    (slot reason (type STRING) (default ""))'
    '    (slot rule (type STRING) (default ""))'
    "    (slot log-level (type SYMBOL) (allowed-symbols none summary full) (default summary))"
    '    (slot notify (type STRING) (default ""))'
    "    (slot attestation (type SYMBOL) (allowed-symbols TRUE FALSE) (default FALSE))"
    '    (slot metadata (type STRING) (default "")))'
)

# Source of the ``seq`` above. MAIN exports every construct and each generated
# module does ``(import MAIN ?ALL)``, so a rule in any module can increment it.
_DECISION_SEQ_GLOBAL = "(defglobal MAIN ?*fathom-decision-seq* = 0)"

# Built only on an ``Engine(match_evidence=True)``. Lives in MAIN, which every
# generated module imports with ``(import MAIN ?ALL)``, so a rule in any module
# can assert it.
_EVIDENCE_TEMPLATE = (
    "(deftemplate MAIN::__fathom_evidence"
    '    (slot rule (type STRING) (default ""))'
    "    (multislot facts (type INTEGER)))"
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
        *,
        audit_sink: AuditSink | None = None,
        session_id: str | None = None,
        attestation_service: AttestationService | None = None,
        metrics: bool = False,
        run_limit: int | None = _DEFAULT_RUN_LIMIT,
        match_evidence: bool = False,
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
            attestation_service: Optional attestation service for signing
                evaluation results. When provided, all evaluation results
                are signed with an Ed25519 JWT token.
            metrics: Enable Prometheus metrics collection. Falls back
                to ``FATHOM_METRICS=1`` environment variable when
                ``False``.
            run_limit: Maximum rule activations a single evaluation may
                fire before :meth:`evaluate` gives up and raises
                :class:`~fathom.errors.EvaluationLimitError`. ``None``
                runs to quiescence with no budget. Defaults to
                ``100_000``.
            match_evidence: Record which facts, with which slot values,
                fired each rule (:attr:`EvaluationResult.match_evidence`).
                Off by default: it makes the compiler bind a pattern
                address to every condition and assert an extra fact per
                firing, so leaving it off costs nothing at all.

        Note:
            Engine is thread-safe: every public method serialises on an
            internal re-entrant lock, so a transport may share one Engine
            across a thread pool. Concurrent evaluations therefore
            serialise — CLIPS has one environment and one agenda, so that
            is correctness rather than a regression.
        """
        # Re-entrant: public methods call one another (evaluate_once ->
        # evaluate, load_modules -> set_focus), so a plain Lock would
        # self-deadlock on the nested call.
        self._lock = threading.RLock()
        self._env: clips.Environment = clips.Environment()
        self._session_id: str = session_id or str(uuid4())
        self._default_decision: str | None = default_decision
        self._template_registry: dict[str, TemplateDefinition] = {}
        self._module_registry: dict[str, ModuleDefinition] = {}
        self._rule_registry: dict[str, RuleDefinition] = {}
        self._has_asserting_rules: bool = False
        self._hierarchy_registry: dict[str, HierarchyDefinition] = {}
        self._focus_order: list[str] = []
        self._reload_lock = threading.Lock()
        self._reload_listeners: list[Callable[[], None]] = []
        self._ruleset_yaml_bytes: bytes | None = None

        self._match_evidence = match_evidence
        self._compiler = Compiler(match_evidence=match_evidence)
        self._fact_manager = FactManager(
            env_provider=lambda: self._env,
            template_registry=self._template_registry,
        )
        self._evaluator = Evaluator(
            env_provider=lambda: self._env,
            default_decision=self._default_decision,
            focus_order=self._focus_order,
            fact_manager=self._fact_manager,
            run_limit=run_limit,
            match_evidence=match_evidence,
        )
        self._audit_log = AuditLog(audit_sink or NullSink())
        self._attestation_service = attestation_service

        # Metrics collector (no-op when disabled or prometheus_client absent)
        metrics = metrics or os.getenv("FATHOM_METRICS") == "1"
        self._metrics = MetricsCollector(enabled=metrics)

        # Build the decision template into the CLIPS environment
        self._safe_build(_DECISION_SEQ_GLOBAL, context="__fathom_decision")
        self._safe_build(_DECISION_TEMPLATE, context="__fathom_decision")
        if match_evidence:
            self._safe_build(_EVIDENCE_TEMPLATE, context="__fathom_evidence")

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

    @property
    def attestation_service(self) -> AttestationService | None:
        """Service signing this engine's decisions, if any.

        Settable because a server can be handed an Engine it did not
        construct — ``app.state.engine`` in the REST app — and still has to
        attach the signing service configured alongside it.
        """
        return self._attestation_service

    @attestation_service.setter
    def attestation_service(self, service: AttestationService | None) -> None:
        self._attestation_service = service

    @property
    def ruleset_hash(self) -> str:
        """Addressable hash of the currently-loaded ruleset YAML.

        Returns ``f"sha256:{hexdigest}"`` over the concatenated raw YAML
        bytes of every rule file ingested via :meth:`load_rules`. For an
        empty engine (no rules loaded yet), returns the sentinel
        ``"sha256:" + "0" * 64``. This is the identifier consumed by the
        hot-reload endpoint (C5) to return ``ruleset_hash_before`` /
        ``ruleset_hash_after`` and by ``GET /v1/status``.
        """
        if self._ruleset_yaml_bytes is None:
            return "sha256:" + "0" * 64
        return f"sha256:{hashlib.sha256(self._ruleset_yaml_bytes).hexdigest()}"

    def set_focus(self, modules: list[str]) -> None:
        """Replace the focus order for evaluation.

        Must be called with modules that are already registered. Replaces
        the private reach-through ``engine._evaluator._focus_order = ...``.

        Validation is skipped when no modules have been loaded yet (the module
        registry is empty), allowing pre-load focus configuration.
        """
        with self._lock:
            if self._module_registry:
                unknown = [m for m in modules if m and m not in self._module_registry]
                if unknown:
                    raise ValueError(f"unknown modules in focus order: {unknown}")
            self._focus_order = list(modules)
            self._evaluator.set_focus_order(modules)

    # --- Internal helpers ---

    def _safe_build(
        self,
        clips_str: str,
        context: str = "",
        env: clips.Environment | None = None,
    ) -> None:
        """Build a CLIPS construct, wrapping CLIPSError as CompilationError.

        Args:
            clips_str: CLIPS construct source.
            context: Diagnostic label attached to ``CompilationError``.
            env: Target environment. Defaults to ``self._env``. Used by
                :meth:`reload_rules` to compile onto a fresh env before the
                atomic swap.
        """
        target = env if env is not None else self._env
        try:
            target.build(clips_str)
        except Exception as exc:
            raise CompilationError(
                f"[fathom.engine] CLIPS build failed: {exc}",
                construct=context,
                detail=str(exc),
            ) from exc

    #: How CLIPS reports a call to a function it does not have. The name it
    #: quotes is frequently generated rather than authored -- a
    #: ``type: classification`` function compiles to ``meets-or-exceeds``,
    #: ``below`` and friends -- so it appears nowhere in the rule YAML the
    #: author is staring at.
    _MISSING_FUNCTION_RE = re.compile(r"Missing function declaration for '([^']+)'")

    def _template_is_known(self, name: str) -> bool:
        """Whether *name* is a deftemplate this engine can match on.

        Checks the CLIPS environment as well as the YAML registry: a template
        can also arrive through a raw build, and a check that only consulted
        the registry would blame a load order that was in fact correct.
        """
        if name in self._template_registry:
            return True
        try:
            self._env.find_template(name)
        except Exception:
            return False
        return True

    def _diagnose_rule_build(
        self,
        exc: CompilationError,
        defn: RuleDefinition,
        file: Path,
        unknown_templates: list[str],
    ) -> CompilationError | None:
        """Re-describe a rule build failure that is really a load-order mistake.

        CLIPS reports the generated construct, not the mistake: a rule
        compiled before its templates fails with "Check appropriate syntax
        for defrule", and one compiled before its functions fails with
        EXPRNPSR3 naming a function the author never wrote. Both read as a
        broken rule. ``load_rules`` already names this failure for modules;
        these are the other two.

        *unknown_templates* must be collected BEFORE the build: CLIPS creates
        an implied deftemplate for each pattern it parses before it hits the
        error, so asking afterwards reports the first pattern as known and
        blames the wrong one.

        Returns None when the failure is something else, so the original
        CLIPS diagnostic is what the caller sees.
        """
        raw = exc.detail or str(exc)

        if unknown_templates:
            unique = list(dict.fromkeys(unknown_templates))
            names = ", ".join(f"'{name}'" for name in unique)
            noun = "template" if len(unique) == 1 else "templates"
            verb = "is" if len(unique) == 1 else "are"
            return CompilationError(
                "[fathom.engine] load rules failed: rule "
                f"'{defn.name}' matches {noun} {names}, which {verb} not "
                "registered. Load templates first with load_templates(), or "
                "load the whole pack with load_pack_dir().",
                file=str(file),
                construct=f"rule:{defn.name}",
                detail=raw,
            )

        missing = self._MISSING_FUNCTION_RE.search(raw)
        if missing:
            return CompilationError(
                "[fathom.engine] load rules failed: rule "
                f"'{defn.name}' calls '{missing.group(1)}', which is not "
                "defined in this engine. Functions must be loaded before the "
                "rules that call them: call load_functions() first, or load "
                "the whole pack with load_pack_dir(). If they are already "
                "loaded, the name is one a function definition should have "
                "produced -- a classification function generates CLIPS names "
                "that do not appear in your YAML.",
                file=str(file),
                construct=f"rule:{defn.name}",
                detail=raw,
            )

        return None

    # --- External functions ---

    def _register_external_functions(self, env: clips.Environment | None = None) -> None:
        """Register Python external functions callable from CLIPS rules.

        Args:
            env: Target CLIPS environment. Defaults to ``self._env``. Passed
                explicitly by :meth:`reload_rules` so callbacks are bound to
                the fresh env *before* the atomic-swap pointer flip.
        """
        if env is None:
            env = self._env

        # fathom-matches(str, pattern) — regex search via re.search()
        def fathom_matches(string_value: str, pattern: str) -> bool:
            """Return True when *pattern* matches *string_value* via re.search.

            Pattern is passed verbatim to Python's ``re`` engine. Both the
            pattern and the input are capped at ``_FATHOM_MATCHES_MAX_LEN``
            characters; longer inputs raise ``ValueError``.

            That cap is a size limit, **not** a ReDoS defence. ``re`` is a
            backtracking engine, so a pathological pattern such as
            ``^(a+)+$`` hangs on ~40 characters of input — three orders of
            magnitude under the cap. Fathom's protection against that is the
            1.0 threat model: rule authors are trusted, so patterns are not
            attacker-controlled. Callers who let untrusted parties author
            patterns must add their own bound (re2, or a wall-clock budget
            in a separate process).
            """
            p = str(pattern)
            s = str(string_value)
            if len(p) > _FATHOM_MATCHES_MAX_LEN or len(s) > _FATHOM_MATCHES_MAX_LEN:
                raise ValueError(
                    f"fathom-matches input exceeds {_FATHOM_MATCHES_MAX_LEN}-char safety cap"
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
        # fathom-schema-frequency-exceeds(template, slot, value, tau) — the same
        # count >= threshold predicate under the name the denoising contract uses.
        # A relation type is promoted candidate -> stable once its extraction
        # frequency reaches tau; registering the alias keeps the compiled CLIPS
        # readable as the operator the rule author actually wrote.
        env.define_function(fathom_last_n, "fathom-schema-frequency-exceeds")

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
        This is :meth:`load_pack_dir` on a fresh engine — the ordering has one
        implementation, in :mod:`fathom.packs`.

        Args:
            path: Directory containing rule definitions.
            **kwargs: Forwarded to :class:`Engine` constructor.

        Returns:
            A fully-loaded :class:`Engine` instance.

        Raises:
            CompilationError: If *path* is not a directory or holds nothing
                this loader recognises.
        """
        from fathom.packs import RulePackLoader

        engine = cls(**kwargs)
        # require_content=False: an empty directory has always produced an
        # empty engine here, and FleetEngine builds its session engines that
        # way before seeding templates by hand.
        RulePackLoader.load_dir(engine, path, require_content=False)
        return engine

    # --- Template / Module / Function / Rule loading ---

    def load_templates(self, path: str) -> None:
        """Load YAML template definitions from *path*.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.
        """
        count = 0
        self._lock.acquire()
        try:
            p = Path(path)
            # sorted(): readdir order is filesystem-dependent, so an
            # unsorted glob made load order vary between machines.
            files: list[Path] = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
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
            self._lock.release()
            if count:
                self._metrics.record_templates_loaded(count)

    def load_modules(self, path: str) -> None:
        """Load YAML module definitions from *path*.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.

        Raises:
            CompilationError: On duplicate module names or invalid YAML.
        """
        loaded: list[str] = []
        declared: list[str] = []
        self._lock.acquire()
        try:
            p = Path(path)
            # sorted(): readdir order is filesystem-dependent, so an
            # unsorted glob made load order vary between machines.
            files: list[Path] = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
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
                    loaded.append(defn.name)
                declared += focus_order

            # Focus is engine-wide and :meth:`set_focus` REPLACES, so applying
            # a declared focus order directly made a second pack unfocus the
            # first: its rules stayed in the registry and simply stopped
            # firing, and the decision fell through to the engine default with
            # an empty rule trace. Append instead.
            #
            # When this call declared no focus order at all, its modules would
            # otherwise never be focused, which is the same silent failure --
            # CLIPS only drains the agenda of the module holding the focus, so
            # the rules sit unfired and the caller gets the default decision.
            # A declared order is taken as written (and may name a dependency
            # pack's module, which is why it is not just `loaded`): a partial
            # focus order is the author excluding a module on purpose.
            #
            # A pack cannot reorder a focus another pack established; within
            # one pack the declared order is kept.
            focus = list(dict.fromkeys([*self._focus_order, *(declared or loaded)]))
            if focus != self._focus_order:
                self.set_focus(focus)
        finally:
            self._lock.release()
            if loaded:
                self._metrics.record_modules_loaded(len(loaded))

    def load_functions(self, path: str) -> None:
        """Load YAML function definitions from *path*.

        Parses function YAML files, resolves hierarchy references for
        classification functions, compiles each to CLIPS deffunctions,
        and builds them into the environment.

        Args:
            path: Path to a YAML file or directory containing ``*.yaml`` files.
        """
        count = 0
        self._lock.acquire()
        try:
            p = Path(path)
            # sorted(): readdir order is filesystem-dependent, so an
            # unsorted glob made load order vary between machines.
            files: list[Path] = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
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
            self._lock.release()
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
        self._lock.acquire()
        try:
            p = Path(path)
            files: list[Path] = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
            # Accumulate raw YAML bytes across all rule files loaded in this
            # call for ruleset_hash; this is the canonical form verified by
            # integrations/ruleset_sig.py (raw bytes, sorted by path).
            loaded_bytes: list[bytes] = []
            for file in files:
                file_bytes = file.read_bytes()
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

                # Compile and build each rule into the CLIPS environment.
                # The registry is keyed "module::name": keying it by bare name
                # meant a rule in a second file silently replaced an
                # identically-named rule from the first, and two modules could
                # not hold the same rule name at all.
                for rule_defn in ruleset.rules:
                    key = f"{ruleset.module}::{rule_defn.name}"
                    if key in self._rule_registry:
                        raise CompilationError(
                            f"[fathom.engine] load rules failed: duplicate rule name '{key}'",
                            file=str(file),
                            construct=f"rule:{key}",
                        )
                    clips_str = self._compiler.compile_rule(
                        rule_defn, ruleset.module, self._template_registry
                    )
                    # Collected before the build: a failed build leaves
                    # implied deftemplates behind for the patterns CLIPS got
                    # through, which would mask the real answer.
                    unknown_templates = [
                        pattern.template
                        for pattern in rule_defn.when
                        if not self._template_is_known(pattern.template)
                    ]
                    try:
                        self._safe_build(clips_str, context=f"rule:{rule_defn.name}")
                    except CompilationError as exc:
                        better = self._diagnose_rule_build(exc, rule_defn, file, unknown_templates)
                        if better is None:
                            raise
                        raise better from exc
                    self._rule_registry[key] = rule_defn
                    count += 1

                loaded_bytes.append(file_bytes)

            # Extend any prior ruleset bytes so successive load_rules() calls
            # accumulate into a single addressable hash. reload_rules() will
            # reset this on a full swap.
            if loaded_bytes:
                prior = self._ruleset_yaml_bytes or b""
                self._ruleset_yaml_bytes = prior + b"".join(loaded_bytes)
        finally:
            # Recompute the cached flag used by evaluate() to short-circuit
            # snapshotting when no loaded rule emits user-declared asserts.
            # Must happen BEFORE releasing the lock: it iterates
            # _rule_registry, which a concurrent load_rules() mutates.
            self._has_asserting_rules = any(
                bool(r.then.asserts) for r in self._rule_registry.values()
            )
            self._lock.release()
            if count:
                self._metrics.record_rules_loaded(count)

    def load_clips_function(self, clips_string: str) -> None:
        """Load a raw CLIPS function string into the environment.

        Args:
            clips_string: A valid CLIPS deffunction string.
        """
        # Mutates the CLIPS environment, so it takes the same lock every
        # other env mutation takes — otherwise a build racing an evaluate()
        # corrupts the environment.
        with self._lock:
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
                f"register_function: name must match [A-Za-z][A-Za-z0-9_-]* (got {name!r})"
            )
        if name.startswith(RESERVED_FUNCTION_PREFIX):
            raise ValueError(
                f"register_function: name must not start with reserved "
                f"prefix {RESERVED_FUNCTION_PREFIX!r} (got {name!r})"
            )
        # define_function mutates the CLIPS environment; hold the same lock
        # evaluate() and the fact mutators take.
        with self._lock:
            self._env.define_function(fn, name)

    def subscribe(
        self,
        callback: Callable[[str, str, dict[str, Any]], None],
    ) -> Callable[[], None]:
        """Register a callback fired on every successful fact assert/retract.

        The callback receives ``(template_name, action, data)`` where
        ``action`` is ``"assert"`` or ``"retract"`` and ``data`` is the
        slot dict that was asserted or just retracted (validated form,
        not CLIPS-coerced).

        Returns an unsubscribe callable. Listener exceptions are
        logged and swallowed -- a wedged subscriber never breaks
        ``assert_fact`` / ``retract``.

        This is the foundation under the gRPC ``SubscribeChanges`` RPC
        and any custom in-process change-feed.
        """
        return self._fact_manager.add_listener(callback)

    def subscribe_reload(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired after every successful :meth:`reload_rules` swap.

        The callback takes no arguments and is invoked *outside* the
        reload lock, after the new env is live. Listener exceptions are
        logged and swallowed — a wedged subscriber never breaks
        :meth:`reload_rules`.

        This is the seam under ADR-0002's cancel-on-swap semantics: the
        gRPC ``SubscribeChanges`` RPC uses it to terminate in-flight
        change streams when the ruleset they were bound to is swapped
        out, so clients re-subscribe against the new ruleset.

        Returns an unsubscribe callable.
        """
        self._reload_listeners.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._reload_listeners.remove(callback)

        return unsubscribe

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
        """Load a rule pack by name from the ``fathom.packs`` entry points.

        For a pack that lives in a directory rather than an installed
        distribution, use :meth:`load_pack_dir`.
        """
        from fathom.packs import RulePackLoader

        RulePackLoader.load(self, pack_name)

    def load_pack_dir(self, path: str | Path) -> None:
        """Load a rule pack from a directory into this engine.

        Loads ``templates`` → ``modules`` → ``functions`` → ``rules``, which
        is the only order that works: a rule references the templates it
        matches and the functions it calls, and CLIPS reports a violation of
        that order as a diagnostic about the generated construct rather than
        about the ordering. Both pack layouts are accepted — the
        ``templates/`` ``modules/`` ``functions/`` ``rules/`` subdirectory
        convention, and a flat directory of ``*.yaml`` whose top-level key
        names the kind.

        Unlike :meth:`from_rules`, this loads into an engine that already
        exists, so a host can add a pack at runtime. Loading the same
        directory twice is a no-op, and a pack that would redefine a template
        another pack registered is rejected before anything is built.
        ``PACK_DEPENDENCIES`` is not resolved for a directory pack: there is
        no module to declare it on.

        Args:
            path: Directory holding the pack.

        Raises:
            CompilationError: If *path* is not a directory, holds nothing
                recognised, or collides with a template already registered.
        """
        from fathom.packs import RulePackLoader

        RulePackLoader.load_dir(self, path)

    # --- Atomic-swap ruleset reload (design C5, AC-5.3, NFR-8) ---

    def reload_rules(
        self,
        ruleset_yaml: bytes,
        signature: bytes | None = None,
        pubkey_pem: bytes | None = None,
    ) -> tuple[str, str]:
        """Atomically swap the rule environment with a new ruleset.

        Builds a fresh :class:`clips.Environment` *outside* the reload lock,
        compiles the supplied rule YAML (plus the currently-registered
        templates and modules) into it, re-registers external callbacks
        against the new env, then acquires ``self._reload_lock`` and swaps
        the env pointer, rule registry, and ``_ruleset_yaml_bytes`` in a
        single critical section.

        In-flight evaluations are unaffected: :class:`Evaluator` and
        :class:`FactManager` snapshot the env via a provider closure at the
        start of each evaluation, so swapping ``self._env`` does not
        reach into running evals. CLIPS callbacks registered on the old
        env keep firing against the old env via their captured closure.

        The audit sink is intentionally **not** touched here; the REST /
        gRPC layer signs and emits the ``ruleset_reloaded`` event on
        successful return (design C5 / C6).

        .. warning::
           This **discards all working memory**. The rules are compiled onto
           a brand-new :class:`clips.Environment`, so every fact asserted
           before the reload is gone afterwards, and TTL timestamps are
           cleared. Callers holding session state must re-assert it.

        Args:
            ruleset_yaml: Raw YAML bytes containing a ruleset document
                (top-level ``module``, ``ruleset``, ``rules`` keys; same
                schema :meth:`load_rules` accepts). Bytes are preserved
                verbatim and hashed by :attr:`ruleset_hash` on success.
            signature: Optional detached 64-byte Ed25519 signature over
                ``ruleset_yaml``. When supplied, ``pubkey_pem`` is
                required. Verification runs *before* compilation so a
                bad signature never mutates CLIPS state.
            pubkey_pem: PEM-encoded Ed25519 public key. Required when
                ``signature`` is supplied.

        Returns:
            Tuple ``(hash_before, hash_after)`` of
            :attr:`ruleset_hash` values bracketing the swap. Callers
            compare the two to detect no-op reloads.

        Raises:
            ValueError: ``signature`` supplied without ``pubkey_pem``.
            RulesetSignatureError: Signature verification failed.
            CompilationError: New ruleset failed to parse or compile.
                The existing env is left untouched (NFR-8).
        """
        # Local imports keep Engine.__init__ cheap and avoid a circular
        # import from integrations when cryptography is absent in minimal
        # installs.
        from fathom.integrations.ruleset_sig import verify_ruleset_signature
        from fathom.models import RulesetDefinition

        if signature is not None and pubkey_pem is None:
            raise ValueError("pubkey_pem required when signature provided")

        hash_before = self.ruleset_hash

        # Step 1: verify signature over the raw bytes BEFORE any compile
        # work. RulesetSignatureError propagates — leaves env untouched.
        if signature is not None:
            assert pubkey_pem is not None  # narrowed by check above
            verify_ruleset_signature(ruleset_yaml, signature, pubkey_pem)

        # Step 2: parse the new ruleset YAML. Parse errors surface as
        # CompilationError so the caller sees a single exception type for
        # any pre-swap compile failure.
        try:
            data = yaml.safe_load(ruleset_yaml)
        except yaml.YAMLError as exc:
            raise CompilationError(
                f"[fathom.engine] reload_rules: invalid YAML: {exc}",
                construct="reload_rules:parse",
                detail=str(exc),
            ) from exc
        if not isinstance(data, dict) or "rules" not in data or "module" not in data:
            raise CompilationError(
                "[fathom.engine] reload_rules: YAML must contain top-level "
                "'module' and 'rules' keys",
                construct="reload_rules:parse",
            )
        try:
            new_ruleset = RulesetDefinition(
                ruleset=data.get("ruleset", "reloaded"),
                version=str(data.get("version", "1.0")),
                module=data["module"],
                rules=data["rules"],
            )
        except Exception as exc:
            raise CompilationError(
                f"[fathom.engine] reload_rules: ruleset validation failed: {exc}",
                construct="reload_rules:validate",
                detail=str(exc),
            ) from exc

        # Step 3: build the fresh env OUTSIDE the lock. All compilation
        # targets ``new_env``; on any failure we raise and never touch
        # ``self._env`` (AC-5.3 atomicity, NFR-8 idempotent failure).
        new_env = clips.Environment()

        # Decision template — matches what __init__ does on startup.
        self._safe_build(_DECISION_SEQ_GLOBAL, context="__fathom_decision", env=new_env)
        self._safe_build(_DECISION_TEMPLATE, context="__fathom_decision", env=new_env)
        if self._match_evidence:
            self._safe_build(_EVIDENCE_TEMPLATE, context="__fathom_evidence", env=new_env)

        # Export MAIN so non-MAIN modules can import its constructs —
        # mirrors load_modules() first-module-seen behaviour.
        if self._module_registry:
            self._safe_build(
                "(defmodule MAIN (export ?ALL))",
                context="module:MAIN",
                env=new_env,
            )

        # Register external callbacks on the new env FIRST. CLIPS `build`
        # resolves external-function references at compile time, so
        # fathom-matches/fathom-count-exceeds/etc. must exist on new_env
        # before any rule that references them is compiled. Callbacks
        # close over the env they were registered against, so in-flight
        # evals on the OLD env keep seeing OLD-env-bound callbacks — the
        # property the design audit relies on (C5 / D1).
        self._register_external_functions(env=new_env)

        # Recompile templates from the current registry. Templates/modules
        # are not part of the hot-reload payload (rule-only swap); we
        # rebuild them onto new_env from their stored definitions so
        # freshly-compiled rules can reference them.
        new_template_registry: dict[str, TemplateDefinition] = {}
        for name, tdefn in self._template_registry.items():
            clips_str = self._compiler.compile_template(tdefn)
            self._safe_build(clips_str, context=f"template:{name}", env=new_env)
            new_template_registry[name] = tdefn

        # Recompile modules from the current registry, preserving order.
        new_module_registry: dict[str, ModuleDefinition] = {}
        for name, mdefn in self._module_registry.items():
            clips_str = self._compiler.compile_module(mdefn)
            self._safe_build(clips_str, context=f"module:{name}", env=new_env)
            new_module_registry[name] = mdefn

        # Validate the new ruleset's module is registered — same guard as
        # load_rules(). Raised as CompilationError; new_env is discarded.
        if new_ruleset.module not in new_module_registry:
            raise CompilationError(
                "[fathom.engine] reload_rules: "
                f"module '{new_ruleset.module}' is not registered. "
                "Load modules via load_modules() before reloading rules.",
                construct=f"ruleset:{new_ruleset.ruleset}",
            )

        # Compile the new rules onto new_env. Build into a fresh registry;
        # we swap the entire mapping under the lock so old rules vanish
        # atomically.
        new_rule_registry: dict[str, RuleDefinition] = {}
        for rule_defn in new_ruleset.rules:
            key = f"{new_ruleset.module}::{rule_defn.name}"
            if key in new_rule_registry:
                raise CompilationError(
                    f"[fathom.engine] reload_rules: duplicate rule name '{key}'",
                    construct=f"rule:{key}",
                )
            # new_template_registry, not self._template_registry: the rules
            # must be typed against the templates built onto new_env.
            clips_str = self._compiler.compile_rule(
                rule_defn, new_ruleset.module, new_template_registry
            )
            self._safe_build(clips_str, context=f"rule:{rule_defn.name}", env=new_env)
            new_rule_registry[key] = rule_defn

        new_has_asserting_rules = any(bool(r.then.asserts) for r in new_rule_registry.values())

        # Step 4: atomic swap. Critical section is pointer assignments
        # only — no I/O, no compilation — so any reader holding the old
        # env snapshot sees a consistent view and the lock is held for
        # microseconds, not the compile duration.
        with self._reload_lock:
            self._env = new_env
            # Replace rule registry by identity; Engine is the sole reader.
            self._rule_registry = new_rule_registry
            # Template/module registries are held by reference in
            # FactManager (template_registry=...). To honour the swap
            # without a reader-side refactor, rebuild contents in place
            # so the shared reference stays valid. Contents are identical
            # today (rule-only reload) but we keep the pattern so future
            # template-reload work has a stable seam.
            self._template_registry.clear()
            self._template_registry.update(new_template_registry)
            self._module_registry.clear()
            self._module_registry.update(new_module_registry)
            self._has_asserting_rules = new_has_asserting_rules
            self._ruleset_yaml_bytes = ruleset_yaml
            # The new env starts empty, so the reload discards ALL working
            # memory. The TTL timestamps are keyed by old-env fact index and
            # would otherwise expire unrelated facts in the new one.
            self._fact_manager.clear_timestamps()
            # The reload also discards the rule registry, so any pack loaded
            # into this engine no longer has rules here. Forget the "already
            # loaded" record, or a later load_pack() returns success while
            # silently restoring nothing.
            from fathom.packs import forget_packs

            forget_packs(self)

        # Notify reload listeners outside the lock — listeners may do
        # I/O (e.g. wake gRPC change streams) and must never extend the
        # critical section. Snapshot so unsubscribe-during-notify is safe.
        for cb in list(self._reload_listeners):
            try:
                cb()
            except Exception:  # pragma: no cover - listener bugs must not crash reload
                logger.exception("reload listener raised; continuing")

        hash_after = self.ruleset_hash
        return hash_before, hash_after

    # --- Fact management ---

    def _publish_working_memory(self, templates: Iterable[str]) -> None:
        """Publish the live fact count for each of *templates*.

        Backs the ``fathom_working_memory_facts`` gauge, which is registered
        and exported but was never recorded, so a working-memory leak read as
        healthy on any dashboard. Caller must hold ``self._lock``; counts are
        read straight from the fact manager so the gauge cannot drift the way
        an inc/dec pair can.
        """
        if not self._metrics.enabled:
            return
        for template in dict.fromkeys(templates):
            if template not in self._template_registry:
                continue
            self._metrics.set_working_memory_facts(
                template=template,
                count=self._fact_manager.count(template),
            )

    def assert_fact(self, template: str, data: dict[str, Any]) -> None:
        """Assert a single fact into working memory.

        Args:
            template: Name of a previously loaded template.
            data: Slot name-to-value mapping for the fact.
        """
        with self._lock:
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
                self._publish_working_memory([template])

    def _assert_local(
        self, template: str, data: dict[str, Any]
    ) -> list[tuple[str, Any, dict[str, Any]]]:
        """Assert a fact bypassing the fleet-scope guard.

        :class:`~fathom.fleet.FleetEngine` is the only legitimate caller: it
        has already written the fact through to the shared store, so the
        guard in :meth:`assert_fact` — which exists to stop a caller writing
        a fleet-scoped fact to one node only — must not fire. Everything else
        :meth:`assert_fact` does (the lock, the metrics) still applies.

        Returns:
            Handles for the facts this call actually created — empty when
            CLIPS de-duplicated the assert onto a fact that already existed.
            :meth:`_retract_local_handles` withdraws exactly these, which is
            what makes FleetEngine's rollback-on-store-failure sound: it
            cannot miss a coerced value the way a retract-by-value filter
            does, and it cannot delete a pre-existing duplicate it did not
            create.
        """
        with self._lock:
            try:
                return self._fact_manager.assert_facts_scoped([(template, data)])
            finally:
                self._metrics.record_fact_asserted(template)
                self._publish_working_memory([template])

    def _retract_local_handles(self, handles: list[tuple[str, Any, dict[str, Any]]]) -> None:
        """Retract exactly the facts named by *handles* (see :meth:`_assert_local`)."""
        if not handles:
            return
        with self._lock:
            self._fact_manager.retract_handles(handles)
            self._metrics.record_facts_retracted(len(handles))
            self._publish_working_memory([template for template, _, _ in handles])

    def assert_facts(self, facts: list[tuple[str, dict[str, Any]]]) -> None:
        """Assert multiple facts atomically.

        All facts are validated before any are asserted. If validation
        fails for any fact, none are asserted.

        Args:
            facts: List of ``(template_name, slot_data)`` tuples.
        """
        with self._lock:
            try:
                self._fact_manager.assert_facts(facts)
            finally:
                for template, _ in facts:
                    self._metrics.record_fact_asserted(template)
                self._publish_working_memory(t for t, _ in facts)

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
        with self._lock:
            return self._fact_manager.query(template, fact_filter)

    def all_facts(self) -> list[dict[str, Any]]:
        """Return every fact currently in working memory, as dictionaries.

        Each entry carries a ``__template__`` key naming the template the
        fact came from, alongside its slot values. The public way to inspect
        working memory without reaching into the CLIPS environment.
        """
        with self._lock:
            return self._fact_manager.all_facts()

    def count(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Count facts matching *template* and optional *fact_filter*.

        Args:
            template: Template name to count.
            fact_filter: Optional slot name-to-value filter.
        """
        with self._lock:
            return self._fact_manager.count(template, fact_filter)

    def retract(self, template: str, fact_filter: dict[str, Any] | None = None) -> int:
        """Retract facts matching *template* and optional *fact_filter*.

        Returns count retracted.

        Raises:
            ScopeError: *template* is fleet-scoped. The guard is the mirror
                of the one on :meth:`assert_fact`: dropping a fleet fact on
                one node only diverges that node from the shared FactStore,
                which is exactly what the assert-side guard exists to
                prevent. Fleet retraction does not propagate at all (see the
                module docstring of :mod:`fathom.fleet`), so this fails
                loudly rather than diverging silently.
        """
        with self._lock:
            tmpl_def = self._template_registry.get(template)
            if tmpl_def is not None and tmpl_def.scope == "fleet":
                raise ScopeError(
                    f"template '{template}' is fleet-scoped; retracting it locally "
                    "would diverge this node from the shared FactStore. Fleet "
                    "retraction does not propagate — recreate the session instead."
                )
            retracted = self._fact_manager.retract(template, fact_filter)
            self._publish_working_memory([template])
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
        # Materialise the key view first: reload_rules rebuilds
        # _template_registry in place under _reload_lock only, so iterating
        # the live dict here races with a concurrent hot reload and raises
        # "dictionary changed size during iteration" mid-evaluation.
        for template_name in list(self._template_registry):
            for row in self._fact_manager.query(template_name):
                snapshot.append(AssertedFact(template=template_name, slots=row))
        return snapshot

    def _snapshot_input_facts(self) -> list[dict[str, Any]]:
        """Working memory as a flat list of ``{template, slots}`` entries.

        This is the exact serialisation the attestation ``input_hash`` is
        taken over (``json.dumps(..., sort_keys=True)``) and what an
        ``AuditRecord.input_facts`` holds at ``log: full``. It must be
        captured BEFORE inference, or rule-asserted facts would be folded
        into the record of what the decision was computed from.

        Each entry carries the template name alongside the slot values.
        Emitting bare slot dicts made ``input_hash`` blind to template
        identity: two templates with the same slot names produced a
        byte-identical hash, so a token attesting ``low_risk_asset(id=x)``
        also verified against ``high_risk_asset(id=x)``.

        Ordering is template-registry order (ruleset declaration order),
        then working-memory order within each template. It is stable for a
        given ruleset but is NOT a canonical set ordering: the hash binds
        the facts *as asserted*, not an order-insensitive set.
        """
        snapshot: list[dict[str, Any]] = []
        # list(): see _snapshot_user_facts — the live dict is rebuilt in
        # place by reload_rules under a different lock.
        for template_name in list(self._template_registry):
            for row in self._fact_manager.query(template_name):
                snapshot.append({"template": template_name, "slots": row})
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
        with self._lock:
            # Pre-snapshot user facts when any loaded rule declares `asserts`,
            # so newly-asserted facts can be captured for the audit record.
            pre_snapshot = self._snapshot_user_facts() if self._has_asserting_rules else None

            # The caller-supplied working memory the decision is computed
            # over. Needed BEFORE inference by attestation (it is what
            # input_hash binds) and by `log: full`. Skipped entirely when
            # neither consumer exists, since it costs a query per template.
            input_facts: list[dict[str, Any]] | None = None
            if self._attestation_service is not None or self._audit_log.is_recording:
                input_facts = self._snapshot_input_facts()

            result, log_level = self._evaluator.evaluate()
            try:
                # Sign attestation if service is configured. input_facts is
                # non-None here by construction; sign() refuses None because a
                # token signed without inputs binds nothing.
                if self._attestation_service is not None:
                    result.attestation_token = self._attestation_service.sign(
                        result,
                        self._session_id,
                        input_facts=input_facts if input_facts is not None else [],
                    )

                asserted_facts = None
                if pre_snapshot is not None:
                    post_snapshot = self._snapshot_user_facts()
                    diff = _diff_user_facts(pre_snapshot, post_snapshot)
                    asserted_facts = diff or None

                self._audit_log.record(
                    result,
                    self._session_id,
                    input_facts=input_facts,
                    asserted_facts=asserted_facts,
                    log_level=log_level,
                )
                return result
            finally:
                self._metrics.record_evaluation(result, self._session_id)

    def _refresh_all_rules(self) -> None:
        """Clear CLIPS refraction for every loaded rule, in every module.

        ``env.rules()`` wraps ``GetNextDefrule``, which enumerates only the
        CLIPS *current module*. After an evaluation the current module is
        whichever one the focus stack left behind — often ``MAIN``, which
        holds no user rules — so a bare ``for rule in env.rules()`` loop
        silently refreshed *nothing* and refraction survived. That made the
        request-scoped boundary non-deterministic: a deny rule keyed on
        long-lived facts fired on request 1, was skipped on request 2, and
        came back on request 3.

        Walk every defmodule explicitly and restore the current module
        afterwards so we do not disturb the focus stack the evaluator sets up.

        Caller must hold ``self._lock``.
        """
        env = self._env
        saved = env.current_module
        try:
            for module in list(env.modules()):
                env.current_module = module
                for rule in env.rules():
                    rule.refresh()
        finally:
            env.current_module = saved

    def evaluate_once(self, facts: list[tuple[str, dict[str, Any]]]) -> EvaluationResult:
        """Evaluate exactly *facts* and leave working memory as it was found.

        Asserts *facts*, runs :meth:`evaluate`, then retracts precisely the
        facts this call asserted and clears CLIPS refraction so an identical
        repeat call fires the same rules again. This is the request-scoped
        boundary the REST and gRPC ``Evaluate`` handlers use: two calls with
        the same facts return the same decision regardless of what this
        engine evaluated before.

        :meth:`evaluate` keeps its cumulative semantics for library callers
        (decision D1) — this is an additional entry point, not a change to
        that one.

        Facts asserted by *rules* during evaluation are left in place; only
        the caller-supplied ones are withdrawn.

        Args:
            facts: List of ``(template_name, slot_data)`` tuples, the same
                shape :meth:`assert_facts` takes.

        Returns:
            :class:`EvaluationResult` for this fact set alone.

        Raises:
            ScopeError: A named template is fleet-scoped.
            ValidationError: Slot data is invalid — raised before anything
                is asserted, so working memory is untouched.
        """
        with self._lock:
            # Guard every template BEFORE asserting any of them, so a
            # fleet-scoped template late in the list cannot leave the
            # earlier facts behind.
            for template, _ in facts:
                tmpl_def = self._template_registry.get(template)
                if tmpl_def is not None and tmpl_def.scope == "fleet":
                    raise ScopeError(
                        f"template '{template}' is fleet-scoped; use FleetEngine.assert_fact "
                        "so the fact is also written through to the shared FactStore."
                    )
            handles = self._fact_manager.assert_facts_scoped(facts)
            for template, _ in facts:
                self._metrics.record_fact_asserted(template)
            self._publish_working_memory(t for t, _ in facts)
            # Clear refraction BEFORE the run, not after.
            #
            # Retracting this request's facts un-matches the rules that
            # joined against them, but a rule whose LHS references only
            # longer-lived working memory (an `agent` fact, a policy fact)
            # matched once and stays refracted forever — it silently stops
            # firing from the second request onwards. For a deny rule that
            # is a fail-open, and the shipped owasp/nist/hipaa/cmmc packs
            # all contain deny rules of exactly that shape.
            #
            # Refreshing afterwards does not fix it: CLIPS `refresh` does not
            # restore an activation that fired during the run just completed,
            # so the rule was still refracted on the very next call. Doing it
            # here means every evaluate_once starts from a clean agenda,
            # which is what "same facts in, same decision out" requires.
            self._refresh_all_rules()
            # Fact indices present before inference. Used only on the
            # budget-exhaustion path below.
            pre_run_indices = {fact.index for fact in self._env.facts()}
            try:
                return self.evaluate()
            except EvaluationLimitError:
                # A ruleset that exhausts the activation budget is one whose
                # rules re-trigger themselves, so by the time we get here it
                # has typically asserted ~run_limit facts. Retracting only the
                # caller's own handles would leave all of them in this
                # session's working memory forever: one 503 permanently costs
                # the process ~100k facts, and a caller who can provoke it
                # repeatedly grows the server without bound.
                #
                # The request produced no decision, so nothing it created has
                # any value — drop the lot and leave working memory as the
                # request found it.
                for fact in list(self._env.facts()):
                    if fact.index in pre_run_indices:
                        continue
                    with contextlib.suppress(Exception):
                        fact.retract()
                raise
            finally:
                # `finally`: a failed evaluation (e.g. an exhausted activation
                # budget) must not leak the request's facts into the working
                # memory of the next request on this session.
                self._fact_manager.retract_handles(handles)
                if handles:
                    self._metrics.record_facts_retracted(len(handles))
                self._publish_working_memory(t for t, _ in facts)

    # --- Session management ---

    def reset(self) -> None:
        """Reset the CLIPS environment.

        Calls ``env.reset()``, which clears all facts and re-asserts
        ``(initial-fact)``. Deftemplates — including ``__fathom_decision``
        — survive ``reset()``, so nothing is rebuilt: every compiled rule
        asserts ``__fathom_decision``, which makes the template permanently
        "in use", and CLIPS refuses to redefine a deftemplate a loaded rule
        references (``[CSTRCPSR4]``). The unconditional rebuild that used to
        live here therefore broke ``reset()`` on any engine with rules
        loaded — i.e. ``fathom test`` and ``fathom bench``.
        """
        with self._lock:
            self._env.reset()
            self._fact_manager.clear_timestamps()
            self._publish_working_memory(list(self._template_registry))

    def clear_facts(self) -> None:
        """Retract all user facts from working memory.

        Iterates registered templates and retracts their facts,
        leaving internal CLIPS facts (initial-fact, __fathom_decision) intact.
        """
        with self._lock:
            self._fact_manager.clear_all()
            self._publish_working_memory(list(self._template_registry))
