"""Schema-denoising rule pack: frequency-tau promotion over an extraction stream.

An external extractor produces triples; some relation types are real and some
are one-off extraction noise. This pack is the deterministic filter between
them: a relation is promoted ``candidate_schema`` -> ``stable_schema`` once at
least tau facts carry it, and only facts under a promoted relation become
``aligned_fact``. Downstream rules match ``aligned_fact``, never
``extracted_fact``.

The mechanism is unified schema filtering as described for MemGraphRAG
(arXiv:2606.00610v1); the implementation here is Fathom's own and shares no
code or data with that system.

What the host does:

1. Assert one ``extracted_fact`` per extracted triple.
2. Call ``Engine.evaluate()`` once. Detection is forward-chaining, so nothing
   happens inside the asserts themselves.
3. Read the ``aligned_fact`` facts, or load rules that match them.

tau is the literal ``3`` in ``promote-stable-schema``. Changing it means
editing that rule, which keeps the threshold a compile-time constant: the
same facts always produce the same promotions.

Promotion is one-way within a session. Working memory only grows during an
evaluation, so a relation that clears tau stays stable until the session's
facts are reset.

The count is retaken as the stream grows, so a relation that reaches tau
across several ``evaluate()`` calls is promoted on the call that reaches it --
``promote-stable-schema`` joins the candidate to the facts supporting it
rather than matching the candidate alone, which was tested once and never
again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fathom.rule_packs._helpers import load_pack_yaml, validate_pack_structure

PACK_DIR = Path(__file__).resolve().parent

#: The support threshold the shipped `promote-stable-schema` rule encodes.
#: Read it to assert against the pack rather than hard-coding 3 in a test.
DEFAULT_TAU = 3


def get_templates() -> list[dict[str, Any]]:
    """Load all template definitions from this pack."""
    validate_pack_structure(PACK_DIR)
    data = load_pack_yaml(PACK_DIR, "templates/schema_templates.yaml")
    result: list[dict[str, Any]] = data.get("templates", [])
    return result


def get_modules() -> list[dict[str, Any]]:
    """Load all module definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "modules/schema_modules.yaml")
    result: list[dict[str, Any]] = data.get("modules", [])
    return result


def get_rules() -> list[dict[str, Any]]:
    """Load all rule definitions from this pack."""
    data = load_pack_yaml(PACK_DIR, "rules/schema_rules.yaml")
    result: list[dict[str, Any]] = data.get("rules", [])
    return result
