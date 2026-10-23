import time

import pytest

from agentstudio.engine.runtime import (
    ExpressionError,
    build_scope,
    choose_route,
    evaluate_rule,
    route_handle,
)

SCOPE = build_scope(
    {"total": "1,250.00", "email": "Dana@Globex.example", "tags": ["vip", "billing"]},
    {"classify": {"json": {"priority": "Urgent", "score": 72}}},
)


def rule(left: str, operator: str, right: str = "") -> dict[str, str]:
    return {"left": left, "operator": operator, "right": right}


@pytest.mark.parametrize(
    ("left", "operator", "right", "expected"),
    [
        ("{{classify.json.priority}}", "equals", "urgent", True),
        ("{{classify.json.priority}}", "not_equals", "low", True),
        ("{{inputs.total}}", "equals", "1250", True),
        ("{{inputs.total}}", "greater_than", "1000", True),
        ("{{inputs.total}}", "less_or_equal", "1250", True),
        ("{{classify.json.score}}", "greater_or_equal", "80", False),
        ("{{classify.json.score}}", "less_than", "abc", False),
        ("{{inputs.email}}", "ends_with", "@globex.example", True),
        ("{{inputs.email}}", "starts_with", "dana", True),
        ("{{inputs.email}}", "contains", "GLOBEX", True),
        ("{{inputs.tags}}", "contains", "VIP", True),
        ("{{inputs.tags}}", "not_contains", "sales", True),
        ("{{classify.json.priority}}", "in_list", "high, urgent", True),
        ("{{missing.value}}", "is_empty", "", True),
        ("{{inputs.tags}}", "is_not_empty", "", True),
        ("{{inputs.email}}", "matches", r"^[a-z]+@", False),
        ("{{inputs.email}}", "matches", r"(?i)^dana@", True),
    ],
)
def test_operators(left: str, operator: str, right: str, expected: bool) -> None:
    assert evaluate_rule(rule(left, operator, right), SCOPE) is expected


def test_first_matching_route_wins_and_else_is_the_fallback() -> None:
    routes = [
        {
            "id": "low",
            "label": "Low",
            "rules": [rule("{{classify.json.score}}", "less_than", "50")],
        },
        {
            "id": "review",
            "label": "Needs review",
            "match": "any",
            "rules": [
                rule("{{classify.json.priority}}", "equals", "urgent"),
                rule("{{inputs.total}}", "greater_than", "100000"),
            ],
        },
        {
            "id": "late",
            "label": "Also matches",
            "rules": [rule("{{inputs.tags}}", "contains", "vip")],
        },
    ]
    assert choose_route(routes, SCOPE) == "review"
    assert choose_route(routes[:1], SCOPE) == "else"
    all_rules = [{"id": "both", "label": "Both", "match": "all", "rules": routes[1]["rules"]}]
    assert choose_route(all_rules, SCOPE) == "else"
    assert route_handle("review") == "route_review"
    assert route_handle("else") == "else"


def test_unknown_operators_and_bad_patterns_fail() -> None:
    with pytest.raises(ExpressionError, match="Unknown operator"):
        evaluate_rule(rule("a", "approximately", "b"), SCOPE)
    with pytest.raises(ExpressionError, match="regular expression"):
        evaluate_rule(rule("abc", "matches", "(unclosed"), SCOPE)


def test_regular_expressions_run_in_linear_time() -> None:
    # Catastrophic for a backtracking engine; instant for RE2.
    started = time.monotonic()
    scope = build_scope({"text": "a" * 50_000 + "!"}, {})
    assert not evaluate_rule(rule("{{inputs.text}}", "matches", r"^(a+)+$"), scope)
    assert time.monotonic() - started < 1.0
