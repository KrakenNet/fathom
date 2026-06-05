---
title: fathom verify-chain
summary: CLI reference for `fathom verify-chain`
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# `fathom verify-chain`

```
                                                                                
 Usage: fathom verify-chain [OPTIONS] LOG_PATH                                  
                                                                                
 Offline-verify a hash-chained attestation log (chain + signatures).            
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    log_path      PATH  Chained attestation log (JSONL) to verify.          │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --pubkey               PATH  Ed25519 public key PEM (exported beside the  │
│                                 log as <log>.pub.pem).                       │
│                                 [required]                                   │
│    --expected-head        TEXT  Out-of-band mirrored line hash; fails if     │
│                                 absent (tail truncation).                    │
│    --anchor-token         TEXT  Checkpoint JWS token; its pinned head must   │
│                                 appear in the log.                           │
│    --json                       Emit the verification result as JSON.        │
│    --help                       Show this message and exit.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```
