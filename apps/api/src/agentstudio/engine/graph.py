"""The graph document and the configuration of every node type.

A flow's draft, its versions, imports and exports are all one `GraphDocument`. The document
itself is lenient about node configuration (a node dropped on the canvas a second ago has an
empty prompt and must still save), so `config` and `settings` are plain dicts here. The
strict per-type models below are applied by validation, which reports problems as issues
instead of refusing the save, and by the engine, which only ever runs a valid graph.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NODE_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
IDENTIFIER_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$"
# Names the template language already uses; a node cannot take them.
RESERVED_IDS = frozenset({"inputs", "secrets", "item", "index", "args", "run", "loop"})

NodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN)]
Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
Template = Annotated[str, StringConstraints(max_length=20_000)]
ShortText = Annotated[str, StringConstraints(max_length=200)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------------------


class Position(_Model):
    x: float = 0.0
    y: float = 0.0


class Viewport(_Model):
    x: float = 0.0
    y: float = 0.0
    zoom: float = Field(default=1.0, gt=0, le=10)


class GraphNode(_Model):
    id: NodeId
    type: Annotated[str, StringConstraints(max_length=32)]
    position: Position = Field(default_factory=Position)
    label: Annotated[str, StringConstraints(max_length=120)] = ""
    config: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(_Model):
    id: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    source: NodeId
    source_handle: Annotated[str, StringConstraints(max_length=40)] = "out"
    target: NodeId
    target_handle: Annotated[str, StringConstraints(max_length=40)] = "in"


class GraphDocument(_Model):
    schema_version: Literal[1] = 1
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    viewport: Viewport | None = None

    def node(self, node_id: str) -> GraphNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)


# --------------------------------------------------------------------------------------
# Settings shared by every executable node
# --------------------------------------------------------------------------------------


class NodeSettings(_Model):
    timeout_s: float = Field(default=60.0, gt=0, le=600)
    retries: int = Field(default=0, ge=0, le=5)
    retry_backoff_s: float = Field(default=1.0, ge=0, le=60)
    continue_on_error: bool = False
    # Model nodes only: cache identical completions (temperature 0) for this long.
    cache_ttl_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)


# --------------------------------------------------------------------------------------
# Node configuration, one model per type
# --------------------------------------------------------------------------------------

FieldType = Literal["string", "number", "integer", "boolean", "object", "array"]


class InputField(_Model):
    name: Identifier
    type: FieldType = "string"
    description: ShortText = ""
    required: bool = True
    default: Any = None


class StartConfig(_Model):
    inputs: list[InputField] = Field(default_factory=list, max_length=30)
    sample: dict[str, Any] = Field(default_factory=dict)

    @field_validator("inputs")
    @classmethod
    def _unique(cls, value: list[InputField]) -> list[InputField]:
        names = [field.name for field in value]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique")
        return value


class JsonField(_Model):
    name: Identifier
    type: FieldType = "string"
    description: ShortText = ""
    enum: list[Annotated[str, StringConstraints(max_length=80)]] = Field(
        default_factory=list, max_length=30
    )
    # For arrays: the item type. Arrays of objects and objects use `fields`.
    items: Literal["string", "number", "integer", "boolean", "object"] = "string"
    fields: list[JsonField] = Field(default_factory=list, max_length=20)


class ModelConfig(_Model):
    model: Annotated[str, StringConstraints(min_length=1, max_length=120)] = "offline"
    system: Template = ""
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=32_000)
    output_mode: Literal["text", "json"] = "text"
    json_fields: list[JsonField] = Field(default_factory=list, max_length=40)


class LlmConfig(ModelConfig):
    prompt: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class AgentConfig(ModelConfig):
    task: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    max_iterations: int = Field(default=5, ge=1, le=50)


class ToolParam(_Model):
    name: Identifier
    type: Literal["string", "number", "integer", "boolean"] = "string"
    description: ShortText = ""
    required: bool = True


class ToolFields(_Model):
    """How a tool node presents itself to an Agent when attached to it."""

    tool_name: (
        Annotated[str, StringConstraints(pattern=r"^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$")] | None
    ) = None
    tool_description: Annotated[str, StringConstraints(max_length=1000)] = ""


class KeyValue(_Model):
    key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    value: Template = ""


class HttpConfig(ToolFields):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    headers: list[KeyValue] = Field(default_factory=list, max_length=30)
    query: list[KeyValue] = Field(default_factory=list, max_length=30)
    body_mode: Literal["none", "json", "text"] = "none"
    body: Template = ""
    expect: Literal["json", "text"] = "json"
    fail_on_status: bool = True
    parameters: list[ToolParam] = Field(default_factory=list, max_length=20)


class KnowledgeConfig(ToolFields):
    knowledge_base_id: uuid.UUID
    query: Template = ""
    top_k: int = Field(default=4, ge=1, le=20)


class CalculatorConfig(ToolFields):
    expression: Annotated[str, StringConstraints(max_length=2000)] = ""


class JsonTransformConfig(ToolFields):
    input: Template = ""
    expression: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


Operator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "is_empty",
    "is_not_empty",
    "in_list",
    "matches",
]


class Rule(_Model):
    left: Template
    operator: Operator = "equals"
    right: Template = ""


class Route(_Model):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,24}$")]
    label: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    match: Literal["all", "any"] = "all"
    rules: list[Rule] = Field(min_length=1, max_length=10)


class ConditionConfig(_Model):
    routes: list[Route] = Field(min_length=1, max_length=10)

    @field_validator("routes")
    @classmethod
    def _unique(cls, value: list[Route]) -> list[Route]:
        ids = [route.id for route in value]
        if len(ids) != len(set(ids)) or "else" in ids:
            raise ValueError("route ids must be unique and cannot be 'else'")
        return value


class LoopConfig(_Model):
    items: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    max_items: int = Field(default=50, ge=1, le=10_000)
    concurrency: int = Field(default=1, ge=1, le=8)
    collect: Template = ""
    continue_on_item_error: bool = False


class ApprovalConfig(_Model):
    title: Annotated[str, StringConstraints(min_length=1, max_length=2000)] = "Review required"
    message: Template = ""
    expires_after_hours: float | None = Field(default=None, gt=0, le=24 * 90)


class OutputField(_Model):
    name: Identifier
    value: Template = ""


class OutputConfig(_Model):
    fields: list[OutputField] = Field(min_length=1, max_length=30)

    @field_validator("fields")
    @classmethod
    def _unique(cls, value: list[OutputField]) -> list[OutputField]:
        names = [field.name for field in value]
        if len(names) != len(set(names)):
            raise ValueError("output names must be unique")
        return value


class NoteConfig(_Model):
    text: Annotated[str, StringConstraints(max_length=4000)] = ""
    color: Literal["yellow", "blue", "green", "pink", "gray"] = "yellow"


# --------------------------------------------------------------------------------------
# The catalog: handles, config models and defaults per type
# --------------------------------------------------------------------------------------


def _single_out(_: BaseModel) -> tuple[str, ...]:
    return ("out",)


def _tool_outs(_: BaseModel) -> tuple[str, ...]:
    return ("out", "tool")


def _no_outs(_: BaseModel) -> tuple[str, ...]:
    return ()


def _condition_outs(config: BaseModel) -> tuple[str, ...]:
    routes = config.routes if isinstance(config, ConditionConfig) else []
    return (*(f"route_{route.id}" for route in routes), "else")


def _approval_outs(_: BaseModel) -> tuple[str, ...]:
    return ("approved", "rejected")


def _loop_outs(_: BaseModel) -> tuple[str, ...]:
    return ("body", "done")


@dataclass(frozen=True, slots=True)
class NodeSpec:
    node_type: str
    label: str
    config_model: type[BaseModel]
    inputs: tuple[str, ...]
    outputs: Callable[[BaseModel], tuple[str, ...]]
    default_timeout_s: float
    executable: bool = True
    tool: bool = False
    uses_model: bool = False


NODE_SPECS: dict[str, NodeSpec] = {
    spec.node_type: spec
    for spec in (
        NodeSpec("start", "Start", StartConfig, (), _single_out, 10),
        NodeSpec("llm", "Prompt", LlmConfig, ("in",), _single_out, 60, uses_model=True),
        NodeSpec("agent", "Agent", AgentConfig, ("in", "tools"), _single_out, 180, uses_model=True),
        NodeSpec("http", "HTTP request", HttpConfig, ("in",), _tool_outs, 30, tool=True),
        NodeSpec(
            "knowledge", "Knowledge search", KnowledgeConfig, ("in",), _tool_outs, 20, tool=True
        ),
        NodeSpec("calculator", "Calculator", CalculatorConfig, ("in",), _tool_outs, 5, tool=True),
        NodeSpec(
            "json_transform",
            "JSON transform",
            JsonTransformConfig,
            ("in",),
            _tool_outs,
            5,
            tool=True,
        ),
        NodeSpec("condition", "Condition", ConditionConfig, ("in",), _condition_outs, 5),
        NodeSpec("loop", "Loop", LoopConfig, ("in",), _loop_outs, 600),
        NodeSpec("approval", "Human approval", ApprovalConfig, ("in",), _approval_outs, 10),
        NodeSpec("output", "Output", OutputConfig, ("in",), _no_outs, 5),
        NodeSpec("note", "Note", NoteConfig, (), _no_outs, 1, executable=False),
    )
}
TOOL_TYPES = frozenset(spec.node_type for spec in NODE_SPECS.values() if spec.tool)


def parse_config(node: GraphNode) -> BaseModel:
    """The node's typed configuration. Raises `pydantic.ValidationError` when invalid."""
    return NODE_SPECS[node.type].config_model.model_validate(node.config)


