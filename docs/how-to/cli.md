---
title: Using the CLI
summary: One-line purpose + worked example for every fathom CLI command.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-08-27
sources:
  - src/fathom/cli.py
---

# Using the CLI

Install the CLI extra with `pip install fathom-rules[cli]`. The entry
point is the `fathom` command, built on Typer. To confirm installation,
print the runtime version with the global flag:

```shell
fathom --version
```

The short form `-V` works identically. The sections below cover every
sub-command, in the order they appear in `src/fathom/cli.py`, with a
worked example against one of the example rule packs shipped under
`examples/`.

## validate

Parse every YAML file under the given path and check that each document
is a well-formed Fathom template, module, rule, or function definition.

```shell
fathom validate examples/01-hello-allow-deny
```

Pass either a single file or a directory; the command walks directories
recursively and reports all parse and schema errors at once. It exits 0
on success, 1 on validation errors, and 2 when no YAML files are found.

## compile

Lower YAML definitions to the CLIPS constructs the engine actually
executes. Useful for debugging code generation or feeding constructs
into a raw CLIPS environment.

```shell
fathom compile examples/02-rbac-modules
```

The `--format` / `-f` option selects the output style: `raw` (the
default, a single flat string of valid CLIPS) or `pretty`, which inserts
newlines at the top-level paren boundaries so each construct sits on
its own line.

```shell
fathom compile examples/02-rbac-modules --format pretty
```

Literals are emitted according to the declared slot type, so `compile` needs
the templates in view: pointed at a directory it reads them from the pack, and
pointed at a single file under `rules/` it picks up the sibling `templates/`
directory. Without that context a `string` slot's literal is emitted bare —
CLIPS rejects that form with `[CSTRNCHK1]`, so the printed constructs would be
ones the engine never builds and that do not load.

The output is ordered to load, not to mirror the directory walk. It opens with
the same preamble the engine builds — the `?*fathom-decision-seq*` global and
the `__fathom_decision` deftemplate every rule's RHS asserts into, plus
`(defmodule MAIN (export ?ALL))` when the pack declares modules — and then
follows with deftemplates, defmodules, deffunctions and defrules in that
order, because CLIPS resolves a reference when the construct naming it is
built.

One thing the text cannot carry: the `fathom-*` operators (`fathom-matches`,
`fathom-count-exceeds`, and the rest) are Python callbacks the engine
registers on the environment before it compiles any rule. A bare `clips`
process has no such functions, so loading the output there fails on the first
rule that uses an operator. Feed it to an environment prepared the way the
engine prepares one.

A pack that depends on another (`cmmc` on `nist-800-53`, say) compiles to
constructs that reference templates and modules the other pack owns; compile
both together, as `Engine.from_rules` loads them. Pointed at a directory the
command checks this for you — it builds what it is about to print into a
prepared environment and exits 1, with the CLIPS diagnostics, rather than
printing constructs that raise on line 1. A single YAML file is exempt: a
rules file names the module and templates its siblings define, which the
command reads for slot types and does not emit, so its output is a fragment
by construction.

The declared focus order is printed as a trailing comment. `(focus …)` is a
command the evaluator issues per evaluation, not a construct, and a loader
rejects it.

## info

Load a rule pack and print a summary of everything the engine sees:
templates (with slot names and types), modules (with priority and the
configured focus order), rules (with salience), and registered
functions.

```shell
fathom info examples/03-classification-blp
```

Use `info` as a sanity check after editing a pack — if a template or
rule is missing from the listing, it did not compile into the engine.

The function listing covers the `fathom-*` operators the engine registers plus
any `deffunction` the pack declares. It is read from the `MAIN` module: CLIPS
enumerates deffunctions in whichever module is current, and building a pack's
last `defmodule` leaves that one current, which is why this section used to report
`Functions (0)` for every pack.

## test

Run a YAML suite of test cases against a compiled rule pack. The
command takes two arguments: the rule pack directory and a test file
(or directory of test files).

```shell
fathom test examples/01-hello-allow-deny tests/cases.yaml
```

Each test file is a YAML list of cases. Every case recognises three
keys:

- `name` — a human-readable label printed in PASS/FAIL lines.
- `facts` — a list of fact specs, each with a `template` and a `data`
  mapping that the CLI asserts into a freshly reset engine.
- `expected_decision` — the decision string the evaluation must return
  for the case to pass.

```yaml
- name: admin can read
  facts:
    - template: subject
      data: { role: admin }
    - template: resource
      data: { kind: report }
  expected_decision: allow
```

