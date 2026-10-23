import asyncio
import json
import time
from decimal import Decimal
from typing import Any

from agentstudio.engine.executor import (
    Decision,
    Executor,
    Limits,
    RestoredStep,
    ResumeState,
    cap_payload,
)
from agentstudio.engine.plan import build_plan
from agentstudio.engine.ports import HttpResponse
from agentstudio.engine.recorder import MemoryRecorder
from agentstudio.providers.base import ChatRequest, ChatResponse
from tests.unit.helpers import (
    KB_ID,
    FakeCancel,
    FakeHttp,
    FakeModels,
    edge,
    graph,
    llm,
    node,
    output,
    services,
    start,
    tool_call_response,
)


async def run(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    inputs: dict[str, Any] | None = None,
    *,
    models: FakeModels | None = None,
    http: FakeHttp | None = None,
    cancel: FakeCancel | None = None,
    limits: Limits | None = None,
    secrets: dict[str, str] | None = None,
    resume: ResumeState | None = None,
    recorder: MemoryRecorder | None = None,
):  # type: ignore[no-untyped-def]
    recorder = recorder or MemoryRecorder()
    executor = Executor(
        build_plan(graph(nodes, edges)),
        services(models, http=http, cancel=cancel),
        recorder,
        limits=limits or Limits(cancel_poll_s=0.01),
        secrets=secrets,
    )
    result = await executor.execute(inputs or {}, resume)
    return result, recorder


def slow_model(delay: float) -> FakeModels:
    async def respond(_: str, request: ChatRequest) -> ChatResponse:
        await asyncio.sleep(delay)
        return ChatResponse(
            content=request.messages[-1]["content"].upper(), prompt_tokens=1, completion_tokens=1
        )

    return FakeModels(respond)


async def test_a_linear_flow_runs_and_records_every_step() -> None:
    nodes = [
        start("question"),
        llm("answer", "Q: {{inputs.question}}"),
        output(answer="{{answer.text}}"),
    ]
    result, recorder = await run(
        nodes, [edge("start", "answer"), edge("answer", "result")], {"question": "why?"}
    )
    assert result.status == "succeeded"
    assert result.outputs == {"answer": "echo: Q: why?"}
    assert [step.node_id for step in recorder.started] == ["start", "answer", "result"]
    assert [step.seq for step in recorder.started] == [1, 2, 3]
    answer = next(step for step in recorder.finished if step.node_id == "answer")
    assert (answer.prompt_tokens, answer.completion_tokens, answer.cost_usd) == (
        10,
        5,
        Decimal("0.001"),
    )
    assert answer.model == "fake:offline"
    started = next(step for step in recorder.started if step.node_id == "answer")
    assert started.input == {"model": "offline", "system": "", "prompt": "Q: why?"}


async def test_independent_branches_run_in_parallel_and_merge_once() -> None:
    nodes = [
        start("q"),
        llm("left", "left"),
        llm("right", "right"),
        llm("merge", "{{left.text}}+{{right.text}}"),
        output(v="{{merge.text}}"),
    ]
    edges = [
        edge("start", "left"),
        edge("start", "right"),
        edge("left", "merge"),
        edge("right", "merge"),
        edge("merge", "result"),
    ]
    began = time.monotonic()
    result, _ = await run(nodes, edges, {"q": "x"}, models=slow_model(0.2))
    elapsed = time.monotonic() - began
    assert result.outputs == {"v": "LEFT+RIGHT"}
    assert elapsed < 0.55, "left and right should have overlapped"


def routing_flow() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
        llm("escalate", "page someone"),
        llm("queue", "queue it"),
        llm("log", "log {{escalate.text}}{{queue.text}}"),
        output("done", path="{{route.label}}", log="{{log.text}}"),
    ]
    edges = [
        edge("start", "route"),
        edge("route", "escalate", "route_urgent"),
        edge("route", "queue", "else"),
        edge("escalate", "log"),
        edge("queue", "log"),
        edge("log", "done"),
    ]
    return nodes, edges


