"""Pydantic data models for Fathom runtime."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# CLIPS identifiers (template, module, rule, function names) are emitted
# verbatim into the CLIPS source stream. Restrict them to a conservative
# ASCII subset so a crafted name cannot break out of the enclosing
# construct and inject arbitrary CLIPS.
_CLIPS_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")

# AssertSpec slot values are emitted into CLIPS RHS forms. The compiler
# passes ``?var`` and ``(…)`` values verbatim; strings are quoted. Reject
# anything that could terminate the enclosing defrule or smuggle a
# second top-level construct — specifically unescaped ``"`` in string
# literals and unbalanced parens in s-expressions.
_SLOT_VAR_RE = re.compile(r"^\?[A-Za-z_][A-Za-z0-9_\-]*$")


def _validate_clips_ident(name: str, kind: str) -> str:
    if not _CLIPS_IDENT_RE.match(name):
        raise ValueError(
            f"{kind} name {name!r} is not a valid CLIPS identifier "
            "(must match [A-Za-z_][A-Za-z0-9_-]*)"
        )
    return name


def _validate_slot_value(value: str) -> str:
    """Reject slot values that could break out of a CLIPS RHS form."""
    if value.startswith("?"):
        if not _SLOT_VAR_RE.match(value):
            raise ValueError(
                f"slot variable reference {value!r} is malformed "
                "(expected '?' followed by a CLIPS identifier)"
            )
        return value
    if value.startswith("("):
        if not value.endswith(")"):
            raise ValueError(f"slot s-expression {value!r} must end with ')'")
        depth = 0
        for ch in value:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError(f"slot s-expression {value!r} has unbalanced parentheses")
        if depth != 0:
            raise ValueError(f"slot s-expression {value!r} has unbalanced parentheses")
        return value
    # Plain string literal — reject embedded control chars that would
    # terminate the CLIPS string when escaped back out.
    if "\x00" in value:
        raise ValueError("slot value must not contain NUL bytes")
    return value


# ``ConditionEntry.expression`` is compiled into the enclosing fact pattern,
# so an argument that closes the expression early can smuggle extra
# conditional elements into the generated defrule. Require a single
# ``operator(argument)`` form whose parentheses balance exactly once, on the
# final character.
_OPERATOR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Operators whose argument the compiler emits as an escaped, quoted CLIPS
# string (``contains`` -> ``(str-index "..." ?v)``, ``matches`` ->
# ``(fathom-matches ?v "...")``). Their argument cannot break out of the
# generated construct no matter what it contains, so the paren-balance rule
# below must not be applied to them: it is a defence against an argument
# closing the expression early, which is impossible once the argument is
# quoted and escaped.
#
# Applying it anyway rejected legitimate patterns — ``matches([)])`` and
# ``matches([(])`` (parentheses inside a regex character class, where they
# are literal) and ``contains(a :-) b)`` (free text) — all of which
# previously compiled to a safely-quoted construct.
_QUOTED_ARG_OPERATORS = frozenset({"contains", "matches"})

# Variable namespace the compiler generates for patterns with no alias
# (``f"p{pattern_index}"``). A user alias must not land in it.
_RESERVED_ALIAS_RE = re.compile(r"^p\d+$")


def _validate_expression(expr: str) -> str:
    """Reject condition expressions that are not one ``operator(arg)`` form."""
    paren_idx = expr.find("(")
    if paren_idx == -1 or not expr.endswith(")"):
        raise ValueError(
            f"ConditionEntry.expression {expr!r} is malformed (expected 'operator(argument)')"
        )
    op = expr[:paren_idx].strip()
    if not _OPERATOR_NAME_RE.match(op):
        raise ValueError(
            f"ConditionEntry.expression {expr!r} has an invalid operator name {op!r} "
            "(must match [A-Za-z_][A-Za-z0-9_]*)"
        )
    if op in _QUOTED_ARG_OPERATORS:
        return expr
    depth = 0
    in_string = False
    escaped = False
    last_idx = len(expr) - 1
    for idx in range(paren_idx, len(expr)):
        ch = expr[idx]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"ConditionEntry.expression {expr!r} has unbalanced parentheses")
            if depth == 0 and idx != last_idx:
                raise ValueError(
                    f"ConditionEntry.expression {expr!r} closes its argument before "
                    "the end of the expression"
                )
    if depth != 0 or in_string:
        raise ValueError(f"ConditionEntry.expression {expr!r} has unbalanced parentheses")
    return expr


__all__ = [
    "ActionType",
    "AssertFactRequest",
    "AssertFactResponse",
    "AssertSpec",
    "AssertedFact",
    "AuditRecord",
    "CompileRequest",
    "CompileResponse",
    "ConditionEntry",
    "ErrorResponse",
    "EvaluateRequest",
    "EvaluateResponse",
    "EvaluationResult",
    "FactChangeNotification",
    "FactInput",
    "FactPattern",
    "FunctionDefinition",
    "HierarchyDefinition",
    "LogLevel",
    "MatchEvidence",
    "ModuleDefinition",
    "QueryFactsRequest",
    "QueryFactsResponse",
    "RetractFactsRequest",
    "RetractFactsResponse",
    "RuleDefinition",
    "RulesetDefinition",
    "SlotDefinition",
    "SlotType",
    "TemplateDefinition",
    "ThenBlock",
]


# --- Core Models (Section 3) ---


class SlotType(StrEnum):
    """Supported CLIPS slot data types."""

    STRING = "string"
    SYMBOL = "symbol"
    FLOAT = "float"
    INTEGER = "integer"


class SlotDefinition(BaseModel):
    """Definition of a single slot within a template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: SlotType
    required: bool = False
    allowed_values: list[str] | None = None
    default: str | float | int | None = None

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "SlotDefinition.name")

    @model_validator(mode="after")
    def _unquoted_literals_must_be_safe(self) -> SlotDefinition:
        """Guard the deftemplate literals the compiler emits unquoted.

        STRING slots get their ``allowed-strings`` and ``default`` values
        escaped and quoted; every other type is interpolated verbatim.
        """
        if self.type is SlotType.STRING:
            return self
        if self.type is SlotType.SYMBOL:
            for value in self.allowed_values or []:
                _validate_clips_ident(value, "SlotDefinition.allowed_values entry")
        if isinstance(self.default, str):
            if self.type is SlotType.SYMBOL:
                _validate_clips_ident(self.default, "SlotDefinition.default")
            else:
                raise ValueError(
                    f"SlotDefinition.default {self.default!r} must be numeric for a "
                    f"'{self.type.value}' slot"
                )
        return self


