---
title: fathom bench
summary: CLI reference for `fathom bench`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom bench`

```
                                                                                
 Usage: fathom bench [OPTIONS] RULES_PATH                                       
                                                                                
 Benchmark rule evaluation latency.                                             
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    rules_path      PATH  Path to a rule pack directory. [required]         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --iterations  -n      INTEGER  Number of evaluation iterations.              │
│                                [default: 1000]                               │
│ --warmup      -w      INTEGER  Number of warmup iterations (excluded from    │
│                                results).                                     │
│                                [default: 100]                                │
│ --help                         Show this message and exit.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```