async def test_conditions_skip_the_branch_not_taken() -> None:
    nodes, edges = routing_flow()
    result, recorder = await run(nodes, edges, {"priority": "urgent"})
    assert result.outputs == {"path": "Urgent", "log": "echo: log echo: page someone"}
    assert recorder.status_of("queue") == "skipped"
    assert recorder.status_of("escalate") == "succeeded"
    assert recorder.output_of("route") == {"route": "urgent", "label": "Urgent"}
    result, recorder = await run(nodes, edges, {"priority": "low"})
    assert result.outputs["path"] == "Else"
    assert recorder.status_of("escalate") == "skipped"
    assert [s.node_id for s in recorder.finished].count("log") == 1


def flaky_http(failures: int, status: int = 503) -> FakeHttp:
    calls = {"n": 0}

    def handle(spec: dict[str, Any]) -> HttpResponse:
        calls["n"] += 1
        if calls["n"] <= failures:
            return HttpResponse(status, "busy", "text/plain")
        return HttpResponse(200, json.dumps({"company": "Globex"}), "application/json")

    return FakeHttp(handle)


def http_flow(**settings: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        start(),
        node(
            "fetch",
            "http",
            url="https://crm.example.com/x",
            settings={"retry_backoff_s": 0.01, **settings},
        ),
        output(v="{{fetch.json.company}}"),
    ]
    return nodes, [edge("start", "fetch"), edge("fetch", "result")]


async def test_retryable_failures_are_retried_with_back_off() -> None:
    nodes, edges = http_flow(retries=2)
    result, recorder = await run(nodes, edges, http=flaky_http(2))
    assert result.outputs == {"v": "Globex"}
    fetch = next(step for step in recorder.finished if step.node_id == "fetch")
    assert fetch.attempt == 3
    retries = [
        event
        for (node_id, _, event) in recorder.events
        if node_id == "fetch" and event["type"] == "retry"
    ]
    assert [event["attempt"] for event in retries] == [1, 2]


async def test_failures_beyond_the_retry_budget_fail_the_run() -> None:
    nodes, edges = http_flow(retries=1)
    result, recorder = await run(nodes, edges, http=flaky_http(5))
    assert result.status == "failed"
    assert result.error is not None
    assert result.error["code"] == "http_status"
    assert result.error["node_id"] == "fetch"
    assert recorder.status_of("fetch") == "failed"
    assert recorder.status_of("result") is None


async def test_client_errors_are_not_retried() -> None:
    nodes, edges = http_flow(retries=3)
    _, recorder = await run(nodes, edges, http=flaky_http(1, status=404))
    fetch = next(step for step in recorder.finished if step.node_id == "fetch")
    assert fetch.attempt == 1
    assert fetch.status == "failed"


async def test_continue_on_error_lets_the_flow_go_on() -> None:
    nodes, edges = http_flow(continue_on_error=True)
    nodes[2] = output(v="{{fetch.error.code}}")
    result, recorder = await run(nodes, edges, http=flaky_http(5, status=500))
    assert result.status == "succeeded"
    assert result.outputs == {"v": "http_status"}
    fetch = next(step for step in recorder.finished if step.node_id == "fetch")
    assert fetch.continued
    assert fetch.status == "failed"


async def test_steps_time_out_and_retry() -> None:
    nodes = [
        start(),
        llm("slow", "x", settings={"timeout_s": 0.05, "retries": 1, "retry_backoff_s": 0}),
        output(v="{{slow.text}}"),
    ]
    result, recorder = await run(
        nodes, [edge("start", "slow"), edge("slow", "result")], models=slow_model(0.3)
    )
    assert result.status == "failed"
    assert result.error is not None
    assert result.error["code"] == "timeout"
    assert next(s for s in recorder.finished if s.node_id == "slow").attempt == 2


async def test_a_failure_cancels_running_siblings() -> None:
    nodes = [
        start(),
        llm("slow", "x"),
        node("broken", "calculator", expression="1 / 0"),
        output(v="{{slow.text}}{{broken.result}}"),
    ]
    edges = [
        edge("start", "slow"),
        edge("start", "broken"),
        edge("slow", "result"),
        edge("broken", "result"),
    ]
    result, recorder = await run(nodes, edges, models=slow_model(1.0))
    assert result.status == "failed"
    assert result.error is not None
    assert result.error["node_id"] == "broken"
    assert result.error["code"] == "calculation_failed"
    assert recorder.status_of("slow") == "cancelled"