The command exits non-zero if any case fails. It also exits non-zero,
rather than silently reporting success, when the suite could not be run at
all: when the test path contains no test cases (an empty directory, or files
that parse to nothing), and when a test file cannot be read or is not a list
of test cases. A suite that quietly matches zero cases used to exit 0, which
made a mis-typed path look like a passing run.

## bench

Measure evaluation latency for a rule pack. The benchmark resets the
engine between each iteration and reports p50, p95, p99, and mean
timings in microseconds.

```shell
fathom bench examples/04-temporal-anomaly
```

Two options tune the run:

- `--iterations` / `-n` — number of measured iterations (default
  `1000`).
- `--warmup` / `-w` — number of warmup iterations that run first and
  are excluded from the statistics (default `100`).

```shell
fathom bench examples/04-temporal-anomaly -n 5000 -w 500
```

## verify-chain

Offline-verify a hash-chained attestation log: every line's JWS
signature, the hash link to its predecessor, and the genesis record's
key fingerprint.

```shell
fathom verify-chain audit/chain.jsonl --pubkey audit/chain.jsonl.pub.pem
```

The `--pubkey` option is required and takes the Ed25519 public key PEM
that the log exports beside itself as `<log>.pub.pem`.

**The sidecar is a convenience, not a trust anchor.** It sits in the same
trust domain as the log: whoever can rewrite `audit/chain.jsonl` can replace
`audit/chain.jsonl.pub.pem` with a key of their own and re-sign a wholly
forged chain that verifies clean. Passing it makes the command say so.
The value to keep out-of-band is the `key_fingerprint` the run prints (and
reports in `--json`) — record it when the key is created, and verify against
a copy of the public key held somewhere the log's writer cannot reach.

Two optional checks detect truncation, which a self-contained log cannot
reveal:

- `--expected-head` — a line hash mirrored out-of-band; verification
  fails if it no longer appears in the log.
- `--anchor-token` — a checkpoint JWS token; the head it pins must
  appear in the log.

Pass `--json` to emit the verification result as JSON. The command
exits 0 when the chain is valid, 1 when verification fails, and 2 when
the log or key file cannot be read — a file that is not a parseable PEM
counts as a key that cannot be read, and reports that rather than raising.

## repl

Start an interactive session for asserting facts and evaluating rules
by hand. Pass `--rules` / `-r` to preload a pack; without it, the REPL
starts with an empty engine.

```shell
fathom repl --rules examples/05-langchain-guardrails
```

Inside the REPL, these sub-commands are available:

- `assert <template> <json_data>` — assert a fact (the data argument
  is parsed as JSON).
- `evaluate` — run an evaluation and print decision, reason, and rule
  trace.
- `query <template>` — list facts whose template matches.
- `retract <template>` — retract all facts matching the template.
- `facts` — list every fact currently in working memory.
- `reset` — reset engine state.
- `help` — print the command list.
- `quit` / `exit` — leave the REPL.

Example session:

```text
fathom> assert subject {"role": "admin"}
Asserted subject fact.
fathom> evaluate
  decision: allow
  reason: admin override
fathom> quit
```

## convert rego

Translate the stateless subset of an OPA Rego policy into a Fathom pack.
Requires the `opa` binary, which does the parsing.

```shell
fathom convert rego authz.rego --out ./converted
```

Anything outside the convertible subset is reported on stderr with the
rule and the reason rather than approximated. The command exits non-zero
when nothing converted; `--strict` also fails when anything was skipped.
See [Converting a Rego policy](convert-rego.md) for the full mapping and
the list of refusals.

## convert to-rego

Export the stateless subset of a Fathom ruleset as Rego.

```shell
fathom convert to-rego ./my-ruleset -o policy.rego
```

Rules that join across facts, assert facts, or use a temporal or
classification operator have no Rego form and are reported on stderr
rather than written out. See [Exporting rules as Rego](export-rego.md).

## Full reference

For the complete flag matrix, exit codes, and error behaviour of each
command, see the generated reference pages:

- [CLI reference index](../reference/cli/index.md)
- [validate](../reference/cli/validate.md)
- [compile](../reference/cli/compile.md)
- [info](../reference/cli/info.md)
- [test](../reference/cli/test.md)
- [bench](../reference/cli/bench.md)
- [verify-chain](../reference/cli/verify-chain.md)
- [convert rego](../reference/cli/convert-rego.md)
- [convert to-rego](../reference/cli/convert-to-rego.md)
- [repl](../reference/cli/repl.md)
