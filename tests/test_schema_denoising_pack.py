"""The frequency-tau denoising contract, end to end and at the compiler.

Two things are under test and they fail differently:

- The **operator**. ``schema_frequency_exceeds`` is ``count >= tau`` -- the
  same predicate ``last_n`` already computes -- so the interesting part is
  not the arithmetic but the ``$alias.field`` value argument, which is what
  lets one promotion rule serve an open set of relations instead of one rule
  per relation. A cross-reference to any other slot compiles to a CLIPS
  variable nothing binds, so it has to be refused at the Fathom layer.
- The **pack**. A relation below tau must leave no trace downstream. The
  filter failing open looks exactly like the filter working, except that the
  noise is still there, so the tests assert on absence as well as presence.
"""

from __future__ import annotations

import pytest

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.models import RuleDefinition
from fathom.rule_packs.schema_denoising import DEFAULT_TAU

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _denoise(triples: list[tuple[str, str, str]]) -> list[dict[str, object]]:
    """Run the pack over *triples* and return the aligned_fact facts."""
    engine = Engine()
    engine.load_pack("schema-denoising")
    for head, relation, tail in triples:
        engine.assert_fact("extracted_fact", {"head": head, "relation": relation, "tail": tail})
    engine.evaluate()
    return [dict(fact) for fact in engine._env.facts() if fact.template.name == "aligned_fact"]


def _facts_named(engine: Engine, template: str) -> list[dict[str, object]]:
    return [dict(f) for f in engine._env.facts() if f.template.name == template]


def _rule(expression: str, *, slot: str = "relation", alias: str | None = "$c") -> str:
    """Compile a one-pattern rule carrying *expression* and return the CLIPS."""
    defn = RuleDefinition.model_validate(
        {
            "name": "r",
            "when": [
                {
                    "template": "candidate_schema",
                    "alias": alias,
                    "conditions": [{"slot": slot, "expression": expression}],
                }
            ],
            "then": {"action": "allow", "reason": "ok"},
        }
    )
    return Compiler().compile_rule(defn, "gov")


# ---------------------------------------------------------------------------
# The operator
# ---------------------------------------------------------------------------


class TestSchemaFrequencyOperator:
    """``schema_frequency_exceeds`` compiles, and says what it is."""

    def test_literal_value_compiles_to_a_quoted_string(self) -> None:
        clips = _rule("schema_frequency_exceeds(extracted_fact, relation, works_at, 3)")
        assert (
            '(fathom-schema-frequency-exceeds "extracted_fact" "relation" "works_at" 3)' in clips
        )

    def test_it_keeps_its_own_clips_name(self) -> None:
        """Same predicate as last_n, but the compiled rule reads back as written.

        Sharing ``fathom-last-n`` would work and would make every audit trail
        name an operator the author never typed.
        """
        clips = _rule("schema_frequency_exceeds(extracted_fact, relation, works_at, 3)")
        assert "fathom-last-n" not in clips

    def test_last_n_is_unchanged(self) -> None:
        clips = _rule("last_n(extracted_fact, relation, works_at, 3)")
        assert '(fathom-last-n "extracted_fact" "relation" "works_at" 3)' in clips
        assert "fathom-schema-frequency-exceeds" not in clips

    def test_self_reference_emits_the_bound_variable(self) -> None:
        """``$c.relation`` on slot ``relation`` of ``$c`` is the slot's own var."""
        clips = _rule("schema_frequency_exceeds(extracted_fact, relation, $c.relation, 3)")
        assert (
            '(fathom-schema-frequency-exceeds "extracted_fact" "relation" ?c-relation 3)' in clips
        )
        assert "(relation ?c-relation)" in clips

    def test_reference_to_another_slot_is_refused(self) -> None:
        """That variable is not bound, and CLIPS would say so three steps later."""
        with pytest.raises(CompilationError, match="can only reference the slot"):
            _rule("schema_frequency_exceeds(extracted_fact, relation, $c.other, 3)")

    def test_reference_to_another_alias_is_refused(self) -> None:
        with pytest.raises(CompilationError, match=r"expected '\$c\.relation'"):
            _rule("schema_frequency_exceeds(extracted_fact, relation, $s.relation, 3)")

    def test_unaliased_pattern_is_named_by_position_in_the_error(self) -> None:
        with pytest.raises(CompilationError, match=r"pattern \$p0"):
            _rule(
                "schema_frequency_exceeds(extracted_fact, relation, $c.relation, 3)",
                alias=None,
            )

    def test_arity_is_enforced(self) -> None:
        with pytest.raises(CompilationError, match="requires at least 4"):
            _rule("schema_frequency_exceeds(extracted_fact, relation)")

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            (
                "count_exceeds(extracted_fact, relation, $c.relation, 2)",
                '(fathom-count-exceeds "extracted_fact" "relation" ?c-relation 2)',
            ),
            (
                "last_n(extracted_fact, relation, $c.relation, 2)",
                '(fathom-last-n "extracted_fact" "relation" ?c-relation 2)',
            ),
            (
                "rate_exceeds(extracted_fact, relation, $c.relation, 2, 60)",
                '(fathom-rate-exceeds "extracted_fact" "relation" ?c-relation 2 60 "ts")',
            ),
        ],
    )
    def test_every_counting_operator_takes_the_reference(
        self, expression: str, expected: str
    ) -> None:
        """The value argument behaves the same across the counting family."""
        assert expected in _rule(expression)

    def test_a_literal_dollar_is_still_a_literal(self) -> None:
        """No ``.`` means no reference, so a lone ``$`` stays text."""
        clips = _rule("schema_frequency_exceeds(extracted_fact, relation, $raw, 3)")
        assert '"$raw"' in clips


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------