async def test_invalid_inputs_fail_at_the_start() -> None:
    nodes = [
        node("start", "start", inputs=[{"name": "seats", "type": "integer"}]),
        output(v="{{inputs.seats}}"),
    ]
    result, _ = await run(nodes, [edge("start", "result")], {"seats": "many"})
    assert result.status == "failed"
    assert result.error is not None
    assert result.error["code"] == "invalid_inputs"
    ok, _ = await run(nodes, [edge("start", "result")], {"seats": "3"})
    assert ok.outputs == {"v": 3}


def loop_flow(**config: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        node("start", "start", inputs=[{"name": "items", "type": "array"}]),
        node("each", "loop", items="{{inputs.items}}", **config),
        llm("shout", "{{item}} #{{index}}"),
        output(results="{{each.results}}", count="{{each.count}}", failed="{{each.failed}}"),
    ]
    edges = [edge("start", "each"), edge("each", "shout", "body"), edge("each", "result", "done")]
    return nodes, edges


async def test_loops_run_the_body_per_item_and_collect_in_order() -> None:
    nodes, edges = loop_flow(collect="{{shout.text}}")
    result, recorder = await run(nodes, edges, {"items": ["a", "b", "c"]})
    assert result.outputs == {
        "results": ["echo: a #0", "echo: b #1", "echo: c #2"],
        "count": 3,
        "failed": 0,
    }
    iterations = sorted(s.iteration for s in recorder.finished if s.node_id == "shout")
    assert iterations == ["0", "1", "2"]


async def test_loop_without_collect_returns_the_terminal_output() -> None:
    nodes, edges = loop_flow()
    result, _ = await run(nodes, edges, {"items": ["a"]})
    assert result.outputs["results"] == [{"text": "echo: a #0"}]


async def test_loop_concurrency_overlaps_items() -> None:
    nodes, edges = loop_flow(concurrency=4, collect="{{shout.text}}")
    began = time.monotonic()
    result, _ = await run(nodes, edges, {"items": ["a", "b", "c", "d"]}, models=slow_model(0.2))
    assert result.outputs["results"] == ["A #0", "B #1", "C #2", "D #3"]
    assert time.monotonic() - began < 0.6


async def test_loop_items_can_fail_independently() -> None:
    nodes = [
        node("start", "start", inputs=[{"name": "items", "type": "array"}]),
        node(
            "each",
            "loop",
            items="{{inputs.items}}",
            continue_on_item_error=True,
            collect="{{calc.result}}",
        ),
        node("calc", "calculator", expression="100 / {{item}}"),
        output(results="{{each.results}}", failed="{{each.failed}}"),
    ]
    edges = [edge("start", "each"), edge("each", "calc", "body"), edge("each", "result", "done")]
    result, _ = await run(nodes, edges, {"items": [4, 0, 5]})
    assert result.outputs["failed"] == 1
    assert result.outputs["results"][0] == 25.0
    assert result.outputs["results"][1]["error"]["code"] == "calculation_failed"
    strict = [dict(n) for n in nodes]
    strict[1] = node("each", "loop", items="{{inputs.items}}", collect="{{calc.result}}")
    failed, recorder = await run(strict, edges, {"items": [4, 0]})
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error["code"] == "loop_item_failed"
    assert recorder.status_of("each") == "failed"


async def test_nested_loops_key_iterations_by_path() -> None:
    nodes = [
        node("start", "start", inputs=[{"name": "rows", "type": "array"}]),
        node("rows", "loop", items="{{inputs.rows}}", collect="{{cells.results}}"),
        node("cells", "loop", items="{{item}}", collect="{{double.result}}"),
        node("double", "calculator", expression="{{item}} * 2 + {{rows.index}}"),
        output(v="{{rows.results}}"),
    ]
    edges = [
        edge("start", "rows"),
        edge("rows", "cells", "body"),
        edge("cells", "double", "body"),
        edge("rows", "result", "done"),
    ]
    result, recorder = await run(nodes, edges, {"rows": [[1, 2], [3]]})
    assert result.outputs == {"v": [[2, 4], [7]]}
    keys = sorted(s.iteration for s in recorder.finished if s.node_id == "double")
    assert keys == ["0/0", "0/1", "1/0"]


