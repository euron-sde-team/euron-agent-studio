"""Graph validation: every rule a flow must satisfy before it can be published or run.

Validation never raises on a bad graph. It returns issues (errors block publishing and
running; warnings are advice) with a stable code and the node, edge or field they are about,
so the editor can show each one inline where it belongs.
"""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from agentstudio.engine import runtime
from agentstudio.engine.graph import (
    NODE_SPECS,
    RESERVED_IDS,
    TOOL_TYPES,
    AgentConfig,
    CalculatorConfig,
    GraphDocument,
    GraphEdge,
    GraphNode,
    HttpConfig,
    JsonTransformConfig,
    KnowledgeConfig,
    LlmConfig,
    LoopConfig,
    ToolFields,
    config_templates,
    parse_config,
    parse_settings,
    tool_name,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Severity
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """What exists outside the graph. `None` means "do not check" (pure unit tests, imports)."""

    knowledge_base_ids: frozenset[uuid.UUID] | None = None
    secret_names: frozenset[str] | None = None
    model_available: Callable[[str], bool] | None = None
    max_nodes: int = 200
    max_edges: int = 400
    max_loop_items: int = 200
    max_agent_iterations: int = 10


@dataclass(slots=True)
class _State:
    doc: GraphDocument
    ctx: ValidationContext
    issues: list[Issue] = field(default_factory=list)
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    configs: dict[str, BaseModel] = field(default_factory=dict)
    data_edges: list[GraphEdge] = field(default_factory=list)
    tool_edges: list[GraphEdge] = field(default_factory=list)

    def error(self, code: str, message: str, **where: str | None) -> None:
        self.issues.append(Issue("error", code, message, **where))

    def warn(self, code: str, message: str, **where: str | None) -> None:
        self.issues.append(Issue("warning", code, message, **where))


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


def validate_graph(doc: GraphDocument, ctx: ValidationContext | None = None) -> list[Issue]:
    state = _State(doc, ctx or ValidationContext())
    _check_size(state)
    _check_nodes(state)
    _check_edges(state)
    if not state.nodes:
        return state.issues
    _check_start_and_output(state)
    graph = _DataGraph(state)
    cyclic = _check_cycles(state, graph)
    _check_connectivity(state, graph)
    _check_tools(state)
    bodies = _check_loops(state, graph) if not cyclic else {}
    _check_branches(state)
    if not cyclic:
        _check_references(state, graph, bodies)
    _check_external(state)
    return state.issues


# --------------------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------------------


def _check_size(state: _State) -> None:
    if len(state.doc.nodes) > state.ctx.max_nodes:
        state.error("too_large", f"A flow can have at most {state.ctx.max_nodes} nodes.")
    if len(state.doc.edges) > state.ctx.max_edges:
        state.error("too_large", f"A flow can have at most {state.ctx.max_edges} connections.")


def _pydantic_field(error: Mapping[str, Any]) -> str:
    return ".".join(str(part) for part in error.get("loc", ()))


def _check_nodes(state: _State) -> None:
    for node in state.doc.nodes:
        if node.id in state.nodes:
            state.error("duplicate_id", f"Two nodes are named {node.id!r}.", node_id=node.id)
            continue
        state.nodes[node.id] = node
        if node.id in RESERVED_IDS:
            state.error(
                "invalid_id",
                f"{node.id!r} is reserved by the template language; rename the node.",
                node_id=node.id,
            )
        spec = NODE_SPECS.get(node.type)
        if spec is None:
            state.error("invalid_config", f"Unknown node type {node.type!r}.", node_id=node.id)
            continue
        try:
            config = parse_config(node)
        except ValidationError as exc:
            for error in exc.errors():
                state.error(
                    "invalid_config",
                    _config_message(error["msg"], _pydantic_field(dict(error))),
                    node_id=node.id,
                    field=_pydantic_field(dict(error)) or None,
                )
            continue
        try:
            parse_settings(node)
        except ValidationError as exc:
            for error in exc.errors():
                state.error(
                    "invalid_config",
                    _config_message(error["msg"], _pydantic_field(dict(error))),
                    node_id=node.id,
                    field="settings." + _pydantic_field(dict(error)),
                )
            continue
        state.configs[node.id] = config


def _config_message(message: str, path: str) -> str:
    if message == "Field required":
        return f"{path or 'This setting'} is required."
    if "at least 1 character" in message:
        return f"{path or 'This setting'} cannot be empty."
    return f"{path}: {message}" if path else message


def _handles_out(state: _State, node: GraphNode) -> tuple[str, ...] | None:
    spec = NODE_SPECS.get(node.type)
    config = state.configs.get(node.id)
    if spec is None or config is None:
        return None
    return spec.outputs(config)


def _check_edges(state: _State) -> None:
    seen: set[tuple[str, str, str, str]] = set()
    for edge in state.doc.edges:
        source = state.nodes.get(edge.source)
        target = state.nodes.get(edge.target)
        if source is None or target is None:
            state.error(
                "dangling_edge",
                "This connection points at a node that does not exist.",
                edge_id=edge.id,
            )
            continue
        if edge.source == edge.target:
            state.error(
                "self_loop",
                "A node cannot connect to itself.",
                edge_id=edge.id,
                node_id=edge.source,
            )
            continue
        key = (edge.source, edge.source_handle, edge.target, edge.target_handle)
        if key in seen:
            state.error(
                "duplicate_edge", "These two nodes are already connected this way.", edge_id=edge.id
            )
            continue
        seen.add(key)
        outs = _handles_out(state, source)
        target_spec = NODE_SPECS.get(target.type)
        if outs is not None and edge.source_handle not in outs:
            state.error(
                "invalid_handle",
                f"{source.id!r} has no output named {edge.source_handle!r}.",
                edge_id=edge.id,
                node_id=source.id,
            )
            continue
        if target_spec is not None and edge.target_handle not in target_spec.inputs:
            state.error(
                "invalid_handle",
                f"{target.id!r} has no input named {edge.target_handle!r}.",
                edge_id=edge.id,
                node_id=target.id,
            )
            continue
        attaching = edge.source_handle == "tool" or edge.target_handle == "tools"
        if attaching:
            if not (edge.source_handle == "tool" and edge.target_handle == "tools"):
                state.error(
                    "invalid_tool",
                    "Tools attach from their tool handle to an Agent's tools handle.",
                    edge_id=edge.id,
                    node_id=target.id,
                )
                continue
            state.tool_edges.append(edge)
        else:
            state.data_edges.append(edge)


def _check_start_and_output(state: _State) -> None:
    starts = [node for node in state.nodes.values() if node.type == "start"]
    if not starts:
        state.error("missing_start", "Add a Start node: every flow begins at one.")
    for extra in starts[1:]:
        state.error("multiple_start", "A flow has exactly one Start node.", node_id=extra.id)
    if not any(node.type == "output" for node in state.nodes.values()):
        state.warn("no_output", "Add an Output node so runs return a result.")


# --------------------------------------------------------------------------------------
# The data graph
# --------------------------------------------------------------------------------------


class _DataGraph:
    def __init__(self, state: _State) -> None:
        self.succ: dict[str, list[str]] = defaultdict(list)
        self.pred: dict[str, list[str]] = defaultdict(list)
        for edge in state.data_edges:
            self.succ[edge.source].append(edge.target)
            self.pred[edge.target].append(edge.source)
        attached = {edge.source for edge in state.tool_edges}
        self.attached_tools = attached
        self.agent_of: dict[str, list[str]] = defaultdict(list)
        for edge in state.tool_edges:
            self.agent_of[edge.source].append(edge.target)
        self.executable = [
            node_id
            for node_id, node in state.nodes.items()
            if NODE_SPECS.get(node.type) is not None
            and NODE_SPECS[node.type].executable
            and node_id not in attached
        ]
        self._ancestors: dict[str, frozenset[str]] = {}

    def reachable_from(self, roots: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.succ.get(current, ()))
        return seen

    def ancestors(self, node_id: str) -> frozenset[str]:
        cached = self._ancestors.get(node_id)
        if cached is not None:
            return cached
        seen: set[str] = set()
        queue = deque(self.pred.get(node_id, ()))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.pred.get(current, ()))
        result = frozenset(seen)
        self._ancestors[node_id] = result
        return result


