---
title: hipaa
summary: Rule pack — hipaa
audience: [rule-authors, app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Rule Pack: `hipaa`

HIPAA Privacy and Security Rule rule pack.

**Pack version:** `1.0`  
**Rule count:** 3  
**Modules:** `hipaa`  
**Templates:** `data_transfer`, `phi_policy`

## Rules

| Name | Salience | Action | Reason | Source |
|---|---|---|---|---|
| `minimum-necessary` | 100 | `deny` | PHI access denied: minimum necessary justification required (164.502(b)) | `src/fathom/rule_packs/hipaa/rules/hipaa_rules.yaml` |
| `transmission-security` | 100 | `deny` | PHI transfer blocked: transmission must be encrypted (164.312(e)(1)) | `src/fathom/rule_packs/hipaa/rules/hipaa_rules.yaml` |
| `breach-trigger` | 200 | `escalate` | Bulk PHI access detected: breach notification evaluation required (164.402) | `src/fathom/rule_packs/hipaa/rules/hipaa_rules.yaml` |
