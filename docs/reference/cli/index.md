---
title: CLI Reference
summary: Index of `fathom` CLI commands
audience: [app-developers, rule-authors]
diataxis: reference
status: stable
last_verified: 2026-04-15
---

# CLI Reference

| Command | |
|---|---|
| [`fathom bench`](bench.md) | |
| [`fathom compile`](compile.md) | |
| [`fathom convert rego`](convert-rego.md) | |
| [`fathom convert to-rego`](convert-to-rego.md) | |
| [`fathom info`](info.md) | |
| [`fathom mcp`](mcp.md) | |
| [`fathom repl`](repl.md) | |
| [`fathom status`](status.md) | |
| [`fathom test`](test.md) | |
| [`fathom validate`](validate.md) | |
| [`fathom verify-artifact`](verify-artifact.md) | |
| [`fathom verify-chain`](verify-chain.md) | |

## Exit codes

Every command uses the same four codes.

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | The command ran and the check failed: validation or compile errors, failing tests, an invalid signature or chain, nothing convertible, `--strict` with skipped items, or an unexpected internal error. |
| `2` | An input could not be found or read (including a rule pack directory with no YAML files in it), or an output could not be written. Typer also exits `2` on a usage error (unknown option, missing argument, a path argument that does not exist), so `2` alone does not tell the two apart; the stderr message does. |
| `3` | An input was read but is malformed or cannot be converted, or a dependency the command needs is not installed (see below). |

Every command that loads a rule pack (`info`, `test`, `bench`, `repl`, `mcp`, `convert to-rego`) exits `1` when the pack does not compile, the same as `validate` and `compile`.

Any command exits `3` with a one-line install hint when the `fathom` script was installed without the `cli` extra, and `fathom mcp` does the same without the `mcp` extra. Commands that can also exit `3`:

- `fathom verify-artifact` — the signature or public key is malformed (bad base64, wrong length, unsupported algorithm, key id mismatch).
- `fathom verify-chain` — the public key is a valid PEM but not an Ed25519 key.
- `fathom convert rego` — the Rego cannot be parsed, including when the `opa` binary that parses it is not installed.
- `fathom convert rego` and `fathom convert to-rego` — a `deny` rule has no faithful translation, so the whole conversion is refused and nothing is written.
