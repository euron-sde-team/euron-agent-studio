"""Export a flow as a standalone, readable Python script.

The script has four parts: a fixed docstring explaining how to run it, the engine's own
runtime library (`engine/runtime.py`, embedded verbatim, so templates, conditions, the
calculator and JSON transforms behave exactly as in AgentStudio), small helpers for the model
API, tools and node semantics, and `run_flow()`, one commented block per node in the same
order the engine uses.

Security: a flow can come from someone else (an import), so nothing a user typed is ever
written as code. Node names, prompts, URLs and every other value are emitted as Python
literals through `repr()`, comments are reduced to one sanitised line, and identifiers are
derived only from node ids, which validation restricts to `[a-z][a-z0-9_]*`.
"""

from __future__ import annotations

import pprint
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentstudio import __version__
from agentstudio.engine import runtime
from agentstudio.engine.graph import NODE_SPECS, StartConfig
from agentstudio.engine.plan import Plan, PlanNode
from agentstudio.providers.registry import split_ref

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True, slots=True)
class ExportInfo:
    flow_name: str
    workspace: str
    version_label: str
    agentstudio_url: str


def comment(text: str, limit: int = 90) -> str:
    """One safe comment line: control characters (newlines included) become spaces."""
    cleaned = _CONTROL.sub(" ", text).strip()
    return cleaned[:limit] + ("..." if len(cleaned) > limit else "")


def literal(value: Any, indent: int = 0) -> str:
    """A Python literal for JSON-like data, wrapped to stay readable."""
    text = pprint.pformat(value, width=96 - indent, sort_dicts=False)
    pad = " " * indent
    return text.replace("\n", "\n" + pad)


