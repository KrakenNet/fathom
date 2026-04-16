---
title: owasp-agentic
summary: Rule pack — owasp-agentic
audience: [rule-authors, app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# Rule Pack: `owasp-agentic`

OWASP LLM Top 10 agentic safety rule pack.

**Pack version:** `1.0`  
**Rule count:** 4  
**Modules:** `owasp`  
**Templates:** `agent_input`, `agent_output`, `tool_call`

## Rules

| Name | Salience | Action | Reason | Source |
|---|---|---|---|---|
| `detect-prompt-injection` | 100 | `escalate` | Possible prompt injection detected in agent input | `src/fathom/rule_packs/owasp_agentic/rules/owasp_rules.yaml` |
| `deny-excessive-agency-exec` | 100 | `deny` | Tool call is in the dangerous tools list (LLM04: Excessive Agency) | `src/fathom/rule_packs/owasp_agentic/rules/owasp_rules.yaml` |
| `flag-insecure-output-ssn` | 90 | `escalate` | Agent output may contain SSN pattern (LLM06: Insecure Output) | `src/fathom/rule_packs/owasp_agentic/rules/owasp_rules.yaml` |
| `flag-insecure-output-email` | 80 | `escalate` | Agent output may contain email address (LLM06: Insecure Output) | `src/fathom/rule_packs/owasp_agentic/rules/owasp_rules.yaml` |
