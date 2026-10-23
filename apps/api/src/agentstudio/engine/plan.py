"""Compile a valid graph into an execution plan.

The plan is what both the executor and the Python exporter walk: nodes with their parsed
configuration, the data edges into and out of each node, the tools attached to each agent,
and one scope per loop body, each with a deterministic topological order (ties broken by
canvas position, left to right then top to bottom, so the order reads like the drawing).
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel

from agentstudio.engine.graph import (
    NODE_SPECS,
    GraphDocument,
    GraphEdge,
    GraphNode,
    NodeSettings,
    NodeSpec,
    ToolFields,
    display_label,
    parse_config,
    parse_settings,
    tool_name,
)
from agentstudio.engine.validate import ValidationContext, has_errors, validate_graph


class InvalidGraphError(ValueError):
    """The graph has validation errors; it cannot be planned or run."""

    def __init__(self, issues: list[object]) -> None:
        super().__init__(f"{len(issues)} validation issue(s)")
        self.issues = issues


@dataclass(frozen=True, slots=True)
class PlanNode:
    node: GraphNode
    spec: NodeSpec
    config: BaseModel
    settings: NodeSettings
    label: str

    @property
    def id(self) -> str:
        return self.node.id

    @property
    def type(self) -> str:
        return self.node.type


@dataclass(frozen=True, slots=True)
class Scope:
    """The top level of the flow, or one loop body."""

    owner: str | None
    order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttachedTool:
    node_id: str
    name: str


@dataclass(slots=True)
class Plan:
    nodes: dict[str, PlanNode]
    incoming: dict[str, list[GraphEdge]]
    outgoing: dict[str, list[GraphEdge]]
    tools: dict[str, list[AttachedTool]]
    top: Scope
    bodies: dict[str, Scope]
    start_id: str
    output_ids: tuple[str, ...]
    body_members: dict[str, frozenset[str]] = field(default_factory=dict)

    def terminal_nodes(self, loop_id: str) -> list[str]:
        """Body nodes nothing else in the body depends on (the default loop result)."""
        members = self.body_members.get(loop_id, frozenset())
        return [
            node_id
            for node_id in self.bodies[loop_id].order
            if not any(edge.target in members for edge in self.outgoing.get(node_id, []))
        ]


def config_of[ConfigT: BaseModel](node: PlanNode, kind: type[ConfigT]) -> ConfigT:
    """A node's configuration as the type its node type guarantees."""
    if not isinstance(node.config, kind):
        raise TypeError(f"node {node.id!r} does not have a {kind.__name__}")
    return node.config


def _position_key(node: GraphNode) -> tuple[float, float, str]:
    return (round(node.position.x, 1), round(node.position.y, 1), node.id)


def _toposort(
    members: set[str], nodes: dict[str, GraphNode], incoming: dict[str, list[GraphEdge]]
) -> tuple[str, ...]:
    indegree = {
        node_id: sum(1 for edge in incoming.get(node_id, []) if edge.source in members)
        for node_id in members
    }
    successors: dict[str, list[str]] = defaultdict(list)
    for node_id in members:
        for edge in incoming.get(node_id, []):
            if edge.source in members:
                successors[edge.source].append(node_id)
    ready = [(_position_key(nodes[n]), n) for n, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, current = heapq.heappop(ready)
        order.append(current)
        for nxt in successors[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, (_position_key(nodes[nxt]), nxt))
    return tuple(order)


def build_plan(doc: GraphDocument, ctx: ValidationContext | None = None) -> Plan:
    issues = validate_graph(doc, ctx)
    if has_errors(issues):
        raise InvalidGraphError([issue for issue in issues if issue.severity == "error"])

    nodes = {node.id: node for node in doc.nodes}
    tool_edges = [e for e in doc.edges if e.source_handle == "tool" and e.target_handle == "tools"]
    attached = {edge.source for edge in tool_edges}
    data_edges = [edge for edge in doc.edges if edge not in tool_edges]

    incoming: dict[str, list[GraphEdge]] = defaultdict(list)
    outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in data_edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    plan_nodes: dict[str, PlanNode] = {}
    for node in doc.nodes:
        spec = NODE_SPECS[node.type]
        if not spec.executable:
            continue
        plan_nodes[node.id] = PlanNode(
            node=node,
            spec=spec,
            config=parse_config(node),
            settings=parse_settings(node),
            label=display_label(node),
        )

    tools: dict[str, list[AttachedTool]] = defaultdict(list)
    for edge in sorted(tool_edges, key=lambda e: _position_key(nodes[e.source])):
        config = config_of(plan_nodes[edge.source], ToolFields)
        tools[edge.target].append(AttachedTool(edge.source, tool_name(nodes[edge.source], config)))

    # Loop bodies: everything reachable from a loop's body handle.
    full_bodies: dict[str, set[str]] = {}
    for loop_id, plan_node in plan_nodes.items():
        if plan_node.type != "loop":
            continue
        frontier = [edge.target for edge in outgoing[loop_id] if edge.source_handle == "body"]
        body: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in body:
                continue
            body.add(current)
            frontier.extend(edge.target for edge in outgoing.get(current, []))
        full_bodies[loop_id] = body

    def innermost(node_id: str) -> str | None:
        owners = [loop_id for loop_id, body in full_bodies.items() if node_id in body]
        # The innermost loop is the one whose body is smallest.
        return min(owners, key=lambda loop_id: len(full_bodies[loop_id])) if owners else None

    scoped: dict[str | None, set[str]] = defaultdict(set)
    for node_id in plan_nodes:
        if node_id in attached:
            continue
        scoped[innermost(node_id)].add(node_id)

    top = Scope(None, _toposort(scoped[None], nodes, incoming))
    bodies = {
        loop_id: Scope(loop_id, _toposort(scoped.get(loop_id, set()), nodes, incoming))
        for loop_id in full_bodies
    }
    start_id = next(node_id for node_id in top.order if plan_nodes[node_id].type == "start")
    output_ids = tuple(node_id for node_id in top.order if plan_nodes[node_id].type == "output")
    return Plan(
        nodes=plan_nodes,
        incoming=dict(incoming),
        outgoing=dict(outgoing),
        tools=dict(tools),
        top=top,
        bodies=bodies,
        start_id=start_id,
        output_ids=output_ids,
        body_members={loop_id: frozenset(body) for loop_id, body in full_bodies.items()},
    )
