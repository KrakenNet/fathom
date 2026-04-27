---
title: fathom verify-artifact
summary: CLI reference for `fathom verify-artifact`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom verify-artifact`

```
                                                                                                    
 Usage: fathom verify-artifact [OPTIONS] ARTIFACT                                                   
                                                                                                    
 Verify an artifact's detached minisign signature against a pubkey.                                 
                                                                                                    
╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    artifact      PATH  Artifact to verify. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --sig           PATH  Sig path (default: <path>.minisig).                                        │
│ --pubkey        PATH  Pubkey (default: embedded).                                                │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
