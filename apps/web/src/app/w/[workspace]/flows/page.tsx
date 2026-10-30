"use client";

import { Plus, Search, Webhook, Workflow as WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useDeferredValue, useState } from "react";

import { NewFlowDialog } from "@/components/flows/new-flow-dialog";
import { NodeIcon } from "@/components/node-icon";
import { StatusDot } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { Input, NativeSelect } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tooltip } from "@/components/ui/tooltip";
import { formatPercent, formatRelative } from "@/lib/format";
import { canEdit, useCurrentWorkspace, useFlows, useTags } from "@/lib/queries";
import type { FlowSummary } from "@/lib/types";

function SuccessRate({ flow }: { flow: FlowSummary }) {
  if (!flow.runs_7d) return <span className="text-subtle">No runs</span>;
  const rate = flow.success_rate_7d;
  return (
    <Tooltip content={`${flow.runs_7d} runs in the last 7 days`}>
      <span className="inline-flex items-center gap-2">
        <span className="bg-muted h-1.5 w-14 overflow-hidden rounded-full">
          <span
            className="bg-success block h-full rounded-full"
            style={{ width: `${(rate ?? 0) * 100}%` }}
          />
        </span>
        <span className="tabular-nums">{rate === null ? "-" : formatPercent(rate)}</span>
        <span className="text-subtle tabular-nums">({flow.runs_7d})</span>
      </span>
    </Tooltip>
  );
}

function FlowsList() {
  const { workspace } = useParams<{ workspace: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const current = useCurrentWorkspace(workspace);
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [published, setPublished] = useState<"" | "true" | "false">("");
  const deferred = useDeferredValue(search);
  const flows = useFlows(workspace, {
    q: deferred || undefined,
    tag: tag || undefined,
    published: published || undefined,
  });
  const tags = useTags(workspace);
  const editable = canEdit(current?.role);
  const creating = params.get("new") === "1";
  const setCreating = (open: boolean) =>
    router.replace(open ? `/w/${workspace}/flows?new=1` : `/w/${workspace}/flows`, {
      scroll: false,
    });
  const items = flows.data?.items;

  return (
    <PageBody>
      <PageHeader
        title="Flows"
        description="Agent workflows in this workspace. Open one to edit it on the canvas."
        actions={
          editable ? (
            <Button onClick={() => setCreating(true)} data-testid="new-flow">
              <Plus /> New flow
            </Button>
          ) : null
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <Search
            className="text-subtle pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search flows"
            className="pl-9"
            aria-label="Search flows"
          />
        </div>
        <NativeSelect
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          className="w-40"
          aria-label="Filter by tag"
        >
          <option value="">All tags</option>
          {(tags.data ?? []).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          value={published}
          onChange={(e) => setPublished(e.target.value as "" | "true" | "false")}
          className="w-40"
          aria-label="Filter by state"
        >
          <option value="">Any state</option>
          <option value="true">Published</option>
          <option value="false">Draft only</option>
        </NativeSelect>
        {flows.data ? (
          <span className="text-muted-foreground ml-auto text-[12.5px]">
            {flows.data.total} flow{flows.data.total === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
      {flows.error ? <ErrorNotice message={flows.error.message} /> : null}
      {!items ? (
        <Skeleton className="h-80" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<WorkflowIcon />}
            title={search || tag || published ? "No flow matches" : "No flows yet"}
            description="Start from a template, import an exported flow, or build one on the canvas."
            action={
              editable ? (
                <Button onClick={() => setCreating(true)}>
                  <Plus /> New flow
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[48rem] text-[13px]">
              <thead className="border-border bg-muted/50 text-subtle border-b text-left text-[11.5px] tracking-wide uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Flow</th>
                  <th className="px-3 py-2.5 font-medium">Steps</th>
                  <th className="px-3 py-2.5 font-medium">Version</th>
                  <th className="px-3 py-2.5 font-medium">Last run</th>
                  <th className="px-3 py-2.5 font-medium">7-day success</th>
                  <th className="px-4 py-2.5 font-medium">Edited</th>
                </tr>
              </thead>
              <tbody className="divide-border divide-y">
                {items.map((flow) => (
                  <tr key={flow.id} className="hover:bg-muted/40 transition-colors">
                    <td className="max-w-[24rem] px-4 py-3">
                      <Link
                        href={`/w/${workspace}/flows/${flow.id}`}
                        className="hover:text-primary flex items-center gap-1.5 font-medium"
                        data-testid="flow-link"
                      >
                        {flow.name}
                        {flow.webhook_enabled ? (
                          <Webhook className="text-subtle size-3.5" aria-label="Webhook enabled" />
                        ) : null}
                      </Link>
                      <span className="text-muted-foreground mt-0.5 block truncate text-[12px]">
                        {flow.description || "No description"}
                      </span>
                      {flow.tags.length ? (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {flow.tags.map((t) => (
                            <Badge key={t} tone="outline">
                              {t}
                            </Badge>
                          ))}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3">
                      <span className="flex items-center gap-1">
                        {flow.node_types
                          .filter((t) => t !== "start" && t !== "output" && t !== "note")
                          .slice(0, 5)
                          .map((type) => (
                            <NodeIcon
                              key={type}
                              type={type}
                              className="size-6 rounded-md [&_svg]:size-3.5"
                            />
                          ))}
                        <span className="text-muted-foreground ml-1 tabular-nums">
                          {flow.node_count}
                        </span>
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {flow.published_version ? (
                        <Badge tone="success">v{flow.published_version} live</Badge>
                      ) : (
                        <Badge tone="outline">Draft</Badge>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {flow.last_run_at && flow.last_run_status ? (
                        <span className="text-muted-foreground flex items-center gap-2">
                          <StatusDot status={flow.last_run_status} />
                          {formatRelative(flow.last_run_at)}
                        </span>
                      ) : (
                        <span className="text-subtle">Never</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <SuccessRate flow={flow} />
                    </td>
                    <td className="text-muted-foreground px-4 py-3">
                      {formatRelative(flow.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {editable ? (
        <NewFlowDialog workspace={workspace} open={creating} onOpenChange={setCreating} />
      ) : null}
    </PageBody>
  );
}

export default function FlowsPage() {
  return (
    <Suspense fallback={null}>
      <FlowsList />
    </Suspense>
  );
}
