import pytest

from agentstudio.engine.runtime import (
    ExpressionError,
    build_scope,
    evaluate,
    parse_path,
    render,
    render_value,
    resolve,
    template_paths,
    to_text,
)

SCOPE = build_scope(
    {"subject": "Refund request", "amount": 42.5},
    {
        "classify": {"json": {"priority": "urgent", "tags": ["billing", "refund"]}, "text": "{}"},
        "search": {"results": [{"title": "Refunds", "score": 0.9}, {"title": "Billing"}]},
        "count": {"result": 3.0},
    },
    secrets={"CRM_TOKEN": "tok-123"},
)


def test_paths_parse_names_and_indexes() -> None:
    assert parse_path("classify.json.priority") == ["classify", "json", "priority"]
    assert parse_path("search.results[1].title") == ["search", "results", 1, "title"]
    assert parse_path(" items[-1] ") == ["items", -1]


@pytest.mark.parametrize("bad", ["", "1abc", "a..b", "a.", "a[x]", "a b"])
def test_invalid_paths_are_rejected(bad: str) -> None:
    with pytest.raises(ExpressionError):
        parse_path(bad)


def test_resolve_walks_dicts_and_lists_and_misses_softly() -> None:
    assert resolve(SCOPE, ["search", "results", 0, "title"]) == "Refunds"
    assert resolve(SCOPE, ["search", "results", 9, "title"]) is None
    assert resolve(SCOPE, ["nothing", "here"]) is None
    assert resolve(SCOPE, ["classify", "json", "tags", "length"]) == 2


def test_render_interpolates_text_and_json() -> None:
    text = render("Subject: {{inputs.subject}} / tags {{classify.json.tags}}", SCOPE)
    assert text == 'Subject: Refund request / tags ["billing", "refund"]'
    assert render("Missing: [{{nope.value}}]", SCOPE) == "Missing: []"
    assert render("no templates here", SCOPE) == "no templates here"


def test_single_expression_keeps_its_type() -> None:
    assert render_value("{{classify.json.tags}}", SCOPE) == ["billing", "refund"]
    assert render_value("  {{ inputs.amount }} ", SCOPE) == 42.5
    assert render_value("{{inputs.amount}} EUR", SCOPE) == "42.5 EUR"


def test_numbers_render_without_a_trailing_zero() -> None:
    assert to_text(3.0) == "3"
    assert to_text(2.75) == "2.75"
    assert to_text(True) == "true"
    assert to_text(None) == ""


def test_filters() -> None:
    assert evaluate("inputs.subject | upper", SCOPE) == "REFUND REQUEST"
    assert evaluate("classify.json.tags | join(' + ')", SCOPE) == "billing + refund"
    assert evaluate("classify.json.tags | length", SCOPE) == 2
    assert evaluate("classify.json.tags | first", SCOPE) == "billing"
    assert evaluate("missing.value | default('n/a')", SCOPE) == "n/a"
    assert evaluate("inputs.amount | round(0)", SCOPE) == 42.0
    assert evaluate("search.results[0] | json", SCOPE) == '{"title": "Refunds", "score": 0.9}'
    assert render("{{ inputs.subject | lower | trim }}", SCOPE) == "refund request"


def test_unknown_filters_and_bad_arguments_fail_clearly() -> None:
    with pytest.raises(ExpressionError, match="Unknown filter"):
        evaluate("inputs.subject | shout", SCOPE)
    with pytest.raises(ExpressionError, match="filter argument"):
        evaluate("inputs.subject | join(nonsense)", SCOPE)


def test_secrets_and_loop_items_are_in_scope() -> None:
    assert render("Bearer {{secrets.CRM_TOKEN}}", SCOPE) == "Bearer tok-123"
    scope = build_scope({}, {}, loops=[("outer", "a", 0), ("inner", {"n": 2}, 5)], args={"q": "x"})
    assert render("{{item.n}}-{{index}}-{{outer.item}}-{{args.q}}", scope) == "2-5-a-x"


def test_template_paths_lists_every_reference() -> None:
    paths = template_paths("{{a.b}} and {{ c[0] | upper }} and {{secrets.KEY}}")
    assert paths == [["a", "b"], ["c", 0], ["secrets", "KEY"]]