class TemplateDefinition(BaseModel):
    """YAML template definition compiled to a CLIPS deftemplate."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    slots: list[SlotDefinition]
    ttl: int | None = None
    scope: Literal["session", "fleet"] = "session"

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "TemplateDefinition.name")

    @model_validator(mode="after")
    def _fleet_slots_must_not_shadow_store_metadata(self) -> TemplateDefinition:
        """``fact_id`` belongs to the FactStore on a shared template.

        A store row is ``{"fact_id": <row id>, **data}`` and the fleet sync
        strips ``fact_id`` before asserting into a peer, so a template that
        declared a slot by that name published a value no peer ever received:
        the publisher decided with it, every peer decided without it. Refuse
        the declaration where the author can see it.
        """
        if self.scope == "fleet" and any(slot.name == "fact_id" for slot in self.slots):
            raise ValueError(
                f"TemplateDefinition {self.name!r}: 'fact_id' is reserved on a "
                "fleet-scoped template — it is the FactStore's own row key and "
                "is removed before the fact reaches a peer. Rename the slot."
            )
        return self


class ConditionEntry(BaseModel):
    """A single slot condition within a fact pattern."""

    model_config = ConfigDict(extra="forbid")

    slot: str = ""
    expression: str = ""
    bind: str | None = Field(
        default=None,
        description=(
            "LHS variable binding for this slot, e.g. ``?sid``. Must start "
            "with ``?`` and be a valid CLIPS symbol. When set, the compiler "
            "emits ``?sid`` in the slot position, making the bound value "
            "available to peer conditions and RHS asserts. "
            "Example: ``ConditionEntry(slot='subject_id', bind='?sid')``."
        ),
    )
    test: str | None = Field(
        default=None,
        description=(
            "Raw CLIPS test conditional element, emitted verbatim as "
            "``(test <test>)`` on the rule LHS. Escape hatch for calling "
            "custom functions registered via ``Engine.register_function`` "
            "(or any CLIPS built-in not covered by fathom's operator "
            "allow-list). When ``test`` is set standalone (no ``slot``, "
            "``expression``, or ``bind``), the pattern emits only the test "
            "CE; when combined with slot constraints, both are emitted. "
            "Example: ``ConditionEntry(test='(my-fn ?sid)')``."
        ),
    )

    @field_validator("slot")
    @classmethod
    def _slot_must_be_clips_ident(cls, v: str) -> str:
        if v:
            _validate_clips_ident(v, "ConditionEntry.slot")
        return v

    @field_validator("expression")
    @classmethod
    def _expression_must_be_operator_form(cls, v: str) -> str:
        if v:
            _validate_expression(v)
        return v

    @field_validator("bind")
    @classmethod
    def _bind_must_be_slot_variable(cls, v: str | None) -> str | None:
        if v is not None and not _SLOT_VAR_RE.match(v):
            raise ValueError(
                f"ConditionEntry.bind must be '?' followed by a CLIPS identifier (got {v!r})"
            )
        return v

    @field_validator("test")
    @classmethod
    def _test_must_be_wrapped(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("ConditionEntry.test must not be empty")
            if not (stripped.startswith("(") and stripped.endswith(")")):
                raise ValueError(
                    f"ConditionEntry.test must be a parenthesized CLIPS expression (got {v!r})"
                )
        return v

    @model_validator(mode="after")
    def _require_bind_or_expression(self) -> ConditionEntry:
        if not self.expression and not self.bind and not self.test:
            raise ValueError("ConditionEntry requires 'expression', 'bind', or 'test'")
        if (self.expression or self.bind) and not self.slot:
            raise ValueError("ConditionEntry requires 'slot' when 'expression' or 'bind' is set")
        if self.test and not (self.expression or self.bind) and self.slot:
            raise ValueError(
                "ConditionEntry: 'slot' has no effect with 'test' alone; "
                "add 'expression' or 'bind' to constrain the slot, or drop "
                "'slot' for a standalone test CE"
            )
        return self


class FactPattern(BaseModel):
    """A fact pattern in a rule's ``when`` clause."""

    model_config = ConfigDict(extra="forbid")

    template: str
    alias: str | None = None
    conditions: list[ConditionEntry]

    @field_validator("template")
    @classmethod
    def _template_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "FactPattern.template")

    @field_validator("alias")
    @classmethod
    def _alias_must_be_clips_ident(cls, v: str | None) -> str | None:
        """The alias is interpolated into generated CLIPS variable names.

        ``compiler._compile_condition`` emits ``?{alias}-{slot}``, so an
        unvalidated alias is a construct-injection hole of exactly the same
        shape as the ``template`` one above:
        ``alias='$v-level)) (test (system "touch /tmp/PWNED")) (agent (level ?zz'``
        compiled cleanly into extra conditional elements.

        The reserved ``p<N>`` forms are refused because that is the
        namespace used for UNALIASED patterns (``f"p{pattern_index}"``).
        Sharing it silently joined two unrelated patterns on one variable:
        pattern 0 aliased ``$p1`` and an unaliased pattern 1 both emitted
        ``?p1-level``.
        """
        if v is None:
            return v
        if not v.startswith("$"):
            raise ValueError(f"FactPattern.alias must start with '$' (got {v!r})")
        _validate_clips_ident(v[1:], "FactPattern.alias")
        if _RESERVED_ALIAS_RE.match(v[1:]):
            raise ValueError(
                f"FactPattern.alias {v!r} is reserved: '$p<number>' is the "
                "namespace generated for unaliased patterns, and reusing it "
                "silently joins two patterns on the same CLIPS variable"
            )
        return v


