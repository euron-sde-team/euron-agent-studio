"""Flows: drafts with optimistic concurrency, validation, versions, import, export, webhooks."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import orjson
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from agentstudio.core.crypto import new_hook_id, new_webhook_secret, webhook_context
from agentstudio.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnprocessableError,
)
from agentstudio.engine.graph import GraphDocument
from agentstudio.engine.plan import InvalidGraphError, Plan, build_plan
from agentstudio.engine.validate import Issue, ValidationContext, has_errors, validate_graph
from agentstudio.export.python import ExportInfo, export_python, file_name
from agentstudio.models import Flow, FlowVersion, Workspace
from agentstudio.repositories.flows import FlowRepository, FlowStats
from agentstudio.repositories.knowledge import KnowledgeRepository
from agentstudio.repositories.secrets import SecretRepository
from agentstudio.repositories.users import UserRepository
from agentstudio.schemas.flows import FlowCreate, FlowDocument, FlowUpdate
from agentstudio.services import audit
from agentstudio.services.container import Container
from agentstudio.services.principal import Principal
from agentstudio.services.templates import TemplateService
from agentstudio.templates import bind_knowledge, knowledge_names

VersionRef = Literal["auto", "draft", "published"] | int


@dataclass(frozen=True, slots=True)
class FlowSummary:
    flow: Flow
    stats: FlowStats


@dataclass(frozen=True, slots=True)
class ResolvedGraph:
    document: GraphDocument
    version: int
    version_id: uuid.UUID | None


def issue_dict(issue: Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "node_id": issue.node_id,
        "edge_id": issue.edge_id,
        "field": issue.field,
    }


def blank_graph() -> dict[str, Any]:
    """A new flow: Start, then Output, already connected and valid."""
    return GraphDocument.model_validate(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "position": {"x": 0, "y": 120},
                    "config": {
                        "inputs": [
                            {
                                "name": "input",
                                "type": "string",
                                "description": "What the flow works on.",
                            }
                        ]
                    },
                },
                {
                    "id": "result",
                    "type": "output",
                    "position": {"x": 420, "y": 120},
                    "config": {"fields": [{"name": "result", "value": "{{inputs.input}}"}]},
                },
            ],
            "edges": [
                {
                    "id": "e_start_out_result_in",
                    "source": "start",
                    "source_handle": "out",
                    "target": "result",
                    "target_handle": "in",
                }
            ],
        }
    ).model_dump(mode="json")


def graph_hash(graph: dict[str, Any]) -> str:
    return hashlib.sha256(orjson.dumps(graph, option=orjson.OPT_SORT_KEYS)).hexdigest()


def node_types(graph: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for node in graph.get("nodes", []):
        kind = node.get("type")
        if isinstance(kind, str) and kind != "note" and kind not in seen:
            seen.append(kind)
    return seen


def executable_count(graph: dict[str, Any]) -> int:
    return sum(1 for node in graph.get("nodes", []) if node.get("type") != "note")


class FlowService:
    def __init__(self, container: Container, session: AsyncSession) -> None:
        self.c = container
        self.session = session
        self.flows = FlowRepository(session)

    # Documents --------------------------------------------------------------------------

    def parse_graph(self, raw: dict[str, Any]) -> GraphDocument:
        settings = self.c.settings
        if len(orjson.dumps(raw)) > settings.max_graph_kb * 1024:
            raise PayloadTooLargeError(f"Flows are limited to {settings.max_graph_kb} KB.")
        try:
            document = GraphDocument.model_validate(raw)
        except ValidationError as exc:
            details = [
                {
                    "loc": list(err.get("loc", ())),
                    "message": err.get("msg"),
                    "type": err.get("type"),
                }
                for err in exc.errors()
            ]
            raise UnprocessableError(
                "The flow document is malformed.", code="invalid_graph", details=details
            ) from exc
        # Hard caps protect storage; validation reports the softer limits as issues.
        if (
            len(document.nodes) > settings.max_nodes * 2
            or len(document.edges) > settings.max_edges * 2
        ):
            raise PayloadTooLargeError("This flow has far too many nodes or connections.")
        return document

    async def context(self, workspace_id: uuid.UUID) -> ValidationContext:
        settings = self.c.settings
        return ValidationContext(
            knowledge_base_ids=await KnowledgeRepository(self.session).ids(workspace_id),
            secret_names=await SecretRepository(self.session).names(workspace_id),
            model_available=self.c.models.available,
            max_nodes=settings.max_nodes,
            max_edges=settings.max_edges,
            max_loop_items=settings.max_loop_items,
            max_agent_iterations=settings.max_agent_iterations,
        )

    async def issues(self, workspace_id: uuid.UUID, document: GraphDocument) -> list[Issue]:
        return validate_graph(document, await self.context(workspace_id))

    async def plan(self, workspace_id: uuid.UUID, document: GraphDocument) -> Plan:
        try:
            return build_plan(document, await self.context(workspace_id))
        except InvalidGraphError as exc:
            raise UnprocessableError(
                "This flow has errors. Fix them in the editor first.",
                code="invalid_flow",
                details=[issue_dict(issue) for issue in exc.issues if isinstance(issue, Issue)],
            ) from exc

    # Reading ----------------------------------------------------------------------------

    async def get(self, workspace_id: uuid.UUID, flow_id: uuid.UUID) -> Flow:
        flow = await self.flows.get(workspace_id, flow_id)
        if flow is None:
            raise NotFoundError("Flow not found.")
        return flow

    async def page(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        search: str | None,
        tag: str | None,
        published: bool | None,
    ) -> tuple[list[FlowSummary], int]:
        flows, total = await self.flows.page(
            workspace_id, limit=limit, offset=offset, search=search, tag=tag, published=published
        )
        since = datetime.now(UTC) - timedelta(days=7)
        stats = await self.flows.stats(workspace_id, [flow.id for flow in flows], since)
        return [FlowSummary(flow, stats.get(flow.id, FlowStats())) for flow in flows], total

    async def summary(self, flow: Flow) -> FlowSummary:
        since = datetime.now(UTC) - timedelta(days=7)
        stats = await self.flows.stats(flow.workspace_id, [flow.id], since)
        return FlowSummary(flow, stats.get(flow.id, FlowStats()))

    async def tags(self, workspace_id: uuid.UUID) -> list[str]:
        return await self.flows.tags(workspace_id)

    async def resolve(self, flow: Flow, ref: VersionRef) -> ResolvedGraph:
        """The graph a run or an export uses: the draft, the published version, or `vN`."""
        if ref == "auto":
            ref = "published" if flow.published_version_id else "draft"
        if ref == "draft":
            return ResolvedGraph(self.parse_graph(flow.graph), 0, None)
        if ref == "published":
            if flow.published_version_id is None:
                raise ConflictError("This flow has no published version yet.", code="not_published")
            version = await self.flows.version_by_id(flow.workspace_id, flow.published_version_id)
        else:
            version = await self.flows.version(flow.id, int(ref))
        if version is None:
            raise NotFoundError("Version not found.")
        return ResolvedGraph(
            GraphDocument.model_validate(version.graph), version.version, version.id
        )

    # Writing ----------------------------------------------------------------------------

    async def create(self, workspace: Workspace, principal: Principal, body: FlowCreate) -> Flow:
        description = body.description
        tags = body.tags
        template_slug = None
        if body.template:
            templates = TemplateService(self.c, self.session)
            template = templates.get(body.template)
            graph = await templates.graph(workspace, principal, template)
            description = description or template.description
            tags = tags or list(template.tags)
            template_slug = template.slug
        else:
            graph = blank_graph()
        flow = await self.flows.add(
            Flow(
                workspace_id=workspace.id,
                name=body.name.strip(),
                description=description.strip(),
                tags=tags,
                graph=self.parse_graph(graph).model_dump(mode="json"),
                template_slug=template_slug,
                created_by=principal.user_id,
                draft_updated_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.created",
            target_type="flow",
            target_id=flow.id,
            details={"name": flow.name, "template": template_slug},
        )
        await self.session.commit()
        return flow

    async def import_document(
        self, workspace: Workspace, principal: Principal, document: FlowDocument
    ) -> Flow:
        graph = document.graph
        names = knowledge_names(graph)
        if names:
            repo = KnowledgeRepository(self.session)
            ids = {name: kb.id for name in names if (kb := await repo.by_name(workspace.id, name))}
            graph = bind_knowledge(graph, ids)
        parsed = self.parse_graph(graph)
        flow = await self.flows.add(
            Flow(
                workspace_id=workspace.id,
                name=document.name.strip(),
                description=document.description.strip(),
                tags=document.tags,
                graph=parsed.model_dump(mode="json"),
                created_by=principal.user_id,
                draft_updated_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.imported",
            target_type="flow",
            target_id=flow.id,
            details={"name": flow.name, "nodes": len(parsed.nodes)},
        )
        await self.session.commit()
        return flow

    async def update(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID, body: FlowUpdate
    ) -> Flow:
        flow = await self.get(workspace.id, flow_id)
        changed: dict[str, Any] = {}
        if body.name is not None and body.name.strip() != flow.name:
            flow.name = body.name.strip()
            changed["name"] = flow.name
        if body.description is not None and body.description.strip() != flow.description:
            flow.description = body.description.strip()
            changed["description"] = True
        if body.tags is not None and body.tags != flow.tags:
            flow.tags = body.tags
            changed["tags"] = body.tags
        if changed:
            flow.updated_at = datetime.now(UTC)
            await audit.record(
                self.session,
                workspace_id=workspace.id,
                principal=principal,
                action="flow.updated",
                target_type="flow",
                target_id=flow.id,
                details=changed,
            )
            await self.session.commit()
        return flow

    async def save_draft(
        self,
        workspace: Workspace,
        principal: Principal,
        flow_id: uuid.UUID,
        graph: dict[str, Any],
        base_revision: int,
    ) -> tuple[Flow, list[Issue]]:
        document = self.parse_graph(graph)
        flow = await self.flows.get_for_update(workspace.id, flow_id)
        if flow is None:
            raise NotFoundError("Flow not found.")
        if flow.draft_revision != base_revision:
            raise ConflictError(
                "This flow was changed somewhere else. Reload it to see the latest draft.",
                code="revision_conflict",
                details={"current_revision": flow.draft_revision},
            )
        now = datetime.now(UTC)
        flow.graph = document.model_dump(mode="json")
        flow.draft_revision += 1
        flow.draft_updated_at = now
        flow.draft_updated_by = principal.user_id
        flow.updated_at = now
        await self.session.commit()
        return flow, await self.issues(workspace.id, document)

    async def publish(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID, notes: str
    ) -> FlowVersion:
        flow = await self.flows.get_for_update(workspace.id, flow_id)
        if flow is None:
            raise NotFoundError("Flow not found.")
        document = self.parse_graph(flow.graph)
        issues = await self.issues(workspace.id, document)
        if has_errors(issues):
            raise UnprocessableError(
                "Fix the errors in this flow before publishing it.",
                code="invalid_flow",
                details=[issue_dict(issue) for issue in issues if issue.severity == "error"],
            )
        graph = document.model_dump(mode="json")
        version = await self.flows.add_version(
            FlowVersion(
                flow_id=flow.id,
                workspace_id=workspace.id,
                version=flow.latest_version + 1,
                graph=graph,
                graph_sha256=graph_hash(graph),
                notes=notes.strip(),
                created_by=principal.user_id,
            )
        )
        flow.latest_version = version.version
        flow.published_version_id = version.id
        flow.updated_at = datetime.now(UTC)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.published",
            target_type="flow",
            target_id=flow.id,
            details={"name": flow.name, "version": version.version},
        )
        await self.session.commit()
        return version

    async def versions(
        self, workspace_id: uuid.UUID, flow_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Flow, list[tuple[FlowVersion, str | None]], int]:
        flow = await self.get(workspace_id, flow_id)
        versions, total = await self.flows.versions(flow.id, limit=limit, offset=offset)
        names = await UserRepository(self.session).names(
            {v.created_by for v in versions if v.created_by}
        )
        return (
            flow,
            [(v, names.get(v.created_by) if v.created_by else None) for v in versions],
            total,
        )

    async def version(
        self, workspace_id: uuid.UUID, flow_id: uuid.UUID, number: int
    ) -> tuple[Flow, FlowVersion, str | None]:
        flow = await self.get(workspace_id, flow_id)
        version = await self.flows.version(flow.id, number)
        if version is None:
            raise NotFoundError("Version not found.")
        names = await UserRepository(self.session).names(
            {version.created_by} if version.created_by else set()
        )
        return flow, version, names.get(version.created_by) if version.created_by else None

    async def restore(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID, number: int
    ) -> Flow:
        _, version, _ = await self.version(workspace.id, flow_id, number)
        flow = await self.flows.get_for_update(workspace.id, flow_id)
        if flow is None:
            raise NotFoundError("Flow not found.")
        now = datetime.now(UTC)
        flow.graph = dict(version.graph)
        flow.draft_revision += 1
        flow.draft_updated_at = now
        flow.draft_updated_by = principal.user_id
        flow.updated_at = now
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.restored",
            target_type="flow",
            target_id=flow.id,
            details={"version": number},
        )
        await self.session.commit()
        return flow

    async def duplicate(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID
    ) -> Flow:
        source = await self.get(workspace.id, flow_id)
        copy = await self.flows.add(
            Flow(
                workspace_id=workspace.id,
                name=f"{source.name} (copy)"[:120],
                description=source.description,
                tags=list(source.tags),
                graph=dict(source.graph),
                template_slug=source.template_slug,
                created_by=principal.user_id,
                draft_updated_by=principal.user_id,
            )
        )
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.duplicated",
            target_type="flow",
            target_id=copy.id,
            details={"from": str(source.id), "name": copy.name},
        )
        await self.session.commit()
        return copy

    async def delete(self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID) -> None:
        flow = await self.get(workspace.id, flow_id)
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="flow.deleted",
            target_type="flow",
            target_id=flow.id,
            details={"name": flow.name},
        )
        await self.session.delete(flow)
        await self.session.commit()

    # Export -----------------------------------------------------------------------------

    async def export_document(
        self, workspace_id: uuid.UUID, flow_id: uuid.UUID, ref: VersionRef
    ) -> FlowDocument:
        flow = await self.get(workspace_id, flow_id)
        resolved = await self.resolve(flow, ref)
        return FlowDocument(
            name=flow.name,
            description=flow.description,
            tags=list(flow.tags),
            graph=resolved.document.model_dump(mode="json"),
            exported_at=datetime.now(UTC),
            source_version=resolved.version or None,
        )

    async def export_python(
        self, workspace: Workspace, flow_id: uuid.UUID, ref: VersionRef
    ) -> tuple[str, str]:
        flow = await self.get(workspace.id, flow_id)
        resolved = await self.resolve(flow, ref)
        plan = await self.plan(workspace.id, resolved.document)
        label = f"v{resolved.version}" if resolved.version else "draft"
        info = ExportInfo(flow.name, workspace.slug, label, self.c.settings.public_api_url)
        return file_name(flow.name), export_python(plan, info)

    # Webhooks ---------------------------------------------------------------------------

    def webhook_url(self, flow: Flow) -> str | None:
        if not flow.webhook_id:
            return None
        return f"{self.c.settings.public_api_url.rstrip('/')}/api/v1/hooks/{flow.webhook_id}"

    async def enable_webhook(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID
    ) -> tuple[Flow, str]:
        """Turn the webhook on with a fresh signing secret (rotating any previous one)."""
        flow = await self.get(workspace.id, flow_id)
        secret = new_webhook_secret()
        rotated = flow.webhook_secret is not None
        flow.webhook_id = flow.webhook_id or new_hook_id()
        flow.webhook_secret = self.c.cipher.encrypt(secret, context=webhook_context(flow.id))
        flow.webhook_enabled = True
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="webhook.rotated" if rotated else "webhook.enabled",
            target_type="flow",
            target_id=flow.id,
            details={"hook_id": flow.webhook_id},
        )
        await self.session.commit()
        return flow, secret

    async def disable_webhook(
        self, workspace: Workspace, principal: Principal, flow_id: uuid.UUID
    ) -> Flow:
        flow = await self.get(workspace.id, flow_id)
        flow.webhook_enabled = False
        flow.webhook_secret = None
        await audit.record(
            self.session,
            workspace_id=workspace.id,
            principal=principal,
            action="webhook.disabled",
            target_type="flow",
            target_id=flow.id,
        )
        await self.session.commit()
        return flow
