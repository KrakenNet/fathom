---
title: fathom status
summary: CLI reference for `fathom status`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom status`

```
                                                                                
 Usage: fathom status [OPTIONS]                                                 
                                                                                
 Query a Fathom server's GET /v1/status endpoint.                               
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --server        TEXT  Fathom server base URL (e.g.,                       │
│                          http://127.0.0.1:8080).                             │
│                          [required]                                          │
│    --token         TEXT  Optional bearer token (defaults to FATHOM_TOKEN env │
│                          var).                                               │
│                          [env var: FATHOM_TOKEN]                             │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```
