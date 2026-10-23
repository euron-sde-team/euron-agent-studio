"""`make demo`: accounts, a workspace with every template, knowledge bases and real runs.

Everything goes through the real services: templates are installed by the flow service
(which creates their knowledge bases from the bundled documents), flows are published,
webhook deliveries are genuinely signed and verified, runs are executed by the engine with
the offline model, and approvals are decided by the people who would decide them. The only
liberty taken is time: runs are spread over the past two weeks (their timestamps are moved
back) so the dashboard has a shape on a brand-new stack. Re-running is safe: an existing
demo workspace is left as it is.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import orjson
from sqlalchemy import select, update

from agentstudio.core.config import Settings
from agentstudio.core.crypto import sign_webhook, webhook_context
from agentstudio.core.logging import get_logger
from agentstudio.core.security import hash_password
from agentstudio.demo.data import PEOPLE, SCENARIOS, SECOND_WORKSPACE, WORKSPACE, Scenario
from agentstudio.engine.graph import GraphDocument
from agentstudio.integrations.queue import InlineQueue
from agentstudio.models import ApiKey, Approval, Flow, Run, RunStep, User, Workspace
from agentstudio.models.enums import ApprovalStatus, Role, RunTrigger
from agentstudio.repositories.flows import FlowRepository
from agentstudio.repositories.users import UserRepository
from agentstudio.repositories.workspaces import WorkspaceRepository
from agentstudio.schemas.flows import FlowCreate
from agentstudio.services.api_keys import ApiKeyService
from agentstudio.services.approvals import ApprovalService
from agentstudio.services.cache import dashboard_key
from agentstudio.services.container import Container, build_container
from agentstudio.services.flows import FlowService
from agentstudio.services.principal import Principal
from agentstudio.services.runs import RunExecution, RunService
from agentstudio.services.secrets import SecretService
from agentstudio.services.webhooks import WebhookService
from agentstudio.services.workspaces import WorkspaceService
from agentstudio.templates import TEMPLATES

log = get_logger("agentstudio.demo")

FLOW_NAMES = {
    "support-triage": "Support ticket triage",
    "invoice-extraction": "Invoice data extraction",
    "research-brief": "Research brief",
    "lead-qualification": "Inbound lead qualification",
    "meeting-actions": "Meeting notes to tasks",
    "policy-assistant": "HR policy assistant",
}


class Demo:
    def __init__(self, container: Container, password: str) -> None:
        self.c = container
        self.password = password
        self.users: dict[str, User] = {}
        self.workspace: Workspace | None = None
        self.flows: dict[str, uuid.UUID] = {}
        self.api_key: ApiKey | None = None
        self.targets: dict[uuid.UUID, datetime] = {}

    # Setup ------------------------------------------------------------------------------

    async def people(self) -> None:
        async with self.c.db.session() as session:
            repo = UserRepository(session)
            for person in PEOPLE:
                user = await repo.by_email(person.email)
                if user is None:
                    user = await repo.add(
                        User(
                            email=person.email,
                            name=person.name,
                            password_hash=await anyio.to_thread.run_sync(
                                hash_password, self.password
                            ),
                            is_admin=person.admin,
                        )
                    )
                self.users[person.email] = user
            await session.commit()

    def principal(self, email: str) -> Principal:
        return Principal(user=self.users[email])

    async def workspaces(self) -> bool:
        """Create the demo workspaces. False when the main one already has flows."""
        owner = self.principal(PEOPLE[0].email)
        async with self.c.db.session() as session:
            repo = WorkspaceRepository(session)
            existing = await repo.by_slug("northwind-operations")
            if existing is not None:
                flows, _ = await FlowRepository(session).page(existing.id, limit=1, offset=0)
                if flows:
                    self.workspace = existing
                    return False
            service = WorkspaceService(self.c, session)
            workspace = existing or await service.create(owner, *WORKSPACE)
            for person in PEOPLE[1:]:
                if await repo.membership(workspace.id, self.users[person.email].id) is None:
                    await repo.add_member(
                        workspace.id, self.users[person.email].id, Role(person.role)
                    )
            await session.commit()
            self.workspace = workspace
            leo = self.principal("leo.chen@northwind.example")
            if await repo.by_slug("leo-s-experiments") is None:
                lab = await service.create(leo, *SECOND_WORKSPACE)
                await repo.add_member(lab.id, self.users[PEOPLE[0].email].id, Role.VIEWER)
                await session.commit()
                await FlowService(self.c, session).create(
                    lab,
                    leo,
                    FlowCreate(name="Scratchpad", description="A blank flow to try ideas in."),
                )
        return True

    def require_workspace(self) -> Workspace:
        if self.workspace is None:
            raise RuntimeError("the demo workspace was not created")
        return self.workspace

    async def flows_and_settings(self) -> None:
        workspace = self.require_workspace()
        leo = self.principal("leo.chen@northwind.example")
        ava = self.principal(PEOPLE[0].email)
        async with self.c.db.session() as session:
            service = FlowService(self.c, session)
            for template in TEMPLATES:
                flow = await service.create(
                    workspace,
                    leo,
                    FlowCreate(name=FLOW_NAMES[template.slug], template=template.slug),
                )
                self.flows[template.slug] = flow.id
                await service.publish(
                    workspace, leo, flow.id, "First version from the template gallery."
                )
            await SecretService(self.c, session).create(
                workspace,
                ava,
                "CRM_TOKEN",
                "crm-demo-" + uuid.uuid4().hex[:20],
                "Token for the CRM API.",
            )
            # Version 2 of the triage flow authenticates its CRM lookup with the secret.
            support = await service.get(workspace.id, self.flows["support-triage"])
            graph = GraphDocument.model_validate(support.graph).model_dump(mode="json")
            for node in graph["nodes"]:
                if node["id"] == "lookup_customer":
                    node["config"]["headers"] = [
                        {"key": "Authorization", "value": "Bearer {{secrets.CRM_TOKEN}}"}
                    ]
            await service.save_draft(workspace, leo, support.id, graph, support.draft_revision)
            await service.publish(
                workspace, ava, support.id, "Authenticate CRM lookups with the CRM_TOKEN secret."
            )
            await service.enable_webhook(workspace, ava, support.id)
            # The research flow carries unpublished edits, as a flow someone is working on does.
            research = await service.get(workspace.id, self.flows["research-brief"])
            draft = GraphDocument.model_validate(research.graph).model_dump(mode="json")
            for node in draft["nodes"]:
                if node["id"] == "compose":
                    node["config"]["system"] += " Lead with the answer, then the evidence."
            await service.save_draft(workspace, leo, research.id, draft, research.draft_revision)
            key, _ = await ApiKeyService(self.c, session).create(
                workspace, ava, "AP automation (invoices and leads)", "editor", 365
            )
            await ApiKeyService(self.c, session).create(workspace, ava, "BI export", "viewer", None)
            self.api_key = key

    # Runs -------------------------------------------------------------------------------

    async def settle(self) -> None:
        queue = self.c.queue
        if isinstance(queue, InlineQueue):
            await queue.drain()

    async def play(self, scenario: Scenario) -> uuid.UUID:
        workspace = self.require_workspace()
        flow_id = self.flows[scenario.template]
        if scenario.trigger == "webhook":
            run_id = await self.webhook(flow_id, scenario.inputs)
        else:
            principal = (
                Principal(api_key=self.api_key)
                if scenario.trigger == "api"
                else self.principal(scenario.actor)
            )
            trigger = RunTrigger.API if scenario.trigger == "api" else RunTrigger.MANUAL
            async with self.c.db.session() as session:
                run = await RunService(self.c, session).start(
                    workspace,
                    principal,
                    flow_id,
                    scenario.inputs,
                    "draft" if scenario.version == "draft" else "published",
                    trigger=trigger,
                )
                run_id = run.id
        await self.settle()
        if scenario.decision or scenario.cancel:
            await self.decide(run_id, scenario)
        self.targets[run_id] = self.when(scenario.days_ago)
        return run_id

    async def webhook(self, flow_id: uuid.UUID, inputs: dict[str, Any]) -> uuid.UUID:
        async with self.c.db.session() as session:
            flow = await session.get(Flow, flow_id)
            if flow is None or flow.webhook_secret is None or not flow.webhook_id:
                raise RuntimeError("the triage flow has no webhook")
            secret = self.c.cipher.decrypt(flow.webhook_secret, context=webhook_context(flow.id))
            body = orjson.dumps(inputs)
            signature = sign_webhook(secret, int(time.time()), body)
            run = await WebhookService(self.c, session).deliver(flow.webhook_id, signature, body)
            return run.id

    async def decide(self, run_id: uuid.UUID, scenario: Scenario) -> None:
        workspace = self.require_workspace()
        async with self.c.db.session() as session:
            result = await session.execute(
                select(Approval).where(
                    Approval.run_id == run_id, Approval.status == ApprovalStatus.PENDING
                )
            )
            pending = result.scalars().first()
            if scenario.cancel:
                await RunService(self.c, session).cancel(
                    workspace, self.principal(scenario.actor), run_id
                )
                return
            if pending is None:
                log.warning("demo_expected_an_approval", run_id=str(run_id))
                return
            decider = self.users[scenario.decider]
            await ApprovalService(self.c, session).decide(
                workspace,
                Principal(user=decider),
                decider,
                pending.id,
                approve=scenario.decision == "approve",
                comment=scenario.comment,
            )
        await self.settle()

    @staticmethod
    def when(days_ago: float) -> datetime:
        """The moment a run happened: older runs land in working hours (09:00 to 17:59 UTC)."""
        moment = datetime.now(UTC) - timedelta(days=days_ago)
        if days_ago >= 1:
            hour = 9 + int((days_ago % 1) * 9)
            moment = moment.replace(hour=hour, minute=int(days_ago * 100) % 60)
        return moment

    async def backdate(self) -> None:
        """Move each run (and its steps and approval) back to its place in the last two weeks."""
        async with self.c.db.session() as session:
            for run_id, target in self.targets.items():
                run = await session.get(Run, run_id)
                if run is None:
                    continue
                shift = run.created_at - target
                if shift <= timedelta(0):
                    continue
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        created_at=Run.created_at - shift,
                        started_at=Run.started_at - shift,
                        finished_at=Run.finished_at - shift,
                    )
                )
                await session.execute(
                    update(RunStep)
                    .where(RunStep.run_id == run_id)
                    .values(
                        started_at=RunStep.started_at - shift,
                        finished_at=RunStep.finished_at - shift,
                    )
                )
                await session.execute(
                    update(Approval)
                    .where(Approval.run_id == run_id)
                    .values(
                        created_at=Approval.created_at - shift,
                        decided_at=Approval.decided_at - shift,
                        expires_at=Approval.expires_at - shift,
                    )
                )
            for flow_id in self.flows.values():
                latest = await session.execute(
                    select(Run.created_at, Run.status)
                    .where(Run.flow_id == flow_id)
                    .order_by(Run.created_at.desc())
                    .limit(1)
                )
                row = latest.first()
                if row is not None:
                    await session.execute(
                        update(Flow)
                        .where(Flow.id == flow_id)
                        .values(
                            last_run_at=row[0], last_run_status=row[1], updated_at=Flow.updated_at
                        )
                    )
            await session.commit()
        await self.c.redis.delete(dashboard_key(self.require_workspace().id))


async def run(settings: Settings, password: str) -> None:
    # Runs execute here, synchronously, with no pacing delay: the seed waits for each one.
    local = settings.model_copy(
        update={"queue_backend": "inline", "offline_delay_ms_per_100_tokens": 0}
    )
    container = build_container(local, application_name="agentstudio-demo")
    if not isinstance(container.queue, InlineQueue):
        raise RuntimeError("the demo seed runs flows in process")
    container.queue.bind(RunExecution(container).execute)
    demo = Demo(container, password)
    try:
        await demo.people()
        if not await demo.workspaces():
            print("The demo workspace already exists; nothing to do.")
        else:
            await demo.flows_and_settings()
            for scenario in sorted(SCENARIOS, key=lambda s: -s.days_ago):
                await demo.play(scenario)
            await demo.backdate()
            print(f"Seeded {len(demo.flows)} flows and {len(demo.targets)} runs.")
    finally:
        await container.close()
    web = settings.web_url.rstrip("/")
    print("")
    print(f"  Open {web} and sign in as:")
    for person in PEOPLE:
        print(f"    {person.email:<34} {person.role}")
