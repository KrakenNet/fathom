---
title: fathom convert to-rego
summary: CLI reference for `fathom convert to-rego`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom convert to-rego`

```
                                                                                
 Usage: fathom convert to-rego [OPTIONS] RULESET                                
                                                                                
 Export the stateless subset of a Fathom ruleset as Rego.                       
                                                                                
 Only rules that match one fact against literals have a Rego form. Rules        
 that join across facts, assert new facts, or use a temporal or                 
 classification operator are reported and left out -- those are the parts       
 of Fathom that Rego has no counterpart for, and writing them out as            
 something Rego accepts would mean writing a different policy.                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    ruleset      DIRECTORY  Path to a Fathom ruleset directory. [required]  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out      -o      PATH  File to write the Rego to. Without it, the policy   │
│                          is printed.                                         │
│ --package  -p      TEXT  Rego package name. Defaults to the module the rules │
│                          declare.                                            │
│ --strict                 Exit nonzero if any rule was skipped, not only if   │
│                          none exported.                                      │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```