class TestSchemaDenoisingPack:
    """Promotion at tau, and silence below it."""

    def test_pack_loads_through_the_public_api(self) -> None:
        engine = Engine()
        engine.load_pack("schema-denoising")
        assert set(engine.template_registry) == {
            "extracted_fact",
            "candidate_schema",
            "stable_schema",
            "aligned_fact",
        }

    def test_relation_at_tau_is_promoted(self) -> None:
        engine = Engine()
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "works_at", "tail": "acme"}
            )
        engine.evaluate()
        assert _facts_named(engine, "stable_schema") == [{"relation": "works_at"}]

    def test_relation_below_tau_stays_a_candidate(self) -> None:
        engine = Engine()
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU - 1):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "rumored_at", "tail": "acme"}
            )
        engine.evaluate()
        assert _facts_named(engine, "candidate_schema") == [{"relation": "rumored_at"}]
        assert _facts_named(engine, "stable_schema") == []

    def test_only_stable_relations_produce_aligned_facts(self) -> None:
        aligned = _denoise(
            [
                ("alice", "works_at", "acme"),
                ("bob", "works_at", "acme"),
                ("carol", "works_at", "globex"),
                ("dave", "rumored_at", "acme"),
                ("erin", "rumored_at", "globex"),
            ]
        )
        assert {f["relation"] for f in aligned} == {"works_at"}
        assert {str(f["head"]) for f in aligned} == {"alice", "bob", "carol"}

    def test_noise_leaves_nothing_downstream(self) -> None:
        """The whole point: a below-tau relation must be invisible after the pass."""
        aligned = _denoise([("dave", "rumored_at", "acme"), ("erin", "rumored_at", "globex")])
        assert aligned == []

    def test_relations_are_counted_independently(self) -> None:
        """One rule, many relations -- the reason the value argument is a variable."""
        triples = [(f"h{i}", "works_at", "acme") for i in range(DEFAULT_TAU)]
        triples += [(f"g{i}", "lives_in", "berlin") for i in range(DEFAULT_TAU)]
        triples += [("noise", "rumored_at", "acme")]
        aligned = _denoise(triples)
        assert {f["relation"] for f in aligned} == {"works_at", "lives_in"}

    def test_the_pack_is_pure_inference(self) -> None:
        """No rule in the pack renders a decision; the host reads the facts."""
        engine = Engine()
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "works_at", "tail": "acme"}
            )
        result = engine.evaluate()
        # "deny" is the engine's fail-closed default, not the pack's call.
        assert result.decision == "deny"
        assert result.reason == "default decision (no rule rendered a decision)"
        # Pure inference still traces: the promotion is the whole point of the
        # pack, and a host that acts on the promoted schema has to be able to
        # show which rule produced it.
        assert any(r.endswith("promote-stable-schema") for r in result.rule_trace)

    def test_tau_reached_across_two_evaluations_still_promotes(self) -> None:
        """A stream arrives in batches, and the count has to be retaken.

        `promote-stable-schema` matched on `candidate_schema` alone, so it
        was tested once -- when the candidate was first asserted -- and never
        again. A relation that reached tau on a later `evaluate()` was never
        promoted, which is every use of this pack that is not one batch.
        """
        engine = Engine()
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU - 1):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "works_at", "tail": "acme"}
            )
        engine.evaluate()
        assert _facts_named(engine, "stable_schema") == []

        engine.assert_fact(
            "extracted_fact",
            {"head": f"h{DEFAULT_TAU - 1}", "relation": "works_at", "tail": "acme"},
        )
        engine.evaluate()

        assert [f["relation"] for f in _facts_named(engine, "stable_schema")] == ["works_at"]
        assert len(_facts_named(engine, "aligned_fact")) == DEFAULT_TAU

    def test_facts_arriving_after_promotion_are_aligned_too(self) -> None:
        engine = Engine()
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "works_at", "tail": "acme"}
            )
        engine.evaluate()

        engine.assert_fact(
            "extracted_fact", {"head": "late", "relation": "works_at", "tail": "acme"}
        )
        engine.evaluate()

        assert len(_facts_named(engine, "aligned_fact")) == DEFAULT_TAU + 1

    def test_firings_are_still_auditable_with_match_evidence(self) -> None:
        """rule_trace names the assert-only firings; evidence names their facts."""
        engine = Engine(match_evidence=True)
        engine.load_pack("schema-denoising")
        for i in range(DEFAULT_TAU):
            engine.assert_fact(
                "extracted_fact", {"head": f"h{i}", "relation": "works_at", "tail": "acme"}
            )
        result = engine.evaluate()
        promotions = [m for m in result.match_evidence if m.rule.endswith("promote-stable-schema")]
        # One firing per supporting fact -- the rule joins the candidate to
        # the extracted_facts that support it so the count is retaken as the
        # stream grows. The promoted stable_schema is a duplicate after the
        # first, which CLIPS suppresses.
        assert len(promotions) == DEFAULT_TAU
        assert promotions[0].facts[0].slots == {"relation": "works_at"}

    def test_default_tau_matches_the_shipped_rule(self) -> None:
        """The constant is documentation only if nothing checks it against the YAML."""
        from fathom.rule_packs.schema_denoising import get_rules

        promote = next(r for r in get_rules() if r["name"] == "promote-stable-schema")
        expression = promote["when"][0]["conditions"][0]["expression"]
        assert expression.endswith(f", {DEFAULT_TAU})")