class ActionType(StrEnum):
    """Decision action types for rule outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"
    SCOPE = "scope"
    ROUTE = "route"


class LogLevel(StrEnum):
    """Audit log verbosity levels."""

    NONE = "none"
    SUMMARY = "summary"
    FULL = "full"


class AssertSpec(BaseModel):
    """A fact assertion emitted from a rule's ``then`` clause.

    Compile-time YAML spec: slot values are strings (CLIPS source text or
    ``?var`` bindings from the LHS). Materialized values after evaluation
    are read back via :class:`AssertedFact`.

    Example:
        >>> spec = AssertSpec(template="decision", slots={"action": "allow"})
        >>> spec.template
        'decision'
    """

    # Same as every other YAML-authoring model: a typo in an `asserts`
    # entry must be an error, not silently dropped.
    model_config = ConfigDict(extra="forbid")

    template: str
    slots: dict[str, str] = Field(default_factory=dict)

    @field_validator("template")
    @classmethod
    def _template_name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "AssertSpec.template")

    @field_validator("slots")
    @classmethod
    def _slot_values_must_be_safe(cls, v: dict[str, str]) -> dict[str, str]:
        for slot_name, slot_value in v.items():
            _validate_clips_ident(slot_name, "AssertSpec slot")
            _validate_slot_value(slot_value)
        return v


class AssertedFact(BaseModel):
    """Snapshot of a user-asserted fact captured during evaluation for audit.

    Distinct from :class:`AssertSpec` (the compile-time YAML spec): slots here
    hold materialized fact values read back from CLIPS, which may be integers,
    strings, symbols, or floats — hence ``dict[str, Any]``.

    Example:
        >>> fact = AssertedFact(template="access-grant", slots={"uid": 42})
        >>> fact.slots["uid"]
        42
    """

    template: str
    slots: dict[str, Any] = Field(default_factory=dict)


class ThenBlock(BaseModel):
    """The ``then`` clause of a rule defining the decision and metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: ActionType | None = None
    reason: str = ""
    log: LogLevel = LogLevel.SUMMARY
    notify: list[str] = Field(default_factory=list)
    attestation: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    scope: str | None = None
    asserts: list[AssertSpec] = Field(
        default_factory=list,
        alias="assert",
        description=(
            "Facts to assert when the rule fires, in order. Each entry is "
            "an :class:`AssertSpec`. YAML authors use the ``assert`` key; "
            "Python callers may use the ``asserts`` attribute name "
            "(``populate_by_name=True``). "
            "Example: ``ThenBlock(action='allow', **{'assert': [AssertSpec("
            "template='audit-log', slots={'uid': '?sid'})]})``."
        ),
    )

    @model_validator(mode="after")
    def _require_action_or_asserts(self) -> ThenBlock:
        if self.action is None and not self.asserts:
            raise ValueError("ThenBlock requires 'action' or non-empty 'assert'")
        return self


