---
title: conflict-detection
summary: Rule pack — conflict-detection
audience: [rule-authors, app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Rule Pack: `conflict-detection`

Conflict-detection rule pack: contradictions in the fact layer, as facts.

**Pack version:** `1.0`  
**Rule count:** 3  
**Modules:** `conflict_detection`  
**Templates:** `claim`, `conflict`, `mutual_exclusion`, `subsumes`

## Rules

| Name | Salience | Action | Reason | Source |
|---|---|---|---|---|
| `detect-mutual-exclusion` | 100 | `` |  | `src/fathom/rule_packs/conflict_detection/rules/conflict_rules.yaml` |
| `detect-temporal-conflict` | 90 | `` |  | `src/fathom/rule_packs/conflict_detection/rules/conflict_rules.yaml` |
| `detect-granularity-conflict` | 80 | `` |  | `src/fathom/rule_packs/conflict_detection/rules/conflict_rules.yaml` |
