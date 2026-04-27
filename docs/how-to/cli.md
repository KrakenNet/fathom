---
title: Using the CLI
summary: One-line purpose + worked example for every fathom CLI command.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-04-27
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

The command exits non-zero if any case fails.

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

## Full reference

For the complete flag matrix, exit codes, and error behaviour of each
command, see the generated reference pages:

- [CLI reference index](../reference/cli/index.md)
- [validate](../reference/cli/validate.md)
- [compile](../reference/cli/compile.md)
- [info](../reference/cli/info.md)
- [test](../reference/cli/test.md)
- [bench](../reference/cli/bench.md)
- [repl](../reference/cli/repl.md)