def parse_settings(node: GraphNode) -> NodeSettings:
    spec = NODE_SPECS.get(node.type)
    settings = dict(node.settings)
    if spec is not None:
        settings.setdefault("timeout_s", spec.default_timeout_s)
    return NodeSettings.model_validate(settings)


def display_label(node: GraphNode) -> str:
    if node.label:
        return node.label
    spec = NODE_SPECS.get(node.type)
    return spec.label if spec else node.type


def tool_name(node: GraphNode, config: ToolFields) -> str:
    return config.tool_name or node.id


def config_templates(node_type: str, config: BaseModel) -> list[tuple[str, str]]:
    """(field path, template) pairs for every templated setting of a node."""
    found: list[tuple[str, str]] = []
    if isinstance(config, LlmConfig):
        found += [("system", config.system), ("prompt", config.prompt)]
    elif isinstance(config, AgentConfig):
        found += [("system", config.system), ("task", config.task)]
    elif isinstance(config, HttpConfig):
        found.append(("url", config.url))
        found += [(f"headers.{i}.value", pair.value) for i, pair in enumerate(config.headers)]
        found += [(f"query.{i}.value", pair.value) for i, pair in enumerate(config.query)]
        if config.body_mode != "none":
            found.append(("body", config.body))
    elif isinstance(config, KnowledgeConfig):
        found.append(("query", config.query))
    elif isinstance(config, CalculatorConfig):
        found.append(("expression", config.expression))
    elif isinstance(config, JsonTransformConfig):
        found.append(("input", config.input))
    elif isinstance(config, ConditionConfig):
        for r, route in enumerate(config.routes):
            for i, rule in enumerate(route.rules):
                found += [
                    (f"routes.{r}.rules.{i}.left", rule.left),
                    (f"routes.{r}.rules.{i}.right", rule.right),
                ]
    elif isinstance(config, LoopConfig):
        found.append(("items", config.items))
    elif isinstance(config, ApprovalConfig):
        found += [("title", config.title), ("message", config.message)]
    elif isinstance(config, OutputConfig):
        found += [(f"fields.{i}.value", field.value) for i, field in enumerate(config.fields)]
    return [(path, template) for path, template in found if template]
