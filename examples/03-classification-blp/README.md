# Example 03 — Bell-LaPadula with Compartments

**Complexity:** Intermediate+
**Concepts:** hierarchies, classification functions, cross-fact references,
compartments, multi-level security

A full Bell-LaPadula multi-level security implementation in YAML — the kind
of policy that goes into hand-written code in most systems.

## Concepts

- **Hierarchies** (`hierarchies/clearance.yaml`) define a totally ordered set
  of classification levels. Fathom auto-generates `rank`, `below`,
  `meets-or-exceeds` and `within-scope` CLIPS deffunctions for each
  hierarchy you register.
- **Classification functions** (`functions/clearance.yaml`) tie the
  hierarchy to the rule operators (`below(...)`, `meets_or_exceeds(...)`).
- **Compartments** are pipe-delimited strings (e.g. `"SI|TK|NOFORN"`) that
  enforce *need-to-know*. `has_compartments(other)` is a subset check.
- **Cross-fact references** like `$req.subject_id` and `$o.classification`
  let one fact pattern reference values bound by another. **Pattern
  ordering matters**: the binding pattern must come before the reference.

## Rules

| # | Salience | Property         | Effect |
|---|----------|------------------|--------|
| 1 | 100      | Simple security  | deny if subject clearance below resource classification (no read up) |
| 2 | 100      | *-property       | deny if resource classification below subject clearance (no write down) |
| 3 | 50       | (allow read)     | clearance dominates AND subject compartments ⊇ resource compartments |
| 4 | 50       | (allow write)    | clearance dominated AND resource compartments ⊇ subject compartments |

Anything that doesn't match an allow rule and isn't explicitly denied falls
through to the engine's default `deny`.

## Run it

```bash
uv run python examples/03-classification-blp/main.py
```

You'll see eleven scenarios covering reads, writes, and compartment
mismatches against a five-level hierarchy:

```
read  alice  top-secret[-]    -> intel-01     secret[-]      => allow
read  bob    confidential[-]  -> intel-01     secret[-]      => deny  (read-up)
read  diana  secret[SI|TK]    -> sigint-04    secret[SI]     => allow
read  eve    secret[SI]       -> sigint-04    secret[SI|TK]  => deny  (missing compartment)
write alice  top-secret[-]    -> public-blog  unclassified[-] => deny (write-down)
...
```

## Layout

```
03-classification-blp/
  hierarchies/clearance.yaml   level ordering
  functions/clearance.yaml     register classification op family
  templates/blp.yaml           subject, resource, access_request
  modules/blp.yaml             single 'blp' module
  rules/blp.yaml               4 rules: 2 deny, 2 allow
  main.py                      11 scenarios across read/write/compartments
```
