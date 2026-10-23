from __future__ import annotations

from typing import Any

from agentstudio.schemas.common import ApiModel


class TemplateOut(ApiModel):
    slug: str
    name: str
    description: str
    category: str
    tags: list[str]
    node_types: list[str]
    node_count: int
    inputs: list[dict[str, Any]]
    sample: dict[str, Any]
    requires_knowledge: list[str]
    graph: dict[str, Any]


class ModelOut(ApiModel):
    ref: str
    provider: str
    model: str
    label: str
    offline: bool
    price_input: float
    price_output: float
    simulated: bool


class LimitsOut(ApiModel):
    max_nodes: int
    max_edges: int
    max_loop_items: int
    max_agent_iterations: int
    run_timeout_s: int
    max_document_kb: int
    max_run_wait_s: int


class SystemInfo(ApiModel):
    product_name: str
    version: str
    default_model: str
    providers: list[str]
    offline_only: bool
    allow_signup: bool
    needs_setup: bool
    queue_backend: str
    public_api_url: str
    sandbox_url: str
    limits: LimitsOut
