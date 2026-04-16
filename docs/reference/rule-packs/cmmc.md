---
title: cmmc
summary: Rule pack — cmmc
audience: [rule-authors, app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Rule Pack: `cmmc`

CMMC Level 2 Cybersecurity Maturity Model Certification rule pack.

**Pack version:** `1.0`  
**Rule count:** 6  
**Modules:** `cmmc`  
**Templates:** `cui_policy`

## Rules

| Name | Salience | Action | Reason | Source |
|---|---|---|---|---|
| `ac-l2-authorized-access` | 100 | `deny` | CUI access denied: authorized access justification required (AC.L2-3.1.1) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
| `ac-l2-cui-flow` | 100 | `deny` | CUI transfer blocked: controlled information cannot flow to external destination (AC.L2-3.1.3) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
| `ac-l2-least-privilege` | 100 | `deny` | Privileged CUI action requires explicit justification (AC.L2-3.1.5) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
| `au-l2-audit-records` | 100 | `escalate` | Audit record incomplete: outcome must be recorded for CUI events (AU.L2-3.3.1) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
| `au-l2-traceability` | 100 | `deny` | Audit traceability failed: subject identity required for all CUI actions (AU.L2-3.3.2) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
| `ir-l2-incident-handling` | 200 | `escalate` | Bulk CUI access detected: incident handling evaluation required (IR.L2-3.6.1) | `src/fathom/rule_packs/cmmc/rules/cmmc_rules.yaml` |
