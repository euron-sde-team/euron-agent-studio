"""The template gallery and the knowledge documents its templates ship with."""

from __future__ import annotations

import copy
import uuid
from importlib import resources
from typing import Any

from agentstudio.templates.catalog import KB_PLACEHOLDER, TEMPLATES, KnowledgeSpec, Template

__all__ = [
    "TEMPLATES",
    "KnowledgeSpec",
    "Template",
    "bind_knowledge",
    "get_template",
    "knowledge_documents",
    "knowledge_names",
]


def get_template(slug: str) -> Template | None:
    return next((template for template in TEMPLATES if template.slug == slug), None)


def knowledge_documents(spec: KnowledgeSpec) -> list[tuple[str, bytes]]:
    """(file name, bytes) for each document bundled with a template knowledge base."""
    folder = resources.files("agentstudio.templates").joinpath("knowledge", spec.slug)
    return sorted(
        (entry.name, entry.read_bytes())
        for entry in folder.iterdir()
        if entry.is_file() and entry.name.endswith(".md")
    )


def knowledge_names(graph: dict[str, Any]) -> list[str]:
    """Knowledge base names a template graph refers to through placeholders."""
    names: list[str] = []
    for node in graph.get("nodes", []):
        ref = (node.get("config") or {}).get("knowledge_base_id")
        if isinstance(ref, str) and ref.startswith(KB_PLACEHOLDER):
            name = ref[len(KB_PLACEHOLDER) :]
            if name not in names:
                names.append(name)
    return names


def bind_knowledge(graph: dict[str, Any], ids: dict[str, uuid.UUID]) -> dict[str, Any]:
    """A copy of the graph with each `kb:<name>` placeholder replaced by a real id."""
    bound = copy.deepcopy(graph)
    for node in bound.get("nodes", []):
        config = node.get("config") or {}
        ref = config.get("knowledge_base_id")
        if isinstance(ref, str) and ref.startswith(KB_PLACEHOLDER):
            found = ids.get(ref[len(KB_PLACEHOLDER) :])
            config["knowledge_base_id"] = str(found) if found else None
    return bound