def _check_cycles(state: _State, graph: _DataGraph) -> bool:
    """Tarjan's strongly connected components; each component larger than one is a cycle."""
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    counter = 0
    components: list[list[str]] = []

    for root in state.nodes:
        if root in index_of:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            successors = graph.succ.get(node, [])
            if child < len(successors):
                work.append((node, child + 1))
                nxt = successors[child]
                if nxt not in index_of:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
                continue
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

    for component in components:
        names = ", ".join(sorted(component))
        for node_id in sorted(component):
            state.error(
                "cycle",
                f"These nodes form a loop of connections: {names}. "
                "Use a Loop node to repeat steps.",
                node_id=node_id,
            )
    return bool(components)


def _check_connectivity(state: _State, graph: _DataGraph) -> None:
    starts = [node_id for node_id, node in state.nodes.items() if node.type == "start"]
    reached = graph.reachable_from(starts)
    for node_id in graph.executable:
        node = state.nodes[node_id]
        if node.type == "start":
            continue
        if not graph.pred.get(node_id):
            state.error(
                "missing_input",
                "Nothing connects into this node, so it would never run.",
                node_id=node_id,
            )
        elif starts and node_id not in reached:
            state.error(
                "unreachable",
                "This node cannot be reached from Start.",
                node_id=node_id,
            )
    for tool_id in graph.attached_tools:
        agents = graph.agent_of.get(tool_id, [])
        if starts and agents and not any(agent in reached for agent in agents):
            state.error(
                "unreachable",
                "The agent this tool is attached to cannot be reached.",
                node_id=tool_id,
            )


