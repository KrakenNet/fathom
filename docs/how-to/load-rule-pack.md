---
title: Loading a rule pack
summary: Load rules from a directory or a distributed Python package via Engine.from_rules and Engine.load_pack.
audience: [app-developers, rule-authors]
diataxis: how-to
status: stable
last_verified: 2026-04-27
sources:
  - src/fathom/engine.py
  - src/fathom/packs.py
  - pyproject.toml
---

# Loading a rule pack

Fathom supports two ways to ship rules into an `Engine`: as a directory tree
you maintain alongside your application, or as an installable Python package
discovered at runtime through a setuptools entry point. Both routes funnel
through the same loaders, so the YAML you author looks identical either way —
only the delivery mechanism differs.

## Load from a directory

`Engine.from_rules(path, **kwargs)` is a classmethod that returns a configured
`Engine`. Any keyword arguments are forwarded to the `Engine(...)` constructor.

```python
from fathom.engine import Engine

engine = Engine.from_rules("examples/01-hello-allow-deny")
result = engine.evaluate()
```

The loader tries two discovery strategies, in order:

1. **Subdirectory convention** (preferred). If the pack directory contains any
   of `templates/`, `modules/`, `functions/`, or `rules/`, each present
   subdirectory is passed to the matching `engine.load_templates`,
   `load_modules`, `load_functions`, or `load_rules` method.
2. **Key-inspection fallback**. If none of those subdirectories exist, every
   `*.yaml` file directly under `path` is opened and routed by its top-level
   key: `templates` → templates loader, `modules` or `focus_order` → modules
   loader, `functions` → functions loader, `rules` or `ruleset` → rules
   loader.

Both strategies load in the same fixed order: **templates → modules →
functions → rules**. The order matters because templates define the slot
schemas that rules bind against, modules establish the namespaces that rules
live in, and functions may be referenced from a rule's left-hand side via the
raw-CLIPS `test:` clause — so everything a rule depends on must be compiled
before the rule itself.

## Directory layout

For anything larger than a toy example, use the subdirectory convention. The
reference shape is what `examples/01-hello-allow-deny` ships with:

```
my-pack/
├── templates/
│   └── *.yaml
├── modules/
│   └── *.yaml
├── functions/
│   └── *.yaml
└── rules/
    └── *.yaml
```

Every YAML file under a given subdirectory is loaded. The glob is `*.yaml`
only — files ending in `.yml` are **not** picked up by `from_rules`, so stick
to the long extension. Empty or missing subdirectories are fine; the loader
simply skips them.

The key-inspection fallback is handy for tiny single-file packs where
splitting into subdirectories would be overkill, but it's strictly less
expressive: it only scans the top level of `path` (no recursion) and each
file must declare exactly one top-level key that the loader recognises.

## Load a distributed pack via entry point

Once a pack is packaged as a Python distribution, load it by name:

```python
from fathom.engine import Engine

engine = Engine()
engine.load_pack("owasp-agentic")
```

`Engine.load_pack` delegates to `RulePackLoader`, which walks the
`fathom.packs` entry-point group, imports the registered module, resolves its
on-disk location via `module.__path__`, and then runs the same
`templates/` → `modules/` → `functions/` → `rules/` subdirectory load as
`from_rules` does.

To expose your own pack, add an entry to your `pyproject.toml`:

```toml
[project.entry-points."fathom.packs"]
my-pack = "my_package.rules"
```

Here `my_package/rules/` is an importable package directory that contains the
familiar `templates/`, `modules/`, `functions/`, and `rules/` subdirectories
full of YAML. After `pip install`, any process with Fathom installed can call
`engine.load_pack("my-pack")`.

### Packs shipped with Fathom

Fathom currently ships four first-party rule packs, registered under the same
entry-point group in its own `pyproject.toml`:

- `owasp-agentic`
- `nist-800-53`
- `hipaa`
- `cmmc`

### Error handling

If you pass a name that isn't registered under `fathom.packs`,
`RulePackLoader.discover` raises `CompilationError` with
`construct="pack:<name>"`. The same error is raised if the registered module
has no resolvable path (neither `__path__` nor `__file__`), which in practice
only happens for exotic namespace-package setups.

## When to use which

- **`Engine.from_rules(path)`** — your application owns the rules, they live
  in a directory inside the repo (or a mounted volume), and you want the
  fastest edit-reload loop. Best for development, single-tenant deployments,
  and environment-specific overrides.
- **`engine.load_pack(name)`** — the rules are a redistributable asset
  consumed by multiple applications, need independent versioning, and can be
  published alongside your Python wheels. Enables `pip install
  compliance-pack` style workflows and clean upgrades.

Nothing stops you from mixing both in one `Engine`: call `load_pack` for a
shared baseline, then `load_rules` or `load_templates` on a local directory
for application-specific overlays.

## Related reading

- [Python SDK reference](../reference/python-sdk/index.md) — full `Engine`
  API, including every `load_*` method used here.
- [Writing rules](writing-rules.md) — YAML authoring conventions for the
  files inside a pack.
- [YAML schema reference](../reference/yaml/index.md) — the top-level keys
  (`templates`, `modules`, `functions`, `rules`) that the key-inspection
  fallback looks for.