class RuleDefinition(BaseModel):
    """A single rule with conditions and an action."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    salience: int = 0
    when: list[FactPattern]
    then: ThenBlock

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "RuleDefinition.name")


class RulesetDefinition(BaseModel):
    """A named ruleset containing rules scoped to a module."""

    model_config = ConfigDict(extra="forbid")

    ruleset: str
    version: str = "1.0"
    module: str
    rules: list[RuleDefinition]

    @field_validator("ruleset")
    @classmethod
    def _ruleset_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "RulesetDefinition.ruleset")

    @field_validator("module")
    @classmethod
    def _module_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "RulesetDefinition.module")


class ModuleDefinition(BaseModel):
    """CLIPS module definition with optional priority."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    priority: int = 0

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "ModuleDefinition.name")


class FunctionDefinition(BaseModel):
    """YAML function definition (classification or raw CLIPS)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    params: list[str]
    hierarchy_ref: str | None = None
    type: Literal["classification", "raw"] = "classification"
    body: str | None = None

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "FunctionDefinition.name")


class HierarchyDefinition(BaseModel):
    """Ordered classification hierarchy (e.g. clearance levels)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    levels: list[str]
    compartments: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "HierarchyDefinition.name")

    @field_validator("levels", "compartments")
    @classmethod
    def _members_must_be_clips_idents(cls, v: list[str] | None) -> list[str] | None:
        for member in v or []:
            _validate_clips_ident(member, "HierarchyDefinition member")
        return v


class MatchEvidence(BaseModel):
    """The working memory that made one rule firing happen.

    ``rule_trace`` says a rule fired; this says which facts it fired on.
    One entry per firing, so a rule that fires twice on different facts
    appears twice. Populated only on an ``Engine(match_evidence=True)``.
    """

    rule: str
    facts: list[AssertedFact] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """Result returned by :meth:`Engine.evaluate` after rule execution."""

    decision: str | None = None
    reason: str | None = None
    rule_trace: list[str] = Field(default_factory=list)
    module_trace: list[str] = Field(default_factory=list)
    duration_us: int = 0
    attestation_token: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    #: Per-firing match basis, empty unless the engine was built with
    #: ``match_evidence=True``.
    match_evidence: list[MatchEvidence] = Field(default_factory=list)