def approval_flow() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        start("reply"),
        llm("draft", "Draft: {{inputs.reply}}"),
        llm("side", "side work"),
        node(
            "review",
            "approval",
            title="Send this reply?",
            message="{{draft.text}}",
            expires_after_hours=24,
        ),
        output("sent", status="sent", reply="{{draft.text}}", note="{{review.comment}}"),
        output("held", status="held"),
    ]
    edges = [
        edge("start", "draft"),
        edge("start", "side"),
        edge("draft", "review"),
        edge("review", "sent", "approved"),
        edge("review", "held", "rejected"),
    ]
    return nodes, edges


async def test_approvals_pause_the_run_and_resume_on_a_decision() -> None:
    nodes, edges = approval_flow()
    models = FakeModels()
    paused, recorder = await run(nodes, edges, {"reply": "hello"}, models=models)
    assert paused.status == "waiting"
    assert paused.waiting_on == ["review"]
    assert recorder.approvals[0].message == "echo: Draft: hello"
    assert recorder.approvals[0].expires_at is not None
    assert recorder.status_of("side") == "succeeded"
    assert len(models.requests) == 2

    resume = ResumeState(
        steps={
            step.node_id: RestoredStep(step.status, step.output, step.handles)
            for step in recorder.finished
            if step.status in ("succeeded", "skipped")
        },
        decisions={"review": Decision(approved=True, comment="Looks good", decided_by="Ava")},
        next_seq=10,
    )
    done, recorder2 = await run(nodes, edges, {"reply": "hello"}, models=models, resume=resume)
    assert done.status == "succeeded"
    assert done.outputs == {"status": "sent", "reply": "echo: Draft: hello", "note": "Looks good"}
    assert len(models.requests) == 2, "finished steps are not executed again"
    assert recorder2.status_of("held") == "skipped"
    assert recorder2.started[0].seq == 10

    resume.decisions["review"] = Decision(approved=False)
    rejected, _ = await run(nodes, edges, {"reply": "hello"}, models=models, resume=resume)
    assert rejected.outputs == {"status": "held"}


async def test_cancellation_stops_running_steps() -> None:
    cancel = FakeCancel()
    nodes = [start(), llm("slow", "x"), output(v="{{slow.text}}")]

    async def flip() -> None:
        await asyncio.sleep(0.1)
        cancel.flag = True

    flipper = asyncio.create_task(flip())
    result, recorder = await run(
        nodes, [edge("start", "slow"), edge("slow", "result")], models=slow_model(5), cancel=cancel
    )
    await flipper
    assert result.status == "cancelled"
    assert recorder.status_of("slow") == "cancelled"


async def test_runs_time_out_as_a_whole() -> None:
    nodes = [start(), llm("slow", "x"), output(v="{{slow.text}}")]
    limits = Limits(run_timeout_s=0.1, cancel_poll_s=0.01)
    result, recorder = await run(
        nodes, [edge("start", "slow"), edge("slow", "result")], models=slow_model(5), limits=limits
    )
    assert result.status == "failed"
    assert result.error is not None
    assert result.error["code"] == "run_timeout"
    assert recorder.status_of("slow") == "cancelled"


async def test_secrets_are_used_but_never_recorded() -> None:
    http = FakeHttp(
        lambda spec: HttpResponse(
            200, json.dumps({"echo": spec["headers"]["Authorization"]}), "application/json"
        )
    )
    nodes = [
        start(),
        node(
            "fetch",
            "http",
            url="https://crm.example.com",
            headers=[{"key": "Authorization", "value": "Bearer {{secrets.CRM_TOKEN}}"}],
        ),
        output(v="{{fetch.json.echo}}"),
    ]
    result, recorder = await run(
        nodes,
        [edge("start", "fetch"), edge("fetch", "result")],
        http=http,
        secrets={"CRM_TOKEN": "s3cr3t-value"},
    )
    assert http.sent[0]["headers"]["Authorization"] == "Bearer s3cr3t-value"
    assert result.outputs == {"v": "Bearer s3cr3t-value"}
    recorded = json.dumps(
        [s.input for s in recorder.started] + [s.output for s in recorder.finished]
    )
    assert "s3cr3t-value" not in recorded
    assert "[secret:CRM_TOKEN]" in recorded


def test_oversized_payloads_are_truncated() -> None:
    small = {"a": 1}
    assert cap_payload(small, 100) == small
    capped = cap_payload({"text": "x" * 5000}, 1000)
    assert capped["_truncated"] is True
    assert capped["_bytes"] > 1000
    assert len(capped["preview"]) == 500


