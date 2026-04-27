---
title: Audit & Attestation
summary: Why every Fathom evaluation is recorded, and how the optional Ed25519 JWT turns a log entry into portable proof.
audience: [app-developers, rule-authors]
diataxis: explanation
status: stable
last_verified: 2026-04-27
sources:
  - src/fathom/audit.py
  - src/fathom/attestation.py
  - src/fathom/engine.py
  - src/fathom/models.py
---

# Audit & Attestation

The [Five Primitives](./five-primitives.md) page describes what rules look like
and how they compile. The [Runtime & Working Memory](./runtime-and-working-memory.md)
page describes what happens when you call `evaluate()`. This page is about what
Fathom writes down *afterwards* — the record of each decision, and the optional
cryptographic signature that turns that record into something you can show a
third party months later.

Two separate mechanisms share this page because they solve two halves of the
same problem:

- **The audit log** answers "what did the engine decide, on what inputs,
  citing which rules?" for every evaluation. It's a local, append-only record.
- **Attestation** answers "prove it." An Ed25519 signature over the decision
  and input digest lets an off-site verifier confirm the record is genuine
  without trusting the box that produced it.

The audit log is always available (default sink is a no-op). Attestation is
opt-in — you construct the engine with a key.

## Why a decision engine keeps records

Fathom is deterministic: given the same rule pack, the same working memory,
and the same module focus stack, it produces the same decision. That's only
useful if you can reconstruct what happened on a specific call weeks later
— which facts were present, which rules fired, what the final decision was.

Stateless policy engines can get away with "replay the request" — the input
fully determines the output. Fathom can't, because [working memory persists
across evaluations](./runtime-and-working-memory.md). The fact that caused a
deny today was asserted by a request three hours ago. Without a record
written at decision time, that context is gone.

The audit log is that record. Attestation adds one property on top: a
signature bound to the decision and inputs, so the record can survive
leaving the box it was written on.

## Audit log shape

Every successful evaluation produces one `AuditRecord`
(`src/fathom/models.py`):

```python
class AuditRecord(BaseModel):
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
```

Field by field:

- **`timestamp`** — UTC ISO-8601, set inside `AuditLog.record()` via
  `datetime.now(UTC).isoformat()`. Not taken from the caller, so clients
  can't back-date entries.
- **`session_id`** — the engine's session identifier. Lets you stitch
  evaluations together when reconstructing what a single agent did.
- **`input_facts`** — optional. The caller can pass a representation of the
  facts asserted for this evaluation; Fathom does not snapshot working
  memory into this field automatically.
- **`modules_traversed`** / **`rules_fired`** — copied from
  `EvaluationResult.module_trace` and `rule_trace`. The modules active
  during inference and the fully-qualified `module::rule` names in fire
  order.
- **`decision`** / **`reason`** — the `action` and `reason` read off the
  last `__fathom_decision` fact. `None` if no rule asserted a decision.
- **`duration_us`** — microseconds spent in the inference loop.
- **`metadata`** — arbitrary string key/value pairs propagated from the
  decision's rule.
- **`asserted_facts`** — populated only when at least one loaded rule
  declares an RHS `asserts` block (see below).

Records are written one-per-line as JSON. JSON Lines is trivially grep-able,
`jq`-able, and concatenatable; it's what most log aggregators expect.
Append-only at the process level means a local attacker can truncate or
overwrite the file but not silently rewrite a past entry without touching
its bytes — detection lives at the filesystem boundary (log shipper,
immutable volume, or WORM bucket underneath).

## Audit sinks

`AuditSink` is a tiny `Protocol` with one method
(`src/fathom/audit.py`):

```python
@runtime_checkable
class AuditSink(Protocol):
    def write(self, record: AuditRecord) -> None: ...
```

Two implementations ship with Fathom:

- **`FileSink(path)`** — writes `record.model_dump_json() + "\n"` to the
  given file in append mode. The constructor creates parent directories and
  `touch`es the file, so pointing it at a fresh path Just Works.
- **`NullSink`** — `write()` is a no-op. This is the default when you
  construct an `Engine` without passing `audit_sink`.

Anything satisfying the protocol is a valid sink. A production deployment
might write to S3, publish to Kafka, call out to syslog, or fan out to
several of those — none of which Fathom provides out of the box, but all of
which are ten lines of Python on top of the protocol.

## Default is off

```python
from fathom import Engine
from fathom.audit import FileSink

engine = Engine(audit_sink=FileSink("/var/log/fathom/audit.jsonl"))
```

Without that argument, `Engine.__init__` installs a `NullSink`:

```python
self._audit_log = AuditLog(audit_sink or NullSink())
```

Audit is opt-in for a reason: many embedding contexts — tests, notebooks,
short-lived agents — have no use for a durable log, and making file I/O
mandatory would turn every `evaluate()` into a write. Production passes a
real sink; everything else keeps working with zero ceremony.

## What gets recorded when

The recording happens inside `Engine.evaluate()`. The sequence:

1. **Pre-snapshot user facts** — but only if `self._has_asserting_rules` is
   true. That flag is set at load time when any compiled rule declares a
   non-empty `asserts` block. If no loaded rule can assert new facts, the
   snapshot is skipped entirely — there's nothing to diff against.
2. **Run inference** — `self._evaluator.evaluate()` returns an
   `EvaluationResult` with `decision`, `reason`, `rule_trace`,
   `module_trace`, and `duration_us`.
3. **Sign, if configured** — if the engine was constructed with an
   `attestation_service`, call `sign(result, self._session_id)` and store the
   returned JWT on `result.attestation_token`.
