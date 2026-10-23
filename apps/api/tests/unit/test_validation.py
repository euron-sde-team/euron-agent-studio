from agentstudio.engine.validate import Issue, ValidationContext, has_errors, validate_graph
from tests.unit.helpers import KB_ID, edge, graph, llm, node, output, start


def codes(issues: list[Issue], severity: str = "error") -> set[str]:
    return {issue.code for issue in issues if issue.severity == severity}


def issue_for(issues: list[Issue], code: str) -> Issue:
    return next(issue for issue in issues if issue.code == code)


def valid_flow() -> tuple[list[dict], list[dict]]:
    nodes = [
        start("question"),
        llm("answer", "Answer: {{inputs.question}}"),
        output(answer="{{answer.text}}"),
    ]
    edges = [edge("start", "answer"), edge("answer", "result")]
    return nodes, edges


def test_a_simple_flow_is_valid() -> None:
    nodes, edges = valid_flow()
    issues = validate_graph(graph(nodes, edges))
    assert issues == []
    assert not has_errors(issues)


def test_start_and_output_are_required() -> None:
    issues = validate_graph(graph([llm("a", "x")], []))
    assert "missing_start" in codes(issues)
    assert "no_output" in codes(issues, "warning")
    two = validate_graph(
        graph([start(), node("start2", "start"), output(x="1")], [edge("start", "result")])
    )
    assert "multiple_start" in codes(two)


def test_invalid_configs_are_reported_per_field() -> None:
    nodes, edges = valid_flow()
    nodes[1] = node("answer", "llm", prompt="", temperature=7)
    issues = validate_graph(graph(nodes, edges))
    fields = {issue.field for issue in issues if issue.code == "invalid_config"}
    assert {"prompt", "temperature"} <= fields
    unknown = validate_graph(graph([start(), node("x", "teleport")], [edge("start", "x")]))
    assert "Unknown node type" in issue_for(unknown, "invalid_config").message


def test_ids_must_be_unique_and_not_reserved() -> None:
    issues = validate_graph(graph([start(), output("inputs", a="1"), output("inputs", b="2")], []))
    assert {"duplicate_id", "invalid_id"} <= codes(issues)


def test_edges_must_join_real_handles() -> None:
    nodes, edges = valid_flow()
    edges = [
        *edges,
        edge("start", "ghost"),
        edge("answer", "answer"),
        edge("start", "answer", "nope"),
        edge("start", "answer"),
    ]
    issues = validate_graph(graph(nodes, edges))
    assert {"dangling_edge", "self_loop", "invalid_handle", "duplicate_edge"} <= codes(issues)


def test_cycles_name_every_member() -> None:
    nodes = [start(), llm("a", "x"), llm("b", "y"), llm("c", "z"), output(v="1")]
    edges = [
        edge("start", "a"),
        edge("a", "b"),
        edge("b", "c"),
        edge("c", "a"),
        edge("c", "result"),
    ]
    issues = validate_graph(graph(nodes, edges))
    cyclic = {issue.node_id for issue in issues if issue.code == "cycle"}
    assert cyclic == {"a", "b", "c"}
    assert "a, b, c" in issue_for(issues, "cycle").message


def test_missing_inputs_and_unreachable_nodes() -> None:
    nodes = [start(), llm("a", "x"), llm("lonely", "y"), llm("island_end", "z"), output(v="1")]
    edges = [edge("start", "a"), edge("a", "result"), edge("lonely", "island_end")]
    issues = validate_graph(graph(nodes, edges))
    assert issue_for(issues, "missing_input").node_id == "lonely"
    assert issue_for(issues, "unreachable").node_id == "island_end"


def test_references_must_point_upstream() -> None:
    nodes = [
        start("q"),
        llm("a", "{{inputs.q}}"),
        llm("b", "{{a.text}} {{c.text}} {{ghost.text}} {{b.text}}"),
        llm("c", "{{a.text}}"),
        output(v="{{b.text}}"),
    ]
    edges = [
        edge("start", "a"),
        edge("a", "b"),
        edge("a", "c"),
        edge("b", "result"),
        edge("c", "result"),
    ]
    issues = validate_graph(graph(nodes, edges))
    messages = [issue.message for issue in issues if issue.code == "unknown_reference"]
    assert any("'c' does not run before" in m for m in messages)
    assert any("no node named 'ghost'" in m for m in messages)
    assert any("'b' does not run before" in m for m in messages)
    assert len(messages) == 3


def test_template_syntax_errors_are_reported() -> None:
    nodes, edges = valid_flow()
    nodes[1] = llm("answer", "{{inputs.question | shout}}")
    assert "invalid_template" in codes(validate_graph(graph(nodes, edges)))


def test_secrets_and_knowledge_bases_resolve_in_the_workspace() -> None:
    nodes = [
        start(),
        node(
            "fetch",
            "http",
            url="https://api.example.com",
            headers=[{"key": "Authorization", "value": "{{secrets.MISSING}}"}],
        ),
        node("search", "knowledge", knowledge_base_id=str(KB_ID), query="refunds"),
        output(v="{{fetch.json}}"),
    ]
    edges = [edge("start", "fetch"), edge("fetch", "search"), edge("search", "result")]
    ctx = ValidationContext(knowledge_base_ids=frozenset(), secret_names=frozenset({"OTHER"}))
    found = codes(validate_graph(graph(nodes, edges), ctx))
    assert {"unknown_secret", "unknown_knowledge_base"} <= found
    ok = ValidationContext(
        knowledge_base_ids=frozenset({KB_ID}), secret_names=frozenset({"MISSING"})
    )
    assert not has_errors(validate_graph(graph(nodes, edges), ok))


