from __future__ import annotations


def test_diff_user_facts_empty_pre_and_post_returns_empty() -> None:
    """No facts on either side yields an empty diff."""
    from fathom.engine import _diff_user_facts

    assert _diff_user_facts([], []) == []


def test_diff_user_facts_returns_fact_only_in_post() -> None:
    """A fact present in post but not pre is returned."""
    from fathom.engine import _diff_user_facts
    from fathom.models import AssertedFact

    fact = AssertedFact(template="agent", slots={"id": "alice"})
    assert _diff_user_facts([], [fact]) == [fact]


def test_diff_user_facts_ignores_slot_order_when_filtering() -> None:
    """Equal facts keyed order-insensitively on slots are filtered out."""
    from fathom.engine import _diff_user_facts
    from fathom.models import AssertedFact

    pre = [AssertedFact(template="t", slots={"x": 1, "y": 2})]
    post = [AssertedFact(template="t", slots={"y": 2, "x": 1})]
    assert _diff_user_facts(pre, post) == []


def test_diff_user_facts_preserves_post_order_for_new_facts() -> None:
    """Multiple new facts are returned in the order they appear in post."""
    from fathom.engine import _diff_user_facts
    from fathom.models import AssertedFact

    first = AssertedFact(template="t", slots={"n": 1})
    second = AssertedFact(template="t", slots={"n": 2})
    assert _diff_user_facts([], [first, second]) == [first, second]
