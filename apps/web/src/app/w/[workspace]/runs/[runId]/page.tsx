"use client";

import { ArrowLeft, Ban, Pencil, RotateCw } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { StepDetail } from "@/components/editor/inspector";
import { GraphView } from "@/components/flows/graph-view";
import { JsonView } from "@/components/json-view";
import { ApprovalCard } from "@/components/runs/approval-card";
import { Timeline } from "@/components/runs/timeline";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody } from "@/components/ui/page";
import {
  formatCost,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatRelative,
} from "@/lib/format";
import { describeTrigger } from "@/lib/describe";
import { outputHandles } from "@/lib/nodes";
import { canEdit, useCurrentWorkspace, useRun, useRunActions } from "@/lib/queries";
import { fromStep, mergeSteps } from "@/lib/runs";
import { nodeStatuses } from "@/lib/trace";
import { isFinal, useRunStream } from "@/lib/use-run-stream";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-subtle text-[11.5px] font-medium tracking-wide uppercase">{label}</p>
      <p className="mt-0.5 text-[17px] font-semibold tracking-tight tabular-nums">{value}</p>
      {hint ? <p className="text-muted-foreground text-[11.5px]">{hint}</p> : null}
    </div>
  );
}

export default function RunPage() {
  const { workspace, runId } = useParams<{ workspace: string; runId: string }>();
  const router = useRouter();
  const current = useCurrentWorkspace(workspace);
  const run = useRun(workspace, runId);
  const actions = useRunActions(workspace);
  const [generation, setGeneration] = useState(0);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const data = run.data;
  const live = data ? !isFinal(data.status) : false;
  const trace = useRunStream(workspace, live ? runId : null, generation);
  const [now] = useState(() => Date.now());

  const steps = useMemo(
    () => mergeSteps((data?.steps ?? []).map(fromStep), live ? trace.steps : []),
    [data?.steps, trace.steps, live],
  );
  const statuses = useMemo(() => nodeStatuses(steps), [steps]);
  const fired = useMemo(() => {
    const handles = new Map<string, Set<string>>();
    for (const s of steps) {
      if (s.status !== "succeeded") continue;
      const set = handles.get(s.nodeId) ?? new Set<string>();
      for (const h of s.handles.length
        ? s.handles
        : outputHandles({ type: s.nodeType, config: {} }))
        set.add(h);
      handles.set(s.nodeId, set);
    }
    return handles;
  }, [steps]);

  if (run.error) {
    return (
      <EmptyState
        className="h-full"
        title="Run not found"
        description={run.error.message}
        action={
          <Button asChild variant="secondary">
            <Link href={`/w/${workspace}/runs`}>Back to runs</Link>
          </Button>
        }
      />
    );
  }
  if (!data) {
    return (
      <PageBody>
        <Skeleton className="h-16" />
        <Skeleton className="mt-4 h-96" />
      </PageBody>
    );
  }

  const status = live && trace.status !== "queued" ? trace.status : data.status;
  const editable = canEdit(current?.role);
  const failed = steps.find((s) => s.status === "failed");
  const selected =
    steps.find((s) => s.key === selectedKey) ??
    failed ??
    steps.filter((s) => s.status !== "skipped").at(-1);
  const pendingApprovals = data.approvals.filter((a) => a.status === "pending");
  const decided = data.approvals.filter((a) => a.status !== "pending");
  const promptTokens = Math.max(data.prompt_tokens, trace.promptTokens);
  const completionTokens = Math.max(data.completion_tokens, trace.completionTokens);
  const cost = Math.max(data.cost_usd, trace.costUsd);

  return (
    <PageBody className="max-w-7xl">
      <header className="flex flex-wrap items-start gap-3 pb-5">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back to runs">
          <Link href={`/w/${workspace}/runs`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1 basis-64">
          <h1 className="flex flex-wrap items-center gap-2 text-[22px] font-semibold tracking-tight">
            {data.flow_name}
            <Badge tone="outline">{data.version_label}</Badge>
            <StatusBadge status={status} />
          </h1>
          <p className="text-muted-foreground mt-1 text-[13px]">
            {describeTrigger(data)} &middot; {formatDateTime(data.created_at)} (
            {formatRelative(data.created_at)})
            {data.rerun_of_id ? (
              <>
                {" "}
                &middot;{" "}
                <Link
                  href={`/w/${workspace}/runs/${data.rerun_of_id}`}
                  className="text-primary hover:underline"
                >
                  re-run of an earlier run
                </Link>
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="secondary" size="sm">
            <Link href={`/w/${workspace}/flows/${data.flow_id}`}>
              <Pencil /> Open flow
            </Link>
          </Button>
          {editable && !isFinal(status) ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={actions.cancel.isPending}
              onClick={async () => {
                try {
                  await actions.cancel.mutateAsync(runId);
                  setGeneration((g) => g + 1);
                  toast.success("Run cancelled");
                } catch (error) {
                  toast.error((error as Error).message);
                }
              }}
            >
              <Ban /> Cancel
            </Button>
          ) : null}
          {editable && isFinal(status) ? (
            <Button
              size="sm"
              disabled={actions.rerun.isPending}
              onClick={async () => {
                try {
                  const again = await actions.rerun.mutateAsync(runId);
                  router.push(`/w/${workspace}/runs/${again.id}`);
                } catch (error) {
                  toast.error((error as Error).message);
                }
              }}
              data-testid="rerun"
            >
              <RotateCw /> Run again
            </Button>
          ) : null}
        </div>
      </header>

      <Card className="mb-5">
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat
            label="Duration"
            value={
              data.duration_ms !== null
                ? formatDuration(data.duration_ms)
                : status === "waiting"
                  ? "Paused"
                  : live
                    ? "Running"
                    : "-"
            }
            hint={status === "waiting" ? "Waiting for a person" : undefined}
          />
          <Stat
            label="Steps"
            value={formatNumber(steps.filter((s) => s.status !== "skipped").length)}
            hint={`${steps.filter((s) => s.status === "skipped").length} skipped`}
          />
          <Stat
            label="Tokens"
            value={formatNumber(promptTokens + completionTokens)}
            hint={`${formatNumber(promptTokens)} in, ${formatNumber(completionTokens)} out`}
          />
          <Stat
            label="Cost"
            value={formatCost(cost)}
            hint={data.cost_simulated ? "Simulated (offline model)" : "At configured prices"}
          />
        </CardContent>
      </Card>

      {data.error ? (
        <ErrorNotice
          className="mb-5"
          message={`${data.error.node_id ? `${data.error.node_id}: ` : ""}${data.error.message} (${data.error.code})`}
        />
      ) : null}

      {pendingApprovals.length ? (
        <div className="mb-5 space-y-3">
          {pendingApprovals.map((approval) => (
            <ApprovalCard
              key={approval.id}
              workspace={workspace}
              approval={approval}
              canDecide={editable}
              showRun={false}
              onDecided={() => setGeneration((g) => g + 1)}
            />
          ))}
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-5">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <CardTitle>The graph as it ran</CardTitle>
              <span className="text-muted-foreground text-[12px]">Click a node to inspect it</span>
            </CardHeader>
            <GraphView
              graph={data.graph}
              statuses={statuses}
              fired={fired}
              selectedNode={selected?.nodeId ?? null}
              onSelectNode={(nodeId) => {
                const match = steps.filter((s) => s.nodeId === nodeId).at(-1);
                if (match) setSelectedKey(match.key);
              }}
              className="bg-canvas border-border h-[26rem] border-t"
              controls
            />
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Timeline</CardTitle>
              <span className="text-muted-foreground text-[12px]">
                Parallel branches overlap; loops show one bar per item
              </span>
            </CardHeader>
            <Timeline
              steps={steps}
              runStart={data.started_at}
              now={now}
              selected={selected?.key ?? null}
              onSelect={setSelectedKey}
            />
          </Card>
        </div>
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>
                {selected
                  ? `${selected.label || selected.nodeId}${selected.iteration ? ` #${selected.iteration}` : ""}`
                  : "Step"}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {selected ? (
                <StepDetail step={selected} />
              ) : (
                <p className="text-muted-foreground text-[13px]">No step has run yet.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Inputs</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <JsonView value={data.inputs} label="Run inputs" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Outputs</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <JsonView
                value={data.outputs ?? trace.outputs}
                label="Run outputs"
                empty={
                  status === "failed"
                    ? "The run failed before producing outputs."
                    : "Outputs appear when the run finishes."
                }
              />
            </CardContent>
          </Card>
          {decided.length ? (
            <div className="space-y-3">
              {decided.map((approval) => (
                <ApprovalCard
                  key={approval.id}
                  workspace={workspace}
                  approval={approval}
                  canDecide={false}
                  showRun={false}
                />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </PageBody>
  );
}
