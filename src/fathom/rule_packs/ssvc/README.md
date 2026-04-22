# SSVC v2.0.3 rule pack

Reference implementation of CISA's **Stakeholder-Specific Vulnerability
Categorization (SSVC)** decision tree, version **2.0.3**, for coordinator-level
vulnerability triage.

- **Version:** 2.0.3
- **Source:** CISA PDF (published Nov 2021)
- **PDF:** `references/cisa-ssvc-v2.0.3.pdf`
- **Pinned hash:** `references/SHA256SUMS` (sha256 of the PDF)
- **Branches source:** `references/branches.yaml` (enumerated from the PDF)

A decision combines four input facts — `exploitation`, `exposure`, `utility`,
`human_impact` — into one of the published decision labels: `Act`, `Attend`,
`Track*`, or `Track`. Each published branch in the CISA tree is exactly one
rule in this pack (no cartesian expansion — naive tuples that are not in the
published tree fall through to the engine's default decision).

## Required input contract

Seed the engine with SSVC inputs plus the pack metadata fact, then evaluate:

```python
from fathom import Engine
from fathom.rule_packs import ssvc

engine = Engine()
engine.load_pack("ssvc")
engine.assert_fact("ssvc_meta", ssvc.SSVC_META)
engine.assert_fact("exploitation", {"value": "active"})
engine.assert_fact("exposure",     {"value": "open"})
engine.assert_fact("utility",      {"value": "super_effective"})
engine.assert_fact("human_impact", {"value": "very_high"})
result = engine.evaluate()
# result.decision.metadata -> "Act"
```

Missing any of the four input facts produces the engine default decision —
this pack never guesses.

## Action slot mapping

The existing engine `__fathom_decision` template's `action` slot is
`allow | deny | escalate | scope | route`. SSVC labels (`Act`, `Attend`,
`Track*`, `Track`) don't fit those symbols, so every SSVC rule emits
`action=route` with the SSVC label in the `metadata` slot. No change to
the decision template is required.

## !! Version-bump rule !!

**Version bump required whenever CISA updates SSVC. Silent edits are forbidden.**

When the CISA PDF changes:

1. Replace `references/cisa-ssvc-v2.0.3.pdf` with the new PDF (filename reflects the new version).
2. Recompute and update `references/SHA256SUMS`.
3. Update `SSVC_META["version"]` in `__init__.py` to match the new CISA version.
4. Re-enumerate published branches in `references/branches.yaml` and regenerate `rules/ssvc_rules.yaml`.
5. Bump the package version (minor bump).

All of the above must land in a **single commit** so `SSVC_META.version`
and the pinned sha256 can never disagree. The branch-coverage test in
`tests/rule_packs/test_ssvc_cisa.py` enforces that the sha256 in
`SHA256SUMS` matches `sha256(cisa-ssvc-v2.0.3.pdf)` at test time; CI will
fail loudly if the two drift.

## References

- Primary: CISA SSVC v2.0.3 PDF (archived in `references/`)
- Secondary (non-authoritative on conflict): [CERT/CC SSVC repo](https://github.com/CERTCC/SSVC)

## Disclaimer

Reference implementation for demonstration and educational purposes only.
Organizations must perform their own vulnerability-triage process and
validate decisions against their operational context.