async def test_json_mode_parses_and_retries_bad_json() -> None:
    answers = iter(["not json", '{"category": "billing", "confidence": "0.9"}'])
    models = FakeModels(lambda _, __: ChatResponse(content=next(answers)))
    nodes = [
        start("text"),
        llm(
            "classify",
            "{{inputs.text}}",
            output_mode="json",
            json_fields=[
                {"name": "category", "enum": ["billing", "tech"]},
                {"name": "confidence", "type": "number"},
            ],
            settings={"retries": 1, "retry_backoff_s": 0},
        ),
        output(category="{{classify.json.category}}", confidence="{{classify.json.confidence}}"),
    ]
    result, _ = await run(
        nodes,
        [edge("start", "classify"), edge("classify", "result")],
        {"text": "refund"},
        models=models,
    )
    assert result.outputs == {"category": "billing", "confidence": 0.9}
    _, request = models.requests[0]
    assert request.response_format is not None
    assert request.response_format["type"] == "json_schema"


def agent_flow(max_iterations: int = 4) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        start("question"),
        node("agent", "agent", task="{{inputs.question}}", max_iterations=max_iterations),
        node("calc", "calculator", tool_description="Do arithmetic"),
        node("docs", "knowledge", knowledge_base_id=str(KB_ID), tool_name="search_docs"),
        output(answer="{{agent.text}}", calls="{{agent.tool_calls | length}}"),
    ]
    edges = [
        edge("start", "agent"),
        edge("agent", "result"),
        edge("calc", "agent", "tool", "tools"),
        edge("docs", "agent", "tool", "tools"),
    ]
    return nodes, edges


async def test_agents_call_their_tools_and_answer() -> None:
    def respond(_: str, request: ChatRequest) -> ChatResponse:
        tool_results = [m for m in request.messages if m["role"] == "tool"]
        if not tool_results:
            return tool_call_response(
                ("calc", '{"expression": "12 * 30"}'),
                ("search_docs", '{"query": "seat pricing"}'),
                ("nope", "{}"),
            )
        summary = " | ".join(m["content"] for m in tool_results)
        return ChatResponse(content=f"final: {summary}", prompt_tokens=30, completion_tokens=12)

    models = FakeModels(respond)
    nodes, edges = agent_flow()
    result, recorder = await run(
        nodes, edges, {"question": "What do 12 seats cost?"}, models=models
    )
    assert result.status == "succeeded"
    assert result.outputs["calls"] == 3
    assert '{"result": 360}' in result.outputs["answer"]
    assert "Answer about seat pricing." in result.outputs["answer"]
    assert "There is no tool named 'nope'" in result.outputs["answer"]
    agent = next(s for s in recorder.finished if s.node_id == "agent")
    assert agent.prompt_tokens == 50
    assert agent.cost_usd == Decimal("0.002")
    tool_events = [e for (_, _, e) in recorder.events if e["type"] == "tool_call"]
    assert [e["name"] for e in tool_events] == ["calc", "search_docs", "nope"]
    first_request = models.requests[0][1]
    assert {t["function"]["name"] for t in first_request.tools or []} == {"calc", "search_docs"}
    second = models.requests[1][1].messages
    assert second[-4]["role"] == "assistant"
    assert len(second[-4]["tool_calls"]) == 3


async def test_agents_stop_at_their_iteration_budget() -> None:
    def respond(_: str, request: ChatRequest) -> ChatResponse:
        if request.tools:
            return tool_call_response(("calc", '{"expression": "1 + 1"}'))
        return ChatResponse(content="forced answer")

    models = FakeModels(respond)
    nodes, edges = agent_flow(max_iterations=2)
    result, _ = await run(nodes, edges, {"question": "loop forever"}, models=models)
    assert result.outputs == {"answer": "forced answer", "calls": 2}
    assert len(models.requests) == 3
    assert models.requests[-1][1].tools is None


async def test_multiple_outputs_merge_in_order() -> None:
    nodes = [
        start("a"),
        output("first", x="1", shared="first"),
        output("second", y="2", shared="second"),
    ]
    result, _ = await run(nodes, [edge("start", "first"), edge("start", "second")], {"a": "z"})
    assert result.outputs == {"x": "1", "y": "2", "shared": "second"}
