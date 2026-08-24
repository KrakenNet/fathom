---
title: fathom convert rego
summary: CLI reference for `fathom convert rego`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom convert rego`

```
                                                                                
 Usage: fathom convert rego [OPTIONS] POLICY                                    
                                                                                
 Convert a Rego policy into Fathom YAML.                                        
                                                                                
 Translates the stateless subset -- `allow`/`deny` rules whose bodies           
 compare `input` fields against literals. Anything outside it is reported       
 and left out rather than approximated, so what is written is faithful and      
 what is missing is listed. Requires the `opa` binary, which does the           
 parsing.                                                                       
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    policy      FILE  Path to a .rego policy file. [required]               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --out       -o      PATH  Directory to write templates/, modules/ and rules/ │
│                           into. Without it, the YAML is printed.             │
│ --template  -t      TEXT  Name for the synthesised template holding Rego's   │
│                           `input` document.                                  │
│                           [default: input]                                   │
│ --strict                  Exit nonzero if any construct was skipped, not     │
│                           only if none converted.                            │
│ --help                    Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```
