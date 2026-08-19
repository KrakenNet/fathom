"""JSON API backing the creem Policy Studio single-page app.

These routes give the React/Babel SPA (served from
:mod:`fathom_studio.creem`) the **real** engine surface it needs, so the hero
flows are never fabricated:

============================  =================================================
Route                         Backing
============================  =================================================
``GET /studio/api/scenarios`` the bundled :data:`~fathom_studio.scenarios.SCENARIOS`
``GET /studio/api/rulesets``  the rulesets the studio can evaluate
``GET /studio/api/ruleset/{id}`` real template / rule / module registries
``POST /studio/api/evaluate`` real ``Engine`` evaluation + a signed audit record
``GET /studio/api/audit``     the in-memory hash-linked, Ed25519-signed chain
``POST /studio/api/audit/verify`` cryptographic verify of an audit signature
============================  =================================================

The Bench *Run* and every Live Wire packet POST to ``/evaluate``, which builds
a fresh :class:`~fathom.engine.Engine` for the requested ruleset (the same
stateless path :func:`fathom.integrations.rest.evaluate` uses without a
session), asserts the facts, evaluates, and appends a real audit record whose
hash chains to the previous record and whose signature is a genuine Ed25519
attestation token. Live Wire traffic is **synthetic** (generated in the
browser and clearly labelled as such) but each packet is a real evaluation;
rule / template / scenario edits made in the UI are session-state only.

Rulesets resolve under ``FATHOM_RULESET_ROOT`` when set, otherwise the demo
rulesets shipped as package data (:mod:`fathom_studio.rulesets`), so the studio
works out of the box from a checkout *and* from an installed wheel.

Every route is gated on ``FATHOM_API_TOKEN`` via
:func:`fathom_studio.auth.require_auth` — the same token the mounted REST app
requires — because these routes load rulesets and drive the real engine.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from fathom.engine import Engine
from fathom.integrations.paths import PathJailError, resolve_ruleset
from pydantic import BaseModel, Field

from fathom_studio.auth import require_auth
from fathom_studio.rulesets import RulesetRootError, ruleset_root
from fathom_studio.scenarios import SCENARIOS

if TYPE_CHECKING:
    from collections.abc import Sequence

router = APIRouter(prefix="/studio/api", dependencies=[Depends(require_auth)])

#: Cap on retained audit records (oldest dropped) to bound memory.
_AUDIT_MAX = 200


def _resolve(ruleset: str) -> str:
    """Jail *ruleset* under the ruleset root, raising 400 on escape, 404 if absent."""
    try:
        resolved = resolve_ruleset(ruleset_root(), ruleset)
    except PathJailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RulesetRootError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not Path(resolved).is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown ruleset '{ruleset}'")
    return str(resolved)


#: Cache of compiled engines per resolved ruleset path, reused for registry
#: dumps. Evaluation always builds a fresh engine so working memory is clean.
_registry_engines: dict[str, Engine] = {}


def _registry_engine(ruleset: str) -> Engine:
    """Return a cached engine for *ruleset* (registries only; never evaluated)."""
    resolved = _resolve(ruleset)
    engine = _registry_engines.get(resolved)
    if engine is None:
        try:
            engine = Engine.from_rules(resolved)
        except Exception as exc:  # noqa: BLE001 — surface compile/load failure as 400
            raise HTTPException(
                status_code=400, detail=f"Could not load ruleset '{ruleset}': {exc}"
            ) from exc
        _registry_engines[resolved] = engine
    return engine


# --------------------------------------------------------------------------
# Scenarios + rulesets
# --------------------------------------------------------------------------
def _scenario_payload() -> list[dict[str, Any]]:
    """Serialise the bundled scenarios into ``{id,title,description,ruleset,facts}``."""
    payload: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        payload.append(
            {
                "id": scenario.id,
                "title": scenario.title,
                "description": scenario.description,
                "ruleset": scenario.ruleset,
                "facts": [
                    {"template": template, "data": data} for template, data in scenario.facts()
                ],
            }
        )
    return payload


@router.get("/scenarios")
async def scenarios() -> dict[str, Any]:
    """Return the bundled, real example scenarios the Bench seeds from."""
    return {"items": _scenario_payload()}


@router.get("/rulesets")
async def rulesets() -> dict[str, Any]:
    """Return the distinct rulesets referenced by the bundled scenarios."""
    seen: dict[str, str] = {}
    for scenario in SCENARIOS:
        seen.setdefault(scenario.ruleset, scenario.title)
    items = [{"id": ruleset, "label": title} for ruleset, title in seen.items()]
    return {"items": items}


def _serialize_pattern(pattern: Any) -> dict[str, Any]:
    """Serialise a rule's :class:`FactPattern` with its slot conditions intact.

    The studio rule view renders the real ``when`` clause, so each pattern's
    conditions (slot / expression / bind / test) must survive — not just the
    template name. Empty fields are dropped to keep the payload terse.
    """
    conditions: list[dict[str, str]] = []
    for c in pattern.conditions:
        entry = {
            k: v
            for k, v in (
                ("slot", c.slot),
                ("expression", c.expression),
                ("bind", c.bind),
                ("test", c.test),
            )
            if v
        }
        conditions.append(entry)
    out: dict[str, Any] = {"template": pattern.template, "conditions": conditions}
    if pattern.alias:
        out["alias"] = pattern.alias
    return out


def _dump_ruleset(ruleset: str) -> dict[str, Any]:
    """Dump the real template / rule / module registries of *ruleset*."""
    engine = _registry_engine(ruleset)
    templates = [
        {
            "name": t.name,
            "description": t.description,
            "slots": [
                {
                    "name": s.name,
                    "type": str(s.type),
                    "required": s.required,
                    "allowed_values": s.allowed_values,
                }
                for s in t.slots
            ],
        }
        for t in engine.template_registry.values()
    ]
    rules = [
        {
            "name": r.name,
            "description": r.description,
            "salience": r.salience,
            "decision": str(r.then.action) if r.then.action else "log",
            "reason": r.then.reason,
            "templates": sorted({p.template for p in r.when}),
            "when": [_serialize_pattern(p) for p in r.when],
        }
        for r in engine.rule_registry.values()
    ]
    modules = [
        {"name": m.name, "description": m.description} for m in engine.module_registry.values()
    ]
    return {"ruleset": ruleset, "templates": templates, "rules": rules, "modules": modules}


@router.get("/ruleset/{ruleset}")
async def ruleset_detail(ruleset: str) -> dict[str, Any]:
    """Return the real templates / rules / modules for *ruleset*."""
    return _dump_ruleset(ruleset)


# --------------------------------------------------------------------------
# Evaluate (real engine) + signed audit chain
# --------------------------------------------------------------------------
class _FactIn(BaseModel):
    """One fact to assert before evaluation."""

    template: str
    data: dict[str, Any] = Field(default_factory=dict)


class _EvaluateIn(BaseModel):
    """Request body for ``POST /studio/api/evaluate``."""

    ruleset: str
    facts: list[_FactIn] = Field(default_factory=list)


def _evaluate(ruleset: str, facts: Sequence[_FactIn]) -> dict[str, Any]:
    """Build a fresh engine for *ruleset*, assert *facts*, and evaluate.

    Mirrors the stateless ``/v1/evaluate`` path (a fresh ``Engine`` per call)
    so working memory never leaks between evaluations.
    """
    resolved = _resolve(ruleset)
    try:
        engine = Engine.from_rules(resolved)
    except Exception as exc:  # noqa: BLE001 — surface load failure as 400
        raise HTTPException(
            status_code=400, detail=f"Could not load ruleset '{ruleset}': {exc}"
        ) from exc
    for fact in facts:
        try:
            engine.assert_fact(fact.template, fact.data)
        except Exception as exc:  # noqa: BLE001 — bad fact is a client error
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = engine.evaluate()
    return {
        "decision": result.decision,
        "reason": result.reason,
        "rule_trace": list(result.rule_trace),
        "module_trace": list(result.module_trace),
        "duration_us": result.duration_us,
        "rules": _dump_ruleset(ruleset)["rules"],
    }


#: In-memory hash-linked audit chain, newest first. Each record carries the
#: previous record's hash and a real Ed25519 attestation token.
_AUDIT: list[dict[str, Any]] = []
_AUDIT_SEQ = 0

#: Lazily-built, process-stable attestation service so a signature minted on a
#: record can be verified by ``POST /studio/api/audit/verify``.
_ATTESTATION: Any = None


def _attestation() -> Any:
    """Return the process-stable :class:`AttestationService`, building once."""
    global _ATTESTATION
    if _ATTESTATION is None:
        from fathom.attestation import AttestationService

        _ATTESTATION = AttestationService.generate_keypair()
    return _ATTESTATION


def _record_audit(
    ruleset: str, facts: Sequence[_FactIn], result: dict[str, Any]
) -> dict[str, Any]:
    """Append a hash-linked, Ed25519-signed audit record and return it."""
    global _AUDIT_SEQ
    _AUDIT_SEQ += 1
    seq = _AUDIT_SEQ
    prev_hash = _AUDIT[0]["hash"] if _AUDIT else "0" * 16
    body = {
        "seq": seq,
        "decision": result["decision"],
        "reason": result["reason"],
        "ruleset": ruleset,
        "facts": [{"template": f.template, "data": f.data} for f in facts],
        "rule_trace": result["rule_trace"],
    }
    digest = hashlib.sha256(
        (prev_hash + json.dumps(body, sort_keys=True, default=str)).encode()
    ).hexdigest()[:16]
    signature: str | None = None
    try:
        signature = _attestation().sign_event(
            {
                "seq": seq,
                "hash": digest,
                **{
                    "decision": result["decision"],
                    "ruleset": ruleset,
                },
            }
        )
    except Exception:  # noqa: BLE001 — attestation is best-effort (optional dep)
        signature = None
    record = {
        **body,
        "ts": datetime.now(UTC).isoformat(),
        "module_trace": result["module_trace"],
        "duration_us": result["duration_us"],
        "prev_hash": prev_hash,
        "hash": digest,
        "signature": signature,
    }
    _AUDIT.insert(0, record)
    if len(_AUDIT) > _AUDIT_MAX:
        del _AUDIT[_AUDIT_MAX:]
    return record


@router.post("/evaluate")
async def evaluate(body: _EvaluateIn) -> dict[str, Any]:
    """Evaluate facts against a ruleset with the real engine; log a signed record.

    Returns the real ``decision`` / ``reason`` / ``rule_trace`` /
    ``module_trace`` / ``duration_us`` (never fabricated), the ruleset's rule
    registry for trace rendering, and the audit record just appended.
    """
    result = _evaluate(body.ruleset, body.facts)
    record = _record_audit(body.ruleset, body.facts, result)
    return {**result, "audit": record}


@router.get("/audit")
async def audit() -> dict[str, Any]:
    """Return the in-memory, hash-linked, signed audit chain (newest first)."""
    return {"items": list(_AUDIT), "count": len(_AUDIT)}


class _VerifyIn(BaseModel):
    """Request body for ``POST /studio/api/audit/verify``."""

    signature: str


@router.post("/audit/verify")
async def audit_verify(body: _VerifyIn) -> dict[str, Any]:
    """Cryptographically verify an audit record's Ed25519 signature."""
    if not body.signature:
        return {"verified": False, "error": "no signature"}
    try:
        from fathom.attestation import verify_token
        from fathom.errors import AttestationError
    except ImportError:
        return {"verified": False, "error": "attestation extra not installed"}
    try:
        claims = verify_token(body.signature, _attestation().public_key)
    except AttestationError:
        return {"verified": False, "error": "signature verification failed"}
    return {"verified": True, "claims": claims}


def _reset_audit_for_tests() -> None:
    """Clear the audit chain (test helper)."""
    global _AUDIT_SEQ
    _AUDIT.clear()
    _AUDIT_SEQ = 0