def _check_tools(state: _State) -> None:
    data_touching = {edge.source for edge in state.data_edges} | {
        edge.target for edge in state.data_edges
    }
    names_per_agent: dict[str, dict[str, str]] = defaultdict(dict)
    for edge in state.tool_edges:
        tool = state.nodes[edge.source]
        if tool.type not in TOOL_TYPES:
            state.error("invalid_tool", "Only tool nodes can attach to an agent.", node_id=tool.id)
            continue
        if tool.id in data_touching:
            state.error(
                "invalid_tool",
                "A tool attached to an agent cannot also be a step in the flow.",
                node_id=tool.id,
            )
        config = state.configs.get(tool.id)
        if isinstance(config, ToolFields):
            name = tool_name(tool, config)
            other = names_per_agent[edge.target].get(name)
            if other and other != tool.id:
                state.error(
                    "invalid_tool",
                    f"Two tools of this agent are named {name!r}.",
                    node_id=tool.id,
                    field="tool_name",
                )
            names_per_agent[edge.target][name] = tool.id


def _check_loops(state: _State, graph: _DataGraph) -> dict[str, set[str]]:
    bodies: dict[str, set[str]] = {}
    for loop_id, node in state.nodes.items():
        if node.type != "loop":
            continue
        entries = [
            edge.target
            for edge in state.data_edges
            if edge.source == loop_id and edge.source_handle == "body"
        ]
        if not entries:
            state.warn("unused_route", "This loop has no steps in its body.", node_id=loop_id)
        body = graph.reachable_from(entries)
        body.discard(loop_id)
        bodies[loop_id] = body
        for edge in state.data_edges:
            inside_source = edge.source in body
            inside_target = edge.target in body
            from_loop_body = edge.source == loop_id and edge.source_handle == "body"
            if inside_target and not inside_source and not from_loop_body:
                state.error(
                    "loop_escape",
                    "Only the Loop node can connect into its body.",
                    edge_id=edge.id,
                    node_id=edge.target,
                )
            elif inside_source and not inside_target:
                state.error(
                    "loop_escape",
                    "Steps inside a loop body cannot connect to steps outside it; "
                    "use the loop's done output.",
                    edge_id=edge.id,
                    node_id=edge.source,
                )
        for member in body:
            if state.nodes[member].type in {"start", "output", "approval"}:
                label = NODE_SPECS[state.nodes[member].type].label
                state.error(
                    "not_allowed_in_loop",
                    f"A {label} node cannot be inside a loop body.",
                    node_id=member,
                )
    return bodies


def _check_branches(state: _State) -> None:
    used = {(edge.source, edge.source_handle) for edge in state.data_edges}
    for node_id, node in state.nodes.items():
        if node.type not in {"condition", "approval", "loop"}:
            continue
        outs = _handles_out(state, node) or ()
        for handle in outs:
            if handle == "body" or (node_id, handle) in used:
                continue
            state.warn(
                "unused_route",
                f"The {handle.replace('route_', '')!r} branch leads nowhere.",
                node_id=node_id,
                field=handle,
            )


# --------------------------------------------------------------------------------------
# Template references
# --------------------------------------------------------------------------------------


def _enclosing_loops(node_id: str, bodies: dict[str, set[str]]) -> list[str]:
    return [loop_id for loop_id, body in bodies.items() if node_id in body]


def _check_references(state: _State, graph: _DataGraph, bodies: dict[str, set[str]]) -> None:
    for node_id, config in state.configs.items():
        node = state.nodes[node_id]
        agents = graph.agent_of.get(node_id, [])
        scope_owner = agents[0] if agents else node_id
        allowed = set(graph.ancestors(scope_owner))
        loops = _enclosing_loops(scope_owner, bodies)
        allowed.update(loops)
        in_loop = bool(loops)
        templates = list(config_templates(node.type, config))
        for field_path, template in templates:
            _check_template(
                state, node_id, field_path, template, allowed, in_loop=in_loop, is_tool=bool(agents)
            )
        if isinstance(config, LoopConfig) and config.collect:
            body = bodies.get(node_id, set())
            body_allowed = set(graph.ancestors(node_id)) | body | {node_id} | set(loops)
            _check_template(
                state, node_id, "collect", config.collect, body_allowed, in_loop=True, is_tool=False
            )