class AuditRecord(BaseModel):
    """Immutable audit record written to the audit sink after evaluation."""

    timestamp: str
    session_id: str
    input_facts: list[dict[str, Any]] | None = None
    modules_traversed: list[str]
    rules_fired: list[str]
    decision: str | None
    reason: str | None
    duration_us: int
    metadata: dict[str, str] = Field(default_factory=dict)
    asserted_facts: list[AssertedFact] | None = None
    #: Per-firing match basis, carried through from the evaluation result.
    #: ``None`` on an engine built without ``match_evidence=True``.
    match_evidence: list[MatchEvidence] | None = None
    #: The evaluation's attestation JWT, when the engine was given an
    #: attestation service. Carried on the record so an exported line can be
    #: verified on its own; ``None`` on an engine that does not sign.
    attestation_token: str | None = None


# --- REST Models (Phase 2) ---


class FactInput(BaseModel):
    """REST API input for a single fact assertion."""

    template: str
    data: dict[str, Any]


class EvaluateRequest(BaseModel):
    """REST API request body for the evaluate endpoint."""

    #: The CLIPS join is quadratic in the number of facts, so the byte cap on
    #: the request body (``FATHOM_MAX_REQUEST_BYTES``) does not bound the CPU
    #: this endpoint can be made to burn.
    #:
    #: The cap must stay BELOW what ``Engine``'s activation budget can serve,
    #: or the endpoint advertises a limit it cannot honour. With the default
    #: ``run_limit`` of 100_000 and a two-template join, n facts produce about
    #: ``(n/2)**2`` activations, so the budget is exhausted at ~632 facts. A
    #: cap of 1000 meant every request between ~632 and 1000 mixed facts got
    #: a 503 despite being inside the documented limit — measured on
    #: ``examples/01-hello-allow-deny``: 600 facts -> 200, 640 -> 503.
    #:
    #: 500 facts is ~62_500 activations, comfortably inside the budget, and
    #: still generous for real callers (~0.04s on the reference ruleset).
    #: Raising this REQUIRES raising ``_DEFAULT_RUN_LIMIT`` in step; a deeper
    #: join (three templates) is cubic and can exhaust the budget below even
    #: this cap, which is why the budget exists.
    facts: list[FactInput] = Field(max_length=500)
    ruleset: str
    session_id: str | None = None


class EvaluateResponse(BaseModel):
    """REST API response body from the evaluate endpoint.

    Mirrors :class:`EvaluationResult` field for field, and the gRPC
    ``EvaluateResponse`` message alongside it. A caller who moves between the
    two transports, or between the library and either of them, should not have
    to discover that one of them drops a field the others carry.
    """

    decision: str | None
    reason: str | None
    rule_trace: list[str]
    module_trace: list[str]
    duration_us: int
    #: ``then.metadata`` of the rule that wrote the decision.
    metadata: dict[str, str] = Field(default_factory=dict)
    #: Ed25519 JWT over this evaluation. Non-null only when the server was
    #: given an attestation service.
    attestation_token: str | None = None


class AssertFactRequest(BaseModel):
    """REST API request body for POST /v1/facts."""

    session_id: str
    template: str
    data: dict[str, Any]


class AssertFactResponse(BaseModel):
    """REST API response body from POST /v1/facts."""

    success: bool = True


class QueryFactsRequest(BaseModel):
    """REST API request body for POST /v1/query."""

    session_id: str
    template: str
    filter: dict[str, Any] | None = None


class QueryFactsResponse(BaseModel):
    """REST API response body from POST /v1/query."""

    facts: list[dict[str, Any]]


class RetractFactsRequest(BaseModel):
    """REST API request body for DELETE /v1/facts."""

    session_id: str
    template: str
    filter: dict[str, Any] | None = None


class RetractFactsResponse(BaseModel):
    """REST API response body from DELETE /v1/facts."""

    retracted_count: int


class ErrorResponse(BaseModel):
    """REST API error response body."""

    error: str
    detail: str
    field: str | None = None


class CompileRequest(BaseModel):
    """REST API request body for the compile endpoint."""

    yaml_content: str = Field(max_length=1_000_000)


class CompileResponse(BaseModel):
    """REST API response body from the compile endpoint."""

    clips: str
    errors: list[str] = Field(default_factory=list)


# --- Fleet Models (Phase 2 — FactStore) ---


class FactChangeNotification(BaseModel):
    """Notification emitted when a fact is asserted or retracted."""

    template: str
    fact_id: str
    action: Literal["assert", "retract"]
    data: dict[str, Any] | None = None
