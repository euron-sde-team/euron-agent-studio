"""What each node type does when it runs.

Every handler works in two phases. `prepare` renders the node's templates against the
current scope and returns a record of exactly what the node is about to consume (it becomes
the step's input in the trace, and retries reuse it). `run` performs the work and returns the
output and the output handles that fire. Loop and Human approval nodes need the executor
itself and are handled there; their `prepare` lives here.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from agentstudio.engine import runtime
from agentstudio.engine.errors import RETRYABLE_STATUSES, NodeError
from agentstudio.engine.graph import (
    AgentConfig,
    ApprovalConfig,
    CalculatorConfig,
    ConditionConfig,
    HttpConfig,
    JsonTransformConfig,
    KnowledgeConfig,
    LlmConfig,
    LoopConfig,
    ModelConfig,
    OutputConfig,
    StartConfig,
)
from agentstudio.engine.plan import Plan, PlanNode, config_of
from agentstudio.engine.ports import EngineServices, ModelResult
from agentstudio.providers.base import ChatRequest, ProviderError

Emit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class NodeContext:
    plan: Plan
    node: PlanNode
    scope: dict[str, Any]
    raw_inputs: Mapping[str, Any]
    services: EngineServices
    emit: Emit


@dataclass(slots=True)
class Prepared:
    record: dict[str, Any] | None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    simulated: bool = False
    cached: bool = True
    calls: int = 0

    def add(self, result: ModelResult) -> None:
        self.model = (
            f"{result.provider}:{result.model}" if result.provider != "offline" else "offline"
        )
        self.prompt_tokens += result.prompt_tokens
        self.completion_tokens += result.completion_tokens
        self.cost_usd += result.cost_usd
        self.simulated = self.simulated or result.simulated
        self.cached = self.cached and result.cached
        self.calls += 1


@dataclass(slots=True)
class NodeResult:
    output: Any
    handles: tuple[str, ...] = ("out",)
    usage: Usage | None = None


class Handler(Protocol):
    def prepare(self, ctx: NodeContext) -> Prepared: ...

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult: ...


def _expression_error(exc: runtime.ExpressionError, code: str = "invalid_expression") -> NodeError:
    return NodeError(code, str(exc))


def _fields(config: ModelConfig) -> list[dict[str, Any]]:
    return [field.model_dump() for field in config.json_fields]


# --------------------------------------------------------------------------------------
# Start and Output
# --------------------------------------------------------------------------------------


class StartHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        return Prepared({"inputs": dict(ctx.raw_inputs)})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, StartConfig)
        fields = [field.model_dump() for field in config.inputs]
        try:
            return NodeResult(runtime.validate_inputs(ctx.raw_inputs, fields))
        except runtime.ExpressionError as exc:
            raise NodeError("invalid_inputs", str(exc)) from exc


class OutputHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, OutputConfig)
        try:
            values = {f.name: runtime.render_value(f.value, ctx.scope) for f in config.fields}
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        return Prepared(None, values)

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        return NodeResult(prepared.values, handles=())


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------


async def complete(
    ctx: NodeContext,
    config: ModelConfig,
    messages: list[dict[str, Any]],
    usage: Usage,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> ModelResult:
    request = ChatRequest(
        model=config.model,
        messages=messages,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        tools=tools,
        response_format=runtime.response_format(config.output_mode, _fields(config)),
    )
    cache_ttl = ctx.node.settings.cache_ttl_s if config.temperature == 0 else 0
    try:
        result = await ctx.services.models.complete(config.model, request, cache_ttl_s=cache_ttl)
    except ProviderError as exc:
        raise NodeError(exc.code, exc.message, retryable=exc.retryable) from exc
    usage.add(result)
    await ctx.emit(
        {
            "type": "model_call",
            "model": usage.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "latency_ms": result.latency_ms,
            "cached": result.cached,
            "tool_calls": [call.name for call in result.response.tool_calls],
        }
    )
    return result


def _structured(text: str, config: ModelConfig) -> dict[str, Any]:
    try:
        return runtime.parse_json_output(text, _fields(config))
    except runtime.ExpressionError as exc:
        # Models occasionally break format; another attempt usually fixes it.
        raise NodeError("invalid_json", str(exc), retryable=True) from exc


class LlmHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, LlmConfig)
        try:
            system = runtime.render(config.system, ctx.scope)
            prompt = runtime.render(config.prompt, ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        messages = runtime.build_messages(
            system, prompt, output_mode=config.output_mode, json_fields=_fields(config)
        )
        record = {"model": config.model, "system": system, "prompt": prompt}
        return Prepared(record, {"messages": messages})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, LlmConfig)
        usage = Usage()
        result = await complete(ctx, config, list(prepared.values["messages"]), usage)
        text = result.response.content or ""
        output: dict[str, Any] = {"text": text}
        if config.output_mode == "json":
            output = {"json": _structured(text, config), "text": text}
        return NodeResult(output, usage=usage)


class AgentHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, AgentConfig)
        try:
            system = runtime.render(config.system, ctx.scope)
            task = runtime.render(config.task, ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        tools = ctx.plan.tools.get(ctx.node.id, [])
        definitions = [
            runtime.tool_definition(
                ctx.plan.nodes[tool.node_id].type,
                ctx.plan.nodes[tool.node_id].config.model_dump(mode="json"),
                tool.name,
            )
            for tool in tools
        ]
        messages = runtime.build_messages(
            system, task, output_mode=config.output_mode, json_fields=_fields(config)
        )
        record = {
            "model": config.model,
            "system": system,
            "task": task,
            "tools": [tool.name for tool in tools],
            "max_iterations": config.max_iterations,
        }
        return Prepared(record, {"messages": messages, "definitions": definitions})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, AgentConfig)
        messages: list[dict[str, Any]] = list(prepared.values["messages"])
        definitions: list[dict[str, Any]] = prepared.values["definitions"]
        by_name = {
            tool.name: ctx.plan.nodes[tool.node_id] for tool in ctx.plan.tools.get(ctx.node.id, [])
        }
        usage = Usage()
        calls: list[dict[str, Any]] = []
        iterations = 0
        text = ""
        for _ in range(config.max_iterations):
            iterations += 1
            result = await complete(ctx, config, messages, usage, tools=definitions or None)
            tool_calls = result.response.tool_calls if definitions else []
            if not tool_calls:
                text = result.response.content or ""
                break
            messages.append(
                runtime.assistant_message(
                    result.response.content,
                    [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in tool_calls],
                )
            )
            for call in tool_calls:
                started = time.monotonic()
                try:
                    args = runtime.parse_tool_arguments(call.arguments)
                except runtime.ExpressionError as exc:
                    args, value = {}, {"error": str(exc)}
                else:
                    tool = by_name.get(call.name)
                    value = (
                        await run_tool(ctx, tool, args)
                        if tool is not None
                        else {"error": f"There is no tool named {call.name!r}."}
                    )
                messages.append(runtime.tool_message(call.id, value))
                record = {
                    "name": call.name,
                    "arguments": args,
                    "result": value,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
                calls.append(record)
                await ctx.emit({"type": "tool_call", **record})
        else:
            # Out of iterations: ask for the final answer with the tools taken away.
            result = await complete(ctx, config, messages, usage, tools=None)
            text = result.response.content or ""
        output: dict[str, Any] = {"text": text, "tool_calls": calls, "iterations": iterations}
        if config.output_mode == "json":
            output["json"] = _structured(text, config)
        return NodeResult(output, usage=usage)


# --------------------------------------------------------------------------------------
# Tools, as steps and as an agent's tools
# --------------------------------------------------------------------------------------


async def _send_http(ctx: NodeContext, config: HttpConfig, spec: dict[str, Any]) -> dict[str, Any]:
    if not spec["url"]:
        raise NodeError("invalid_url", "The URL rendered empty.")
    response = await ctx.services.http.send(spec, timeout_s=ctx.node.settings.timeout_s)
    return runtime.http_result(response.status, response.text, response.content_type, config.expect)


async def run_tool(ctx: NodeContext, tool: PlanNode, args: dict[str, Any]) -> Any:
    """Run a tool node on an agent's behalf. Failures go back to the model as results."""
    config = tool.config
    try:
        if isinstance(config, HttpConfig):
            scope = {**ctx.scope, "args": args}
            result = await _send_http(
                ctx, config, runtime.http_request_spec(config.model_dump(), scope)
            )
            if config.fail_on_status and not result["ok"]:
                return {"error": f"The request failed with HTTP {result['status']}.", **result}
            return result
        if isinstance(config, KnowledgeConfig):
            query = runtime.to_text(args.get("query", "")).strip()
            if not query:
                return {"error": "A search query is required."}
            results = await ctx.services.knowledge.search(
                config.knowledge_base_id, query, config.top_k
            )
            return {"results": results, "context": runtime.knowledge_context(results)}
        if isinstance(config, CalculatorConfig):
            return {"result": runtime.calculate(runtime.to_text(args.get("expression", "")))}
        if isinstance(config, JsonTransformConfig):
            return {"result": runtime.transform(args.get("data"), config.expression)}
    except runtime.ExpressionError as exc:
        return {"error": str(exc)}
    except NodeError as exc:
        return {"error": exc.message}
    return {"error": "This node cannot be used as a tool."}


class HttpHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, HttpConfig)
        try:
            spec = runtime.http_request_spec(config.model_dump(), ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        return Prepared(dict(spec), {"spec": spec})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, HttpConfig)
        result = await _send_http(ctx, config, prepared.values["spec"])
        if config.fail_on_status and not result["ok"]:
            raise NodeError(
                "http_status",
                f"The request failed with HTTP {result['status']}.",
                retryable=result["status"] in RETRYABLE_STATUSES,
                details={
                    "status": result["status"],
                    "body": result.get("json") or result.get("text"),
                },
            )
        return NodeResult(result)


class KnowledgeHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, KnowledgeConfig)
        try:
            query = runtime.render(config.query, ctx.scope).strip()
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        record = {
            "knowledge_base_id": str(config.knowledge_base_id),
            "query": query,
            "top_k": config.top_k,
        }
        return Prepared(record, {"query": query})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, KnowledgeConfig)
        query = prepared.values["query"]
        if not query:
            raise NodeError("empty_query", "The search query rendered empty.")
        results = await ctx.services.knowledge.search(config.knowledge_base_id, query, config.top_k)
        return NodeResult({"results": results, "context": runtime.knowledge_context(results)})


class CalculatorHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, CalculatorConfig)
        try:
            expression = runtime.render(config.expression, ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        return Prepared({"expression": expression}, {"expression": expression})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        try:
            return NodeResult({"result": runtime.calculate(prepared.values["expression"])})
        except runtime.ExpressionError as exc:
            raise _expression_error(exc, "calculation_failed") from exc


class JsonTransformHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, JsonTransformConfig)
        try:
            data = runtime.render_value(config.input, ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        return Prepared({"input": data, "expression": config.expression}, {"data": data})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, JsonTransformConfig)
        try:
            return NodeResult(
                {"result": runtime.transform(prepared.values["data"], config.expression)}
            )
        except runtime.ExpressionError as exc:
            raise _expression_error(exc, "transform_failed") from exc


