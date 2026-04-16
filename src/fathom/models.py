"""Pydantic data models for Fathom runtime."""

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
            raise ValueError(
                f"slot s-expression {value!r} must end with ')'"
            )
        depth = 0
        for ch in value:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError(
                        f"slot s-expression {value!r} has unbalanced parentheses"
                    )
        if depth != 0:
            raise ValueError(
                f"slot s-expression {value!r} has unbalanced parentheses"
            )
        return value
    # Plain string literal — reject embedded control chars that would
    # terminate the CLIPS string when escaped back out.
    if "\x00" in value:
        raise ValueError("slot value must not contain NUL bytes")
    return value


# --- Core Models (Section 3) ---


class SlotType(StrEnum):
    """Supported CLIPS slot data types."""

    STRING = "string"
    SYMBOL = "symbol"
    FLOAT = "float"
    INTEGER = "integer"


class SlotDefinition(BaseModel):
    """Definition of a single slot within a template."""

    name: str
    type: SlotType
    required: bool = False
    allowed_values: list[str] | None = None
    default: str | float | int | None = None


class TemplateDefinition(BaseModel):
    """YAML template definition compiled to a CLIPS deftemplate."""

    name: str
    description: str = ""
    slots: list[SlotDefinition]
    ttl: int | None = None
    scope: Literal["session", "fleet"] = "session"

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "TemplateDefinition.name")


class ConditionEntry(BaseModel):
    """A single slot condition within a fact pattern."""

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

    @field_validator("bind")
    @classmethod
    def _bind_must_start_with_question_mark(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("?"):
            raise ValueError(f"ConditionEntry.bind must start with '?' (got {v!r})")
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
                    f"ConditionEntry.test must be a parenthesized CLIPS "
                    f"expression (got {v!r})"
                )
        return v

    @model_validator(mode="after")
    def _require_bind_or_expression(self) -> ConditionEntry:
        if not self.expression and not self.bind and not self.test:
            raise ValueError(
                "ConditionEntry requires 'expression', 'bind', or 'test'"
            )
        if (self.expression or self.bind) and not self.slot:
            raise ValueError(
                "ConditionEntry requires 'slot' when 'expression' or 'bind' is set"
            )
        if self.test and not (self.expression or self.bind) and self.slot:
            raise ValueError(
                "ConditionEntry: 'slot' has no effect with 'test' alone; "
                "add 'expression' or 'bind' to constrain the slot, or drop "
                "'slot' for a standalone test CE"
            )
        return self


class FactPattern(BaseModel):
    """A fact pattern in a rule's ``when`` clause."""

    template: str
    alias: str | None = None
    conditions: list[ConditionEntry]


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

    model_config = ConfigDict(populate_by_name=True)

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

    name: str
    description: str = ""
    priority: int = 0

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "ModuleDefinition.name")


class FunctionDefinition(BaseModel):
    """YAML function definition (classification, temporal, or raw CLIPS)."""

    name: str
    description: str = ""
    params: list[str]
    hierarchy_ref: str | None = None
    type: Literal["classification", "temporal", "raw"] = "classification"
    body: str | None = None

    @field_validator("name")
    @classmethod
    def _name_must_be_clips_ident(cls, v: str) -> str:
        return _validate_clips_ident(v, "FunctionDefinition.name")


class HierarchyDefinition(BaseModel):
    """Ordered classification hierarchy (e.g. clearance levels)."""

    name: str
    levels: list[str]
    compartments: list[str] | None = None


class EvaluationResult(BaseModel):
    """Result returned by :meth:`Engine.evaluate` after rule execution."""

    decision: str | None = None
    reason: str | None = None
    rule_trace: list[str] = Field(default_factory=list)
    module_trace: list[str] = Field(default_factory=list)
    duration_us: int = 0
    attestation_token: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


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


# --- REST Models (Phase 2) ---


class FactInput(BaseModel):
    """REST API input for a single fact assertion."""

    template: str
    data: dict[str, Any]


class EvaluateRequest(BaseModel):
    """REST API request body for the evaluate endpoint."""

    facts: list[FactInput]
    ruleset: str
    session_id: str | None = None


class EvaluateResponse(BaseModel):
    """REST API response body from the evaluate endpoint."""

    decision: str | None
    reason: str | None
    rule_trace: list[str]
    module_trace: list[str]
    duration_us: int
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