def test_unavailable_models_are_a_warning() -> None:
    nodes, edges = valid_flow()
    nodes[1] = llm("answer", "x", model="openai:gpt-4o-mini")
    ctx = ValidationContext(model_available=lambda ref: ref == "offline")
    issues = validate_graph(graph(nodes, edges), ctx)
    assert codes(issues, "warning") == {"model_unavailable"}
    assert not has_errors(issues)


def condition_flow() -> tuple[list[dict], list[dict]]:
    nodes = [
        start("priority"),
        node(
            "route",
            "condition",
            routes=[
                {
                    "id": "urgent",
                    "label": "Urgent",
                    "rules": [
                        {"left": "{{inputs.priority}}", "operator": "equals", "right": "urgent"}
                    ],
                }
            ],
        ),
        output("fast", v="fast"),
    ]
    edges = [edge("start", "route"), edge("route", "fast", "route_urgent")]
    return nodes, edges


def test_unused_branches_are_warned() -> None:
    nodes, edges = condition_flow()
    issues = validate_graph(graph(nodes, edges))
    warning = issue_for(issues, "unused_route")
    assert warning.field == "else"
    assert not has_errors(issues)


def test_tools_attach_only_to_agents_and_only_as_tools() -> None:
    nodes = [
        start("q"),
        node("agent", "agent", task="{{inputs.q}}"),
        node("calc", "calculator", tool_description="Math"),
        node("calc2", "calculator", tool_name="calc", tool_description="Duplicate name"),
        node("search", "knowledge", knowledge_base_id=str(KB_ID), query="{{inputs.q}}"),
        output(v="{{agent.text}}"),
    ]
    edges = [
        edge("start", "agent"),
        edge("agent", "result"),
        edge("calc", "agent", "tool", "tools"),
        edge("calc2", "agent", "tool", "tools"),
        edge("search", "agent", "tool", "tools"),
        edge("start", "search"),
        edge("start", "result", "tool", "in"),
    ]
    issues = validate_graph(graph(nodes, edges))
    messages = [issue.message for issue in issues if issue.code == "invalid_tool"]
    assert any("named 'calc'" in m for m in messages)
    assert any("cannot also be a step" in m for m in messages)
    assert "invalid_handle" in codes(issues)


def test_attached_tools_may_use_args_but_steps_may_not() -> None:
    nodes = [
        start("q"),
        node("agent", "agent", task="{{inputs.q}}"),
        node(
            "lookup",
            "http",
            url="https://crm.example.com/{{args.domain}}",
            parameters=[{"name": "domain"}],
        ),
        node("step", "http", url="https://crm.example.com/{{args.domain}}"),
        output(v="{{agent.text}}"),
    ]
    edges = [
        edge("start", "agent"),
        edge("agent", "step"),
        edge("step", "result"),
        edge("lookup", "agent", "tool", "tools"),
    ]
    issues = validate_graph(graph(nodes, edges))
    refs = [issue for issue in issues if issue.code == "unknown_reference"]
    assert [issue.node_id for issue in refs] == ["step"]


def loop_flow(**loop_config: object) -> tuple[list[dict], list[dict]]:
    nodes = [
        start("items"),
        node("each", "loop", items="{{inputs.items}}", **loop_config),
        llm("summarize", "Summarize {{item}} ({{index}})"),
        output(v="{{each.results}}"),
    ]
    edges = [
        edge("start", "each"),
        edge("each", "summarize", "body"),
        edge("each", "result", "done"),
    ]
    return nodes, edges


def test_loop_bodies_are_closed() -> None:
    nodes, edges = loop_flow()
    assert validate_graph(graph(nodes, edges)) == []
    escaping = [*edges, edge("summarize", "result")]
    assert "loop_escape" in codes(validate_graph(graph(nodes, escaping)))
    nodes2 = [*nodes, llm("outside", "{{inputs.items}}")]
    entering = [*edges, edge("start", "outside"), edge("outside", "summarize")]
    assert "loop_escape" in codes(validate_graph(graph(nodes2, entering)))


def test_some_nodes_cannot_live_in_a_loop() -> None:
    nodes, edges = loop_flow()
    nodes.append(node("ok", "approval", title="Check"))
    edges.append(edge("summarize", "ok"))
    issues = validate_graph(graph(nodes, edges))
    assert issue_for(issues, "not_allowed_in_loop").node_id == "ok"


def test_item_and_index_only_exist_inside_loops() -> None:
    nodes, edges = valid_flow()
    nodes[1] = llm("answer", "{{item}}")
    assert "unknown_reference" in codes(validate_graph(graph(nodes, edges)))


def test_limits_come_from_the_context() -> None:
    nodes, edges = loop_flow(max_items=500)
    ctx = ValidationContext(max_loop_items=100, max_nodes=3)
    issues = validate_graph(graph(nodes, edges), ctx)
    assert any(issue.field == "max_items" for issue in issues)
    assert "too_large" in codes(issues)


def test_step_tools_need_their_inputs() -> None:
    nodes = [
        start(),
        node("calc", "calculator"),
        node("fetch", "http", url="ftp://example.com"),
        node("shape", "json_transform", expression="a"),
        output(v="1"),
    ]
    edges = [
        edge("start", "calc"),
        edge("calc", "fetch"),
        edge("fetch", "shape"),
        edge("shape", "result"),
    ]
    fields = {
        issue.field
        for issue in validate_graph(graph(nodes, edges))
        if issue.code == "invalid_config"
    }
    assert {"expression", "url", "input"} <= fields
