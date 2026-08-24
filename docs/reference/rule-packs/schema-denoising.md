---
title: schema-denoising
summary: Rule pack — schema-denoising
audience: [rule-authors, app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Rule Pack: `schema-denoising`

Schema-denoising rule pack: frequency-tau promotion over an extraction stream.

**Pack version:** `1.0`  
**Rule count:** 3  
**Modules:** `schema_denoising`  
**Templates:** `aligned_fact`, `candidate_schema`, `extracted_fact`, `stable_schema`

## Rules

| Name | Salience | Action | Reason | Source |
|---|---|---|---|---|
| `observe-candidate-schema` | 100 | `` |  | `src/fathom/rule_packs/schema_denoising/rules/schema_rules.yaml` |
| `promote-stable-schema` | 90 | `` |  | `src/fathom/rule_packs/schema_denoising/rules/schema_rules.yaml` |
| `align-fact-to-stable-schema` | 80 | `` |  | `src/fathom/rule_packs/schema_denoising/rules/schema_rules.yaml` |