4. **Diff pre/post snapshots** — a second `_snapshot_user_facts()` call,
   differenced against the pre-snapshot, yields the facts the rules
   asserted during this evaluation. Order is preserved from the post
   snapshot; equality is keyed on `(template, sorted(slots.items()))`.
5. **Record** — `self._audit_log.record(result, session_id,
   asserted_facts=...)` constructs the `AuditRecord` and hands it to the
   sink.
6. **Metrics** — `self._metrics.record_evaluation(...)` runs in a `finally`
   so metrics are updated even if recording raised.

Two things worth flagging:

- `asserted_facts` is `None` when no loaded rule has an `asserts` block,
  and also when asserting rules exist but none fired. An empty list is
  collapsed to `None`, so the record distinguishes "didn't try to capture
  this" from "captured nothing."
- Signing happens *before* the audit record is written. The JWT ends up
  on the `EvaluationResult` the caller receives but is **not** one of the
  `AuditRecord` fields — the log records the decision; the token is
  returned to the caller to store or forward separately.

## Attestation as signed proof

`AttestationService` (`src/fathom/attestation.py`) turns an evaluation into a
JWT signed with an Ed25519 key. Construct one of two ways:

```python
from fathom.attestation import AttestationService

# Ephemeral keypair — fine for tests, wrong for production.
service = AttestationService.generate_keypair()

# Stable key — load from secure storage at startup.
service = AttestationService.from_private_key_bytes(pem_bytes)
```

Pass it to the engine alongside (or instead of) a sink:

```python
engine = Engine(
    audit_sink=FileSink("/var/log/fathom/audit.jsonl"),
    attestation_service=service,
)
```

The algorithm is `EdDSA` (PyJWT's name for Ed25519-over-JWT). Ed25519 was
picked because signatures are 64 bytes, verification is fast, and the
public-key PEM is small enough to embed in a verifier image.

The payload is deliberately narrow:

```python
{
    "iss":        "fathom",
    "iat":        int(time.time()),
    "decision":   result.decision,
    "rule_trace": result.rule_trace,
    "input_hash": sha256(json.dumps(input_facts or [], sort_keys=True)).hexdigest(),
    "session_id": session_id,
}
```

What's **in** the signature: the decision, the rules that produced it, the
session, an issuance timestamp, and a hash of the caller-supplied input
facts. What's **not**: the facts themselves (they're hashed, not embedded),
the reason string, the metadata dict, and the evaluation duration — those
remain in the audit log but sit outside the signed envelope. The JWT
alone proves *what* was decided; to prove *why*, pair it with the
matching audit-log line.

## Verifying an attestation

```python
from fathom.attestation import verify_token

payload = verify_token(jwt_string, service.public_key)
```

`verify_token` re-decodes the JWT with `algorithms=["EdDSA"]` and the
supplied public key, returning the payload dict. Any failure — bad
signature, malformed token, wrong algorithm — raises `AttestationError`.

The public key can be serialised for distribution:

```python
pem = service.public_key_pem()  # PEM SubjectPublicKeyInfo bytes
```

Two fields in the payload are worth calling out:

- **`iat`** gives freshness. A verifier that has its own clock and a known
  signing-key issuance window can reject tokens from outside it without
  contacting the signer.
- **`input_hash`** binds the token to a specific input fact set. A verifier
  reconstructs the hash from the inputs it has and compares; a mismatch
  means someone changed either the facts or the token.

## Threat model

What audit + attestation *do* protect against:

- **Disputes about what was decided.** A signed `decision` and `rule_trace`
  pin down the answer and the rules that produced it.
- **Tampering with exported logs.** An attacker who modifies an audit line
  after export can't re-sign it without the private key; `verify_token`
  fails.
- **Input substitution.** The `input_hash` commits the token to a specific
  set of facts. Swap the facts and the hash stops matching.

What they *don't* protect against:

- **A compromised engine.** If the process producing audit records is
  controlled by an attacker, it simply never calls `AuditLog.record()`, or
  signs a fabricated result. Fathom cannot attest to its own integrity;
  that's the job of whatever loads the binary.
- **Private-key theft.** Ed25519 is only as strong as the secrecy of the
  signing key. Key custody is out of scope.
- **Side channels.** Nothing here prevents an observer from inferring
  decisions from timing, cache behaviour, or downstream effects.

## Declaring attestation on a rule

`ThenBlock` carries an `attestation: bool` field
(`src/fathom/models.py`). It is compiled into the `__fathom_decision`
fact's `attestation` slot — the `TRUE`/`FALSE` value is visible to
anything reading the decision fact and surfaces through the audit log's
decision chain. It is **not** a switch that turns JWT signing on or off:
the engine decides whether to sign based on whether an
`attestation_service` was passed to `Engine(...)`, not on the flag in the
rule. Think of the rule-level `attestation` field as declarative
metadata — "this rule claims its decisions should be attested" — that
downstream consumers (audit readers, policy linters) can act on.

## How they fit together

Audit is the always-on local story: every evaluation gets one
`AuditRecord`, written synchronously to whatever sink the engine was given.
`NullSink` by default, `FileSink` for development, anything that satisfies
the `AuditSink` protocol in production.

Attestation is the optional portable story: construct the engine with an
`AttestationService` and each `EvaluationResult` comes back carrying an
Ed25519-signed JWT. The token travels independently of the log; the log
keeps the full context; together they give a downstream auditor everything
they need.

See [Runtime & Working Memory](./runtime-and-working-memory.md) for the
evaluation loop these records describe, and
[Writing Rules](../how-to/writing-rules.md) for the YAML-level `attestation`
flag on a rule's `then` block.