def file_name(flow_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", flow_name.lower()).strip("_")[:60]
    return f"{slug or 'flow'}.py"


def _runtime_source() -> str:
    source = Path(runtime.__file__).read_text(encoding="utf-8")
    # Drop the module docstring and the future import; the script has its own.
    body = source.split('"""', 2)[2]
    return body.replace("from __future__ import annotations\n", "", 1).strip("\n")


def _constant(node_id: str) -> str:
    return f"NODE_{node_id.upper()}"


def _models(plan: Plan) -> dict[str, str]:
    wire: dict[str, str] = {}
    for node in plan.nodes.values():
        if node.spec.uses_model:
            ref = str(getattr(node.config, "model", "offline"))
            provider, model = split_ref(ref)
            wire[ref] = model if provider != "offline" else "offline"
    return wire


def _secrets(plan: Plan) -> list[str]:
    names: set[str] = set()
    for node in plan.nodes.values():
        for value in _strings(node.config.model_dump(mode="json")):
            for path in runtime.template_paths(value) if "{{" in value else []:
                if path and path[0] == "secrets" and len(path) > 1:
                    names.add(str(path[1]))
    return sorted(names)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def line(self, text: str = "") -> None:
        self.lines.append(("    " * self.depth + text) if text else "")

    def block(self, text: str) -> None:
        for line in text.splitlines():
            self.line(line)

    def indent(self) -> None:
        self.depth += 1

    def dedent(self) -> None:
        self.depth -= 1

    def text(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def _node_value(node: PlanNode) -> dict[str, Any]:
    value = node.config.model_dump(mode="json")
    value["settings"] = node.settings.model_dump(mode="json")
    return value


def _incoming(plan: Plan, node_id: str) -> str:
    edges = sorted({(e.source, e.source_handle) for e in plan.incoming.get(node_id, [])})
    return ", ".join(f"({source!r}, {handle!r})" for source, handle in edges)


def _describe(node: PlanNode) -> str:
    kind = NODE_SPECS[node.type].label
    return comment(f"{node.label} ({kind})" if node.label != kind else kind)


def _emit_node(w: _Writer, plan: Plan, node: PlanNode, run: str, number: str) -> None:
    const = _constant(node.id)
    nid = repr(node.id)
    w.line(f"# {number}{'.' if '.' not in number else ''} {_describe(node)}")
    if node.type == "start":
        w.line(f"{run}.inputs = {run}.out[{nid}] = await start_step({const}, inputs)")
        w.line(f"{run}.fire({nid}, 'out')")
        w.line()
        return
    w.line(f"if {run}.reached({_incoming(plan, node.id)}):")
    w.indent()
    call = {
        "llm": f"llm(client, node, {run}.scope())",
        "http": f"http_step(client, node, {run}.scope())",
        "knowledge": f"knowledge_step(client, node, {run}.scope())",
        "calculator": f"calculator_step(node, {run}.scope())",
        "json_transform": f"transform_step(node, {run}.scope())",
        "condition": f"condition_step(node, {run}.scope())",
        "output": f"output_step(node, {run}.scope())",
        "approval": f"approval_step(node, {run}.scope())",
    }.get(node.type)
    if node.type == "agent":
        w.line("tools = {")
        w.indent()
        for attached in plan.tools.get(node.id, []):
            tool_node = plan.nodes[attached.node_id]
            tool_const = _constant(tool_node.id)
            runner = {
                "http": f"lambda args: http_tool(client, {tool_const}, {run}.scope(), args)",
                "knowledge": f"lambda args: knowledge_tool(client, {tool_const}, args)",
                "calculator": "lambda args: calculator_tool(args)",
                "json_transform": f"lambda args: transform_tool({tool_const}, args)",
            }[tool_node.type]
            w.line(f"{attached.name!r}: (")
            w.indent()
            w.line(f"tool_definition({tool_node.type!r}, {tool_const}, {attached.name!r}),")
            w.line(f"{runner},")
            w.dedent()
            w.line("),")
        w.dedent()
        w.line("}")
        call = f"agent(client, node, {run}.scope(), tools)"
    if node.type == "loop":
        body = plan.bodies[node.id]
        item_run = "body" if run == "run" else f"body{number.count('.') + 2}"
        w.line()
        w.line(f"async def body_{node.id}(item: Any, index: int) -> Any:")
        w.indent()
        w.line(f"{item_run} = {run}.child({nid}, item, index)")
        for position, member in enumerate(body.order, start=1):
            _emit_node(w, plan, plan.nodes[member], item_run, f"{number}.{position}")
        terminals = plan.terminal_nodes(node.id)
        w.line(f"return collect({const}, {item_run}, {terminals!r})")
        w.dedent()
        w.line()
        call = f"loop_step(node, {run}.scope(), body_{node.id})"
    target = (
        f"result = {run}.out[{nid}]"
        if node.type in {"condition", "approval"}
        else f"{run}.out[{nid}]"
    )
    w.line(f"{target} = await step(")
    w.indent()
    w.line(f"{run}, {nid}, {const}, lambda node: {call}")
    w.dedent()
    w.line(")")
    if node.type == "condition":
        w.line(f"{run}.fire({nid}, route_handle(result.get('route', 'else')))")
    elif node.type == "approval":
        w.line(
            f"{run}.fire({nid}, 'approved' if result.get('decision') == 'approved' else 'rejected')"
        )
    elif node.type == "loop":
        w.line(f"{run}.fire({nid}, 'done')")
    elif node.type != "output":
        w.line(f"{run}.fire({nid}, 'out')")
    w.dedent()
    w.line()


def export_python(plan: Plan, info: ExportInfo) -> str:
    w = _Writer()
    w.block(HEADER.replace("__VERSION__", __version__))
    w.line()
    w.line("# " + "-" * 86)
    w.line("# The AgentStudio runtime library, embedded unchanged: templates, conditions, the")
    w.line("# calculator, JSON transforms, prompts and tool formats behave exactly as in the app.")
    w.line("# " + "-" * 86)
    w.line()
    w.block(_runtime_source())
    w.line()
    w.line()
    w.line("# " + "-" * 86)
    w.line("# This flow")
    w.line("# " + "-" * 86)
    w.line()
    w.line(f"FLOW_NAME = {info.flow_name!r}")
    w.line(f"FLOW_VERSION = {info.version_label!r}")
    w.line(f"EXPORTED_AT = {datetime.now(UTC).replace(microsecond=0).isoformat()!r}")
    w.line(f"WORKSPACE = {info.workspace!r}")
    w.line(f"DEFAULT_AGENTSTUDIO_URL = {info.agentstudio_url.rstrip('/')!r}")
    w.line(f"MODELS = {literal(_models(plan))}")
    w.line(f"SECRET_NAMES = {_secrets(plan)!r}")
    start = plan.nodes[plan.start_id].config
    sample = start.sample if isinstance(start, StartConfig) else {}
    w.line(f"SAMPLE_INPUTS = {literal(sample)}")
    w.line(f"OUTPUT_NODES = {list(plan.output_ids)!r}")
    w.line()
    w.block(HELPERS)
    w.line()
    ordered = [*plan.top.order, *[m for body in plan.bodies.values() for m in body.order]]
    ordered += [t.node_id for tools in plan.tools.values() for t in tools]
    for node_id in dict.fromkeys(ordered):
        node = plan.nodes[node_id]
        w.line(f"# {_describe(node)}")
        w.line(f"{_constant(node_id)} = {literal(_node_value(node))}")
        w.line()
    w.line()
    w.line(
        "async def run_flow(inputs: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any]:"
    )
    w.indent()
    w.line('"""Run the flow once and return its outputs."""')
    w.line("run = Run()")
    w.line()
    for position, node_id in enumerate(plan.top.order, start=1):
        _emit_node(w, plan, plan.nodes[node_id], "run", str(position))
    w.line("return run.outputs(OUTPUT_NODES)")
    w.dedent()
    w.line()
    w.line()
    w.block(MAIN)
    return w.text()


HEADER = '''#!/usr/bin/env python3
"""An AgentStudio flow, exported as a standalone script (Euron AgentStudio __VERSION__).

FLOW_NAME and FLOW_VERSION below name the flow. The script reproduces it step by step with
httpx: the same templates, conditions and tools, the same model calls, in the same order.

Run it:

    pip install httpx jmespath
    python this_script.py                         # runs the flow on its sample inputs
    python this_script.py --input '{"key": "value"}'
    python this_script.py --input-file inputs.json --approve

Model calls go to any OpenAI-compatible endpoint. By default that is the offline model of
the AgentStudio deployment the flow came from, so the script runs with no provider key.

    AGENTSTUDIO_URL      base URL of the AgentStudio API (offline model, sandbox, knowledge search)
    AGENTSTUDIO_API_KEY  an AgentStudio workspace API key (agst_...)
    LLM_BASE_URL         another OpenAI-compatible endpoint, for example https://api.openai.com/v1
    LLM_API_KEY          the key for LLM_BASE_URL (defaults to AGENTSTUDIO_API_KEY)
    LLM_MODEL            one model name to use for every model step
    SECRET_<NAME>        the value of {{secrets.NAME}} wherever the flow uses it
    APPROVAL_MODE        ask, approve or reject (Human approval steps; default: ask on a terminal)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx'''


HELPERS = '''Json = dict[str, Any]
Client = httpx.AsyncClient

AGENTSTUDIO_URL = os.environ.get("AGENTSTUDIO_URL", DEFAULT_AGENTSTUDIO_URL).rstrip("/")
AGENTSTUDIO_API_KEY = os.environ.get("AGENTSTUDIO_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", AGENTSTUDIO_URL + "/api/v1/offline/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", AGENTSTUDIO_API_KEY)
LLM_MODEL = os.environ.get("LLM_MODEL")
APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "")
SECRETS = {name: os.environ.get(f"SECRET_{name}", "") for name in SECRET_NAMES}
SANDBOX_HOST = "sandbox.agentstudio.test"
RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class StepFailed(Exception):
    """A node could not do its work. Retryable failures are tried again."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class FlowFailed(Exception):
    def __init__(self, node_id: str, error: StepFailed) -> None:
        super().__init__(f"{node_id}: {error.message}")
        self.node_id = node_id
        self.error = error


class Run:
    """Outputs and fired edges of one scope: the whole flow, or one loop iteration."""

    def __init__(self, inputs=None, out=None, fired=(), loops=()) -> None:
        self.inputs = dict(inputs or {})
        self.out = dict(out or {})
        self.fired = set(fired)
        self.loops = tuple(loops)
        self.failed: set[str] = set()

    def reached(self, *edges: tuple[str, str]) -> bool:
        """A node runs when at least one of its incoming edges fired."""
        return any(edge in self.fired for edge in edges)

    def fire(self, node_id: str, *handles: str) -> None:
        self.fired.update((node_id, handle) for handle in handles)

    def scope(self, args: Json | None = None) -> Json:
        return build_scope(self.inputs, self.out, loops=self.loops, args=args, secrets=SECRETS)

    def child(self, loop_id: str, item: Any, index: int) -> Run:
        loops = (*self.loops, (loop_id, item, index))
        return Run(self.inputs, self.out, {(loop_id, "body")}, loops)

    def outputs(self, node_ids: list[str]) -> Json:
        merged: Json = {}
        for node_id in node_ids:
            value = self.out.get(node_id)
            if isinstance(value, dict) and node_id not in self.failed:
                merged.update(value)
        return merged


async def step(run: Run, node_id: str, node: Json, factory: Any) -> Any:
    """Run one node with its timeout and retry policy; continue on error if it allows."""
    settings = node["settings"]
    attempts = settings.get("retries", 0) + 1
    timeout = settings.get("timeout_s", 60)
    error = StepFailed("internal_error", "The step did not run.")
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(factory(node), timeout)
        except TimeoutError:
            message = f"The step did not finish within {timeout:g} seconds."
            error = StepFailed("timeout", message, retryable=True)
        except StepFailed as exc:
            error = exc
        except ExpressionError as exc:
            error = StepFailed("invalid_expression", str(exc))
        if attempt < attempts and error.retryable:
            await asyncio.sleep(settings.get("retry_backoff_s", 1.0) * 2 ** (attempt - 1))
            continue
        break
    if settings.get("continue_on_error"):
        run.failed.add(node_id)
        return {"error": {"code": error.code, "message": error.message}}
    raise FlowFailed(node_id, error)


# Models -------------------------------------------------------------------------------


async def chat(client: Client, model: str, messages: list[Json], options: Json) -> Json:
    """One OpenAI-compatible chat completion; returns the assistant message."""
    body: Json = {"model": LLM_MODEL or MODELS.get(model, model), "messages": messages}
    body.update({key: value for key, value in options.items() if value is not None})
    headers = {"authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
    try:
        response = await client.post(f"{LLM_BASE_URL}/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException as exc:
        message = "The model provider timed out."
        raise StepFailed("provider_timeout", message, retryable=True) from exc
    except httpx.HTTPError as exc:
        message = f"The model provider could not be reached: {exc}"
        raise StepFailed("provider_unreachable", message, retryable=True) from exc
    if response.status_code >= 400:
        message = f"The model provider returned HTTP {response.status_code}: {response.text[:200]}"
        retryable = response.status_code in RETRYABLE_STATUSES
        raise StepFailed("provider_http_error", message, retryable=retryable)
    return response.json()["choices"][0]["message"]


def model_options(node: Json, tools: list[Json] | None = None) -> Json:
    return {
        "temperature": node["temperature"],
        "max_tokens": node["max_tokens"],
        "tools": tools,
        "response_format": response_format(node["output_mode"], node["json_fields"]),
    }


def parse_json(text: str, fields: list[Json]) -> Json:
    try:
        return parse_json_output(text, fields)
    except ExpressionError as exc:
        raise StepFailed("invalid_json", str(exc), retryable=True) from exc


async def llm(client: Client, node: Json, sc: Json) -> Json:
    """A Prompt node: render the prompt, call the model, read its JSON when asked to."""
    messages = build_messages(
        render(node["system"], sc),
        render(node["prompt"], sc),
        output_mode=node["output_mode"],
        json_fields=node["json_fields"],
    )
    message = await chat(client, node["model"], messages, model_options(node))
    text = message.get("content") or ""
    if node["output_mode"] == "json":
        return {"json": parse_json(text, node["json_fields"]), "text": text}
    return {"text": text}


async def agent(client: Client, node: Json, sc: Json, tools: Json) -> Json:
    """An Agent node: call the model with its tools, run the calls it asks for, repeat."""
    definitions = [definition for definition, _ in tools.values()]
    messages = build_messages(
        render(node["system"], sc),
        render(node["task"], sc),
        output_mode=node["output_mode"],
        json_fields=node["json_fields"],
    )
    calls: list[Json] = []
    iterations = 0
    text = ""
    for _ in range(node["max_iterations"]):
        iterations += 1
        options = model_options(node, definitions or None)
        message = await chat(client, node["model"], messages, options)
        requested = (message.get("tool_calls") or []) if definitions else []
        if not requested:
            text = message.get("content") or ""
            break
        asked = [
            {
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": call["function"].get("arguments") or "{}",
            }
            for call in requested
        ]
        messages.append(assistant_message(message.get("content"), asked))
        for call in asked:
            name = call["name"]
            try:
                args = parse_tool_arguments(call["arguments"])
            except ExpressionError as exc:
                args, value = {}, {"error": str(exc)}
            else:
                entry = tools.get(name)
                if entry is None:
                    value = {"error": f"There is no tool named {name!r}."}
                else:
                    value = await entry[1](args)
            messages.append(tool_message(call["id"], value))
            calls.append({"name": name, "arguments": args, "result": value})
    else:
        # Out of iterations: ask for the final answer with the tools taken away.
        message = await chat(client, node["model"], messages, model_options(node))
        text = message.get("content") or ""
    output: Json = {"text": text, "tool_calls": calls, "iterations": iterations}
    if node["output_mode"] == "json":
        output["json"] = parse_json(text, node["json_fields"])
    return output


# Tools --------------------------------------------------------------------------------


def outside_url(url: str) -> str:
    """Inside AgentStudio the sandbox answers sandbox.agentstudio.test; here it is /sandbox."""
    for scheme in ("https://", "http://"):
        if url.startswith(scheme + SANDBOX_HOST):
            return AGENTSTUDIO_URL + "/sandbox" + url[len(scheme + SANDBOX_HOST) :]
    return url


async def http_request(client: Client, node: Json, spec: Json) -> Json:
    if not spec["url"]:
        raise StepFailed("invalid_url", "The URL rendered empty.")
    try:
        response = await client.request(
            spec["method"],
            outside_url(spec["url"]),
            headers=spec["headers"] or None,
            params=spec["params"] or None,
            json=spec.get("json"),
            content=spec.get("content"),
            timeout=node["settings"]["timeout_s"],
        )
    except httpx.TimeoutException as exc:
        raise StepFailed("http_timeout", "The request timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        message = f"The server could not be reached: {exc}"
        raise StepFailed("http_unreachable", message, retryable=True) from exc
    content_type = response.headers.get("content-type", "")
    return http_result(response.status_code, response.text, content_type, node["expect"])


async def http_step(client: Client, node: Json, sc: Json) -> Json:
    result = await http_request(client, node, http_request_spec(node, sc))
    if node["fail_on_status"] and not result["ok"]:
        status = result["status"]
        message = f"The request failed with HTTP {status}."
        raise StepFailed("http_status", message, retryable=status in RETRYABLE_STATUSES)
    return result


async def http_tool(client: Client, node: Json, sc: Json, args: Json) -> Any:
    try:
        result = await http_request(client, node, http_request_spec(node, {**sc, "args": args}))
    except StepFailed as exc:
        return {"error": exc.message}
    except ExpressionError as exc:
        return {"error": str(exc)}
    if node["fail_on_status"] and not result["ok"]:
        return {"error": f"The request failed with HTTP {result['status']}.", **result}
    return result


async def knowledge_search(client: Client, knowledge_base_id: str, query: str, top_k: int) -> Json:
    """Search a knowledge base through the AgentStudio API."""
    headers = {"authorization": f"Bearer {AGENTSTUDIO_API_KEY}"} if AGENTSTUDIO_API_KEY else {}
    url = f"{AGENTSTUDIO_URL}/api/v1/workspaces/{WORKSPACE}/knowledge-bases/{knowledge_base_id}"
    body = {"query": query, "top_k": top_k}
    try:
        response = await client.post(f"{url}/search", json=body, headers=headers)
    except httpx.HTTPError as exc:
        message = f"Knowledge search failed: {exc}"
        raise StepFailed("knowledge_unreachable", message, retryable=True) from exc
    if response.status_code >= 400:
        message = f"Knowledge search returned HTTP {response.status_code}."
        retryable = response.status_code in RETRYABLE_STATUSES
        raise StepFailed("knowledge_failed", message, retryable=retryable)
    results = response.json()["results"]
    return {"results": results, "context": knowledge_context(results)}


async def knowledge_step(client: Client, node: Json, sc: Json) -> Json:
    query = render(node["query"], sc).strip()
    if not query:
        raise StepFailed("empty_query", "The search query rendered empty.")
    return await knowledge_search(client, node["knowledge_base_id"], query, node["top_k"])


async def knowledge_tool(client: Client, node: Json, args: Json) -> Any:
    query = to_text(args.get("query", "")).strip()
    if not query:
        return {"error": "A search query is required."}
    try:
        return await knowledge_search(client, node["knowledge_base_id"], query, node["top_k"])
    except StepFailed as exc:
        return {"error": exc.message}


async def calculator_step(node: Json, sc: Json) -> Json:
    try:
        return {"result": calculate(render(node["expression"], sc))}
    except ExpressionError as exc:
        raise StepFailed("calculation_failed", str(exc)) from exc


async def calculator_tool(args: Json) -> Any:
    try:
        return {"result": calculate(to_text(args.get("expression", "")))}
    except ExpressionError as exc:
        return {"error": str(exc)}


async def transform_step(node: Json, sc: Json) -> Json:
    data = render_value(node["input"], sc)
    try:
        return {"result": transform(data, node["expression"])}
    except ExpressionError as exc:
        raise StepFailed("transform_failed", str(exc)) from exc


async def transform_tool(node: Json, args: Json) -> Any:
    try:
        return {"result": transform(args.get("data"), node["expression"])}
    except ExpressionError as exc:
        return {"error": str(exc)}


# Control flow -------------------------------------------------------------------------


async def start_step(node: Json, inputs: Json) -> Json:
    try:
        return validate_inputs(inputs, node["inputs"])
    except ExpressionError as exc:
        raise FlowFailed("start", StepFailed("invalid_inputs", str(exc))) from exc


async def condition_step(node: Json, sc: Json) -> Json:
    route = choose_route(node["routes"], sc)
    label = next((r["label"] for r in node["routes"] if r["id"] == route), "Else")
    return {"route": route, "label": label}


async def output_step(node: Json, sc: Json) -> Json:
    return {field["name"]: render_value(field["value"], sc) for field in node["fields"]}


async def approval_step(node: Json, sc: Json) -> Json:
    """A Human approval step: ask on the terminal, or follow APPROVAL_MODE."""
    title = render(node["title"], sc).strip() or "Review required"
    message = render(node["message"], sc)
    mode = APPROVAL_MODE or ("ask" if sys.stdin.isatty() else "reject")
    comment = ""
    if mode == "ask":
        print(f"\\n== {title} ==\\n\\n{message}\\n", file=sys.stderr)
        approved = input("Approve? [y/N] ").strip().lower() in {"y", "yes"}
        comment = input("Comment (optional): ").strip()
    else:
        approved = mode == "approve"
    decision = "approved" if approved else "rejected"
    return {"decision": decision, "comment": comment, "decided_by": "script", "decided_at": None}


async def loop_step(node: Json, sc: Json, body: Any) -> Json:
    """A Loop node: run the body once per item, up to `concurrency` items at a time."""
    items = render_value(node["items"], sc)
    if isinstance(items, str):
        items = transform(items, "@") if items.strip().startswith("[") else None
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        raise StepFailed("loop_items", "The loop's items must resolve to a list.")
    items = items[: node["max_items"]]
    gate = asyncio.Semaphore(node["concurrency"])
    results: list[Any] = [None] * len(items)
    failed = 0

    async def one(index: int, item: Any) -> None:
        nonlocal failed
        async with gate:
            try:
                results[index] = await body(item, index)
            except FlowFailed as exc:
                if not node["continue_on_item_error"]:
                    raise
                failed += 1
                error = {"code": exc.error.code, "message": exc.error.message}
                results[index] = {"error": error, "node_id": exc.node_id}

    await asyncio.gather(*(one(index, item) for index, item in enumerate(items)))
    return {"results": results, "count": len(items), "failed": failed}


def collect(node: Json, run: Run, terminals: list[str]) -> Any:
    """What one loop iteration contributes to the loop's results."""
    if node["collect"].strip():
        return render_value(node["collect"], run.scope())
    ran = [n for n in terminals if n in run.out and n not in run.failed]
    if len(ran) == 1:
        return run.out[ran[0]]
    return {n: run.out.get(n) for n in ran}'''


MAIN = """def main() -> None:
    global APPROVAL_MODE
    parser = argparse.ArgumentParser(description=f"Run the {FLOW_NAME} flow.")
    parser.add_argument("--input", help="Inputs as a JSON object.")
    parser.add_argument("--input-file", help="A file with the inputs as a JSON object.")
    decision = parser.add_mutually_exclusive_group()
    decision.add_argument(
        "--approve", action="store_true", help="Approve every Human approval step."
    )
    decision.add_argument(
        "--reject", action="store_true", help="Reject every Human approval step."
    )
    options = parser.parse_args()
    if options.approve:
        APPROVAL_MODE = "approve"
    elif options.reject:
        APPROVAL_MODE = "reject"
    if options.input:
        inputs = json.loads(options.input)
    elif options.input_file:
        inputs = json.loads(Path(options.input_file).read_text(encoding="utf-8"))
    else:
        inputs = dict(SAMPLE_INPUTS)

    async def go() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120) as client:
            return await run_flow(inputs, client)

    try:
        outputs = asyncio.run(go())
    except FlowFailed as exc:
        error = {"node_id": exc.node_id, "code": exc.error.code, "message": exc.error.message}
        print(json.dumps({"error": error}, indent=2), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(outputs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()"""
