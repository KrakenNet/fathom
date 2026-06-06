# SSVC rule pack

Reference implementation of **Stakeholder-Specific Vulnerability
Categorization (SSVC)** decision trees — one module per tree:

| Module | Tree | Branches | Decision labels |
|---|---|---|---|
| `ssvc_supplier` | CERT/CC supplier patch-development priority (table 1.0.0) | 36 | `defer`, `scheduled`, `out-of-cycle`, `immediate` |
| `ssvc_deployer` | CERT/CC deployer patch-application priority (table 1.0.0) | 72 | `defer`, `scheduled`, `out-of-cycle`, `immediate` |
| `ssvc_cisa` | CISA SSVC v2.0.3 vulnerability triage | 36 | `Track`, `Track*`, `Attend`, `Act` |

Every published branch is exactly one rule (no cartesian expansion — tuples
not in the published tree fall through to the engine's default decision).

## Provenance

- **Enumeration source:** the decision-table CSVs in `references/csv/`,
  archived from the [CERT/CC SSVC repository](https://github.com/CERTCC/SSVC)
  (`data/csv/ssvc/` and `data/csv/cisa/`) and sha256-pinned in
  `references/SHA256SUMS`.
- **CISA tree cross-check:** the archived CISA SSVC Guide
  (`references/cisa-ssvc-guide-508c.pdf`, fetched via the Internet Archive —
  the canonical `cisa.gov` URL is bot-gated) publishes the full 36-row tree
  as Table 9 (p.10); it matches `csv/cisa_coordinator_2_0_3.csv` on all 36
  branches.
- **Deployer tree cross-check:** `references/certcc-deployer-tree-2023.pdf`
  (CERT/CC one-pager, 2023) depicts the same 72-leaf tree as
  `csv/deployer_patch_application_priority_1_0_0.csv` (outcome distribution
  defer 7 / scheduled 42 / out-of-cycle 20 / immediate 3).
- **Methodology reference:** `references/certcc-ssvc-v2.0-paper.pdf`
  ("Prioritizing Vulnerability Response: A Stakeholder-Specific Vulnerability
  Categorization, Version 2.0", SEI/CERT-CC, April 2021). Note its tree
  *figures* are v2.0-era: the deployer figure still uses Utility (108 leaves)
  and at least one supplier leaf differs from the current published table —
  the pinned CSVs are authoritative for this pack.
- **Branch lists:** `references/branches-{supplier,deployer,cisa}.yaml`,
  generated from the CSVs by `scripts/generate_ssvc_rules.py` (which also
  generates `rules/*.yaml`). CI verifies the YAML matches the pinned CSVs
  row for row.

### Value mapping

CSV values are mapped to CLIPS symbols by `scripts/generate_ssvc_rules.py`:

| CSV value | Symbol |
|---|---|
| `public poc` | `poc` |
| `super effective` | `super_effective` |
| `very high` | `very_high` |

All other values pass through unchanged (spaces would become underscores).
Decision labels are carried verbatim in the string-typed `metadata` slot
(`out-of-cycle`, `Track*` etc. never reach the CLIPS symbol table).

## Required input contract

Each tree reads four input facts; assert the facts for the tree you want
plus the pack metadata fact, then evaluate:

```python
from fathom import Engine
from fathom.rule_packs import ssvc

engine = Engine()
engine.load_pack("ssvc")
engine.assert_fact("ssvc_meta", ssvc.SSVC_META)

# CISA tree
engine.assert_fact("exploitation",      {"value": "active"})
engine.assert_fact("automatable",       {"value": "yes"})
engine.assert_fact("technical_impact",  {"value": "total"})
engine.assert_fact("mission_wellbeing", {"value": "high"})
result = engine.evaluate()
# result.metadata["decision"] -> "Act"
```

Inputs per tree:

- `ssvc_supplier`: `exploitation`, `utility`, `technical_impact`, `public_safety_impact`
- `ssvc_deployer`: `exploitation`, `exposure`, `automatable`, `human_impact`
- `ssvc_cisa`: `exploitation`, `automatable`, `technical_impact`, `mission_wellbeing`

Missing any of a tree's four input facts produces the engine default
decision — this pack never guesses. Asserting the union of several trees'
facts can fire more than one tree; assert one tree's facts per evaluation.

## Action slot mapping

The engine `__fathom_decision` template's `action` slot is
`allow | deny | escalate | scope | route`. SSVC labels don't fit those
symbols, so every SSVC rule emits `action=route` with the SSVC label in the
`metadata` slot. No change to the decision template is required.

## !! Version-bump rule !!

**Version bump required whenever an upstream tree changes. Silent edits are
forbidden.**

When an upstream source (CERT/CC decision table or CISA guide) changes:

1. Replace the affected file(s) under `references/` (filenames reflect the
   new version).
2. Recompute and update `references/SHA256SUMS`.
3. Update `SSVC_META["version"]` in `__init__.py` if the CISA tree version
   changed.
4. Regenerate branches + rules: `uv run python scripts/generate_ssvc_rules.py`
   (update its `TREES` table first if columns or filenames changed).
5. Bump the package version (minor bump).

All of the above must land in a **single commit** so `SSVC_META` and the
pinned hashes can never disagree. `tests/rule_packs/test_ssvc.py` enforces
that every archived reference matches its pin, that each tree retains its
full published branch count, and that the committed branch lists equal the
pinned CSVs row for row; CI fails loudly if any of them drift.

## References

- [CERT/CC SSVC repository](https://github.com/CERTCC/SSVC) (decision tables; authoritative)
- [CISA SSVC guide](https://www.cisa.gov/stakeholder-specific-vulnerability-categorization-ssvc) (CISA tree)
- SEI/CERT-CC SSVC v2.0 paper (methodology; archived in `references/`)

## Disclaimer

Reference implementation for demonstration and educational purposes only.
Organizations must perform their own vulnerability-triage process and
validate decisions against their operational context.