def _check_template(
    state: _State,
    node_id: str,
    field_path: str,
    template: str,
    allowed: set[str],
    *,
    in_loop: bool,
    is_tool: bool,
) -> None:
    try:
        paths = runtime.template_paths(template)
    except runtime.ExpressionError as exc:
        state.error("invalid_template", str(exc), node_id=node_id, field=field_path)
        return
    for path in paths:
        root = str(path[0])
        if root == "inputs":
            continue
        if root == "secrets":
            if len(path) < 2 or not isinstance(path[1], str):
                state.error(
                    "unknown_secret",
                    "Name the secret: {{secrets.NAME}}.",
                    node_id=node_id,
                    field=field_path,
                )
            elif state.ctx.secret_names is not None and path[1] not in state.ctx.secret_names:
                state.error(
                    "unknown_secret",
                    f"There is no secret named {path[1]!r} in this workspace.",
                    node_id=node_id,
                    field=field_path,
                )
            continue
        if root in {"item", "index"}:
            if not in_loop:
                state.error(
                    "unknown_reference",
                    f"{{{{{root}}}}} only exists inside a loop body.",
                    node_id=node_id,
                    field=field_path,
                )
            continue
        if root == "args":
            if not is_tool:
                state.error(
                    "unknown_reference",
                    "{{args.*}} only exists in a tool attached to an agent.",
                    node_id=node_id,
                    field=field_path,
                )
            continue
        if root not in state.nodes:
            state.error(
                "unknown_reference",
                f"There is no node named {root!r}.",
                node_id=node_id,
                field=field_path,
            )
        elif root == node_id or root not in allowed:
            state.error(
                "unknown_reference",
                f"{root!r} does not run before this node, so its output is not available here.",
                node_id=node_id,
                field=field_path,
            )


# --------------------------------------------------------------------------------------
# Settings that depend on the workspace and the deployment
# --------------------------------------------------------------------------------------


def _check_external(state: _State) -> None:
    ctx = state.ctx
    attached = {edge.source for edge in state.tool_edges}
    for node_id, config in state.configs.items():
        if (
            isinstance(config, LlmConfig | AgentConfig)
            and ctx.model_available is not None
            and not ctx.model_available(config.model)
        ):
            state.warn(
                "model_unavailable",
                f"The model {config.model!r} is not configured on this deployment.",
                node_id=node_id,
                field="model",
            )
        if isinstance(config, AgentConfig) and config.max_iterations > ctx.max_agent_iterations:
            state.error(
                "invalid_config",
                f"Agents can take at most {ctx.max_agent_iterations} iterations here.",
                node_id=node_id,
                field="max_iterations",
            )
        if isinstance(config, LoopConfig) and config.max_items > ctx.max_loop_items:
            state.error(
                "invalid_config",
                f"Loops can process at most {ctx.max_loop_items} items here.",
                node_id=node_id,
                field="max_items",
            )
        if isinstance(config, KnowledgeConfig):
            if (
                ctx.knowledge_base_ids is not None
                and config.knowledge_base_id not in ctx.knowledge_base_ids
            ):
                state.error(
                    "unknown_knowledge_base",
                    "Choose a knowledge base from this workspace.",
                    node_id=node_id,
                    field="knowledge_base_id",
                )
            if node_id not in attached and not config.query.strip():
                state.error(
                    "invalid_config", "Enter a search query.", node_id=node_id, field="query"
                )
        if (
            isinstance(config, CalculatorConfig)
            and node_id not in attached
            and not config.expression.strip()
        ):
            state.error(
                "invalid_config", "Enter an expression.", node_id=node_id, field="expression"
            )
        if (
            isinstance(config, JsonTransformConfig)
            and node_id not in attached
            and not config.input.strip()
        ):
            state.error(
                "invalid_config", "Choose the data to transform.", node_id=node_id, field="input"
            )
        if isinstance(config, HttpConfig):
            url = config.url.strip()
            if "{{" not in url.split("/")[0] and not url.lower().startswith(
                ("http://", "https://")
            ):
                state.error(
                    "invalid_config",
                    "The URL must start with http:// or https://.",
                    node_id=node_id,
                    field="url",
                )
