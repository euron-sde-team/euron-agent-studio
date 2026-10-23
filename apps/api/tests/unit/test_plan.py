import pytest

from agentstudio.engine.plan import InvalidGraphError, build_plan
from tests.unit.helpers import edge, graph, llm, node, output, start


def test_order_is_topological_and_reads_like_the_drawing() -> None:
    nodes = [
        start("q"),
        node("top", "llm", x=200, y=0, prompt="a"),
        node("bottom", "llm", x=200, y=200, prompt="b"),
        node("merge", "llm", x=400, y=100, prompt="{{top.text}} {{bottom.text}}"),
        node("result", "output", x=600, fields=[{"name": "v", "value": "{{merge.text}}"}]),
    ]
    edges = [
        edge("start", "bottom"),
        edge("start", "top"),
        edge("top", "merge"),
        edge("bottom", "merge"),
        edge("merge", "result"),
    ]
    plan = build_plan(graph(nodes, edges))
    assert plan.top.order == ("start", "top", "bottom", "merge", "result")
    assert plan.start_id == "start"
    assert plan.output_ids == ("result",)


def test_loop_bodies_and_attached_tools_get_their_own_scopes() -> None:
    nodes = [
        start("items"),
        node("each", "loop", items="{{inputs.items}}"),
        llm("first", "{{item}}"),
        llm("second", "{{first.text}}"),
        node("agent", "agent", task="{{item}}"),
        node("calc", "calculator"),
        output(v="{{each.results}}"),
        node("sticky", "note", text="remember"),
    ]
    edges = [
        edge("start", "each"),
        edge("each", "first", "body"),
        edge("first", "second"),
        edge("first", "agent"),
        edge("calc", "agent", "tool", "tools"),
        edge("each", "result", "done"),
    ]
    plan = build_plan(graph(nodes, edges))
    assert plan.top.order == ("start", "each", "result")
    assert set(plan.bodies["each"].order) == {"first", "second", "agent"}
    assert plan.bodies["each"].order[0] == "first"
    assert [tool.name for tool in plan.tools["agent"]] == ["calc"]
    assert "sticky" not in plan.nodes
    assert sorted(plan.terminal_nodes("each")) == ["agent", "second"]


def test_invalid_graphs_cannot_be_planned() -> None:
    with pytest.raises(InvalidGraphError) as error:
        build_plan(graph([llm("a", "x")], []))
    assert error.value.issues
