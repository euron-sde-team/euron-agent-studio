"""Turning service results into response models. Pure functions, no I/O."""

from __future__ import annotations

from agentstudio.engine.validate import Issue
from agentstudio.models import Flow, FlowVersion, RunStep
from agentstudio.providers.registry import ModelInfo
from agentstudio.schemas.approvals import ApprovalOut
from agentstudio.schemas.catalog import ModelOut, TemplateOut
from agentstudio.schemas.flows import FlowOut, FlowSummaryOut, IssueOut, VersionOut, WebhookOut
from agentstudio.schemas.runs import RunDetail, RunOut, StepOut
from agentstudio.services.approvals import ApprovalView
from agentstudio.services.flows import FlowSummary, executable_count, issue_dict, node_types
from agentstudio.services.views import RunDetailView, RunView
from agentstudio.templates import Template


def version_label(version: int) -> str:
    return f"v{version}" if version else "draft"


def run_out(view: RunView) -> RunOut:
    run = view.run
    return RunOut(
        id=run.id,
        flow_id=run.flow_id,
        flow_name=view.flow_name,
        version=run.version,
        version_label=version_label(run.version),
        status=run.status,
        trigger=run.trigger,
        inputs=run.inputs,
        outputs=run.outputs,
        error=run.error,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        cost_usd=float(run.cost_usd),
        cost_simulated=run.cost_simulated,
        step_count=run.step_count,
        triggered_by=view.triggered_by,
        rerun_of_id=run.rerun_of_id,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
    )


def step_out(step: RunStep) -> StepOut:
    return StepOut(
        id=step.id,
        node_id=step.node_id,
        node_type=step.node_type,
        label=step.label,
        iteration=step.iteration,
        seq=step.seq,
        status=step.status,
        attempt=step.attempt,
        input=step.input,
        output=step.output,
        error=step.error,
        events=step.events,
        handles=step.handles,
        model=step.model,
        prompt_tokens=step.prompt_tokens,
        completion_tokens=step.completion_tokens,
        cost_usd=float(step.cost_usd),
        cached=step.cached,
        continued=step.continued,
        started_at=step.started_at,
        finished_at=step.finished_at,
        latency_ms=step.latency_ms,
    )


def approval_out(view: ApprovalView) -> ApprovalOut:
    approval = view.approval
    return ApprovalOut(
        id=approval.id,
        run_id=approval.run_id,
        flow_id=approval.flow_id,
        flow_name=view.flow_name,
        node_id=approval.node_id,
        title=approval.title,
        message=approval.message,
        context=approval.context,
        status=approval.status,
        run_status=view.run_status,
        expires_at=approval.expires_at,
        decided_by_name=view.decided_by_name,
        decided_at=approval.decided_at,
        comment=approval.comment,
        created_at=approval.created_at,
    )


def run_detail(detail: RunDetailView) -> RunDetail:
    base = run_out(detail.view)
    flow_name = detail.view.flow_name
    return RunDetail(
        **base.model_dump(),
        graph=detail.graph,
        steps=[step_out(step) for step in detail.steps],
        approvals=[
            approval_out(ApprovalView(approval, flow_name, detail.view.run.status, name))
            for approval, name in detail.approvals
        ],
    )


def issues_out(issues: list[Issue]) -> list[IssueOut]:
    return [IssueOut.model_validate(issue_dict(issue)) for issue in issues]


def flow_summary(summary: FlowSummary) -> FlowSummaryOut:
    flow, stats = summary.flow, summary.stats
    finished = stats.succeeded + stats.failed
    return FlowSummaryOut(
        id=flow.id,
        name=flow.name,
        description=flow.description,
        tags=list(flow.tags),
        published_version=flow.latest_version if flow.published_version_id else None,
        latest_version=flow.latest_version,
        draft_revision=flow.draft_revision,
        node_count=executable_count(flow.graph),
        node_types=node_types(flow.graph),
        template_slug=flow.template_slug,
        webhook_enabled=flow.webhook_enabled,
        last_run_at=flow.last_run_at,
        last_run_status=flow.last_run_status,
        runs_7d=stats.runs,
        success_rate_7d=round(stats.succeeded / finished, 4) if finished else None,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


def webhook_out(flow: Flow, url: str | None, secret: str | None = None) -> WebhookOut:
    return WebhookOut(
        enabled=flow.webhook_enabled,
        hook_id=flow.webhook_id,
        url=url,
        secret=secret,
    )


def flow_out(summary: FlowSummary, issues: list[Issue], webhook_url: str | None) -> FlowOut:
    flow = summary.flow
    return FlowOut(
        **flow_summary(summary).model_dump(),
        graph=flow.graph,
        draft_updated_at=flow.draft_updated_at,
        issues=issues_out(issues),
        webhook=webhook_out(flow, webhook_url),
    )


def version_out(version: FlowVersion, creator: str | None, flow: Flow) -> VersionOut:
    return VersionOut(
        id=version.id,
        version=version.version,
        notes=version.notes,
        graph_sha256=version.graph_sha256,
        node_count=executable_count(version.graph),
        created_by_name=creator,
        created_at=version.created_at,
        published=version.id == flow.published_version_id,
    )


def template_out(template: Template) -> TemplateOut:
    start = next((n for n in template.graph["nodes"] if n["type"] == "start"), None)
    return TemplateOut(
        slug=template.slug,
        name=template.name,
        description=template.description,
        category=template.category,
        tags=list(template.tags),
        node_types=node_types(template.graph),
        node_count=executable_count(template.graph),
        inputs=list(start["config"].get("inputs", [])) if start else [],
        sample=dict(template.sample),
        requires_knowledge=[spec.name for spec in template.knowledge],
        graph=template.graph,
    )


def model_out(info: ModelInfo) -> ModelOut:
    return ModelOut(
        ref=info.ref,
        provider=info.provider,
        model=info.model,
        label=info.label,
        offline=info.offline,
        price_input=info.price_input,
        price_output=info.price_output,
        simulated=info.simulated,
    )
