---
title: fathom compile
summary: CLI reference for `fathom compile`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom compile`

```
                                                                                
 Usage: fathom compile [OPTIONS] PATH                                           
                                                                                
 Compile YAML definitions into CLIPS constructs.                                
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    path      PATH  Path to a YAML file or directory to compile. [required] │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      [raw|pretty]  Output format: raw (valid CLIPS) or pretty   │
│                                 (human-readable).                            │
│                                 [default: raw]                               │
│ --help                          Show this message and exit.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```