# --------------------------------------------------------------------------------------
# Control flow
# --------------------------------------------------------------------------------------


class ConditionHandler:
    def prepare(self, ctx: NodeContext) -> Prepared:
        config = config_of(ctx.node, ConditionConfig)
        rules = []
        try:
            for route in config.routes:
                for rule in route.rules:
                    left = runtime.render_value(rule.left, ctx.scope)
                    right = (
                        None
                        if rule.operator in runtime.UNARY_OPERATORS
                        else runtime.render_value(rule.right, ctx.scope)
                    )
                    rules.append(
                        {"route": route.id, "left": left, "operator": rule.operator, "right": right}
                    )
        except runtime.ExpressionError as exc:
            raise _expression_error(exc) from exc
        return Prepared({"rules": rules})

    async def run(self, ctx: NodeContext, prepared: Prepared) -> NodeResult:
        config = config_of(ctx.node, ConditionConfig)
        try:
            route = runtime.choose_route(config.model_dump()["routes"], ctx.scope)
        except runtime.ExpressionError as exc:
            raise _expression_error(exc, "condition_failed") from exc
        label = next((r.label for r in config.routes if r.id == route), "Else")
        return NodeResult({"route": route, "label": label}, handles=(runtime.route_handle(route),))


def prepare_loop(ctx: NodeContext, max_items: int) -> Prepared:
    config = config_of(ctx.node, LoopConfig)
    try:
        items = runtime.render_value(config.items, ctx.scope)
    except runtime.ExpressionError as exc:
        raise _expression_error(exc) from exc
    if isinstance(items, str):
        items = runtime.transform(items, "@") if items.strip().startswith("[") else None
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        raise NodeError("loop_items", "The loop's items must resolve to a list.")
    limit = min(config.max_items, max_items)
    record = {"count": len(items), "processed": min(len(items), limit), "items": items[:limit]}
    return Prepared(record, {"items": items[:limit]})


def prepare_approval(ctx: NodeContext) -> Prepared:
    config = config_of(ctx.node, ApprovalConfig)
    try:
        title = runtime.render(config.title, ctx.scope).strip() or "Review required"
        message = runtime.render(config.message, ctx.scope)
    except runtime.ExpressionError as exc:
        raise _expression_error(exc) from exc
    return Prepared({"title": title[:200], "message": message})


HANDLERS: dict[str, Handler] = {
    "start": StartHandler(),
    "output": OutputHandler(),
    "llm": LlmHandler(),
    "agent": AgentHandler(),
    "http": HttpHandler(),
    "knowledge": KnowledgeHandler(),
    "calculator": CalculatorHandler(),
    "json_transform": JsonTransformHandler(),
    "condition": ConditionHandler(),
}
