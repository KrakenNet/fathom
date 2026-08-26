"""Conflict-detection rule pack: contradictions in the fact layer, as facts.

Three kinds of disagreement between claims about the same subject, each
detected by a forward-chaining rule and reported as a ``conflict`` fact:

- **mutual exclusion** -- two claims name tails a ``mutual_exclusion``
  declaration says cannot both hold of one head.
- **temporal** -- two different tails for one ``(head, relation)`` observed
  within ``DEFAULT_WINDOW_SECONDS`` *of each other*. Far apart in time the
  same pair is a legitimate change, so closeness is the whole test. A claim
  left at the default ``observed_at`` of 0 never pairs: absence of a
  timestamp is not evidence of closeness.
- **granularity** -- two claims that disagree only about how coarse they are,
  related by a ``subsumes`` declaration.

Detection only. No rule here renders a decision, because what to do about a
contradiction is a policy question this pack does not have the answer to.
Resolution is tracked separately (see #73).

What the host does:

1. Assert the declarations (``mutual_exclusion``, ``subsumes``) it wants
   enforced, and one ``claim`` per assertion about the world.
2. Call ``Engine.evaluate()``.
3. Read the ``conflict`` facts.

Detection must not live in a ``subscribe`` callback. ``FactManager.add_listener``
fires listeners synchronously inside ``assert_fact``, which only validates and
asserts -- it does not run inference -- so asserting a conflict from a listener
re-enters the fact manager mid-assert. These are rules; the host runs them.

**Granularity is declared with ``subsumes`` facts, not a**
``HierarchyDefinition``. A hierarchy orders *level names*, so using one would
mean every claim carrying an extra level slot and each deployment shipping its
own lattice. It would also be loud: the first hierarchy loaded into an engine
claims the unscoped ``below`` / ``meets-or-exceeds`` / ``within-scope``
deffunctions for every rule in it, so a pack that ships one silently changes
what those operators mean for the host's own rules. A ``subsumes`` fact reads
the same way as a ``mutual_exclusion`` fact and costs the host nothing it was
not already declaring.

What a purely symbolic detector cannot see: near-duplicates and paraphrase.
``lives_in berlin`` against ``lives_in Berlin, Germany`` is one conflict to a
reader and two unrelated claims here. Catching those needs embeddings, which
Fathom does not have and is not trying to grow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent

#: The window `detect-temporal-conflict` encodes, in seconds. Two claims
#: further apart than this are a change, not a contradiction. Read it rather
#: than hard-coding 3600 in a test.
#:
#: Measured between the two claims, not between each claim and now. The rule
#: tested `changed_within(3600)` on both patterns, which measured recency: a
#: pair a minute apart stopped being a conflict once it was a day old, a pair
#: fifty minutes apart was missed whenever it straddled the boundary, and the
#: same working memory answered differently depending on when it was asked.
DEFAULT_WINDOW_SECONDS = 3600


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/conflict_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/conflict_modules.yaml")
    result: list[dict[str, Any]] = data.get("modules", [])
    return result


def get_rules() -> list[dict[str, Any]]:
    """Load all rule definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "rules/conflict_rules.yaml")
    result: list[dict[str, Any]] = data.get("rules", [])
    return result
