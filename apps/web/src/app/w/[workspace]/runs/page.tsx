"use client";

import { ChevronLeft, ChevronRight, History } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { NativeSelect } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { TRIGGER_LABELS } from "@/lib/describe";
import { formatCost, formatDuration, formatNumber, formatRelative } from "@/lib/format";
import { useFlows, useRuns, type RunFilters } from "@/lib/queries";
import type { RunStatus, RunTrigger } from "@/lib/types";

const PAGE = 25;
const STATUSES: RunStatus[] = ["queued", "running", "waiting", "succeeded", "failed", "cancelled"];
const TRIGGERS: { value: RunTrigger; label: string }[] = [
  { value: "manual", label: "By hand" },
  { value: "api", label: "API" },
  { value: "webhook", label: "Webhook" },
  { value: "rerun", label: "Re-run" },
];

export default function RunsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const router = useRouter();
  const [filters, setFilters] = useState<RunFilters>({});
  const [offset, setOffset] = useState(0);
  const runs = useRuns(workspace, filters, offset, PAGE);
  const flows = useFlows(workspace, {});
  const set = (patch: RunFilters) => {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
  };
  const items = runs.data?.items;
  const total = runs.data?.total ?? 0;

  return (
    <PageBody>
      <PageHeader
        title="Runs"
        description="Every run in this workspace, newest first, with its steps, tokens and cost."
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <NativeSelect
          value={filters.flow_id ?? ""}
          onChange={(e) => set({ flow_id: e.target.value || undefined })}
          className="w-56"
          aria-label="Filter by flow"
        >
          <option value="">All flows</option>
          {(flows.data?.items ?? []).map((flow) => (
            <option key={flow.id} value={flow.id}>
              {flow.name}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          value={filters.status ?? ""}
          onChange={(e) => set({ status: (e.target.value as RunStatus) || undefined })}
          className="w-44"
          aria-label="Filter by status"
        >
          <option value="">Any status</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status === "waiting"
                ? "Waiting for approval"
                : status[0]!.toUpperCase() + status.slice(1)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect
          value={filters.trigger ?? ""}
          onChange={(e) => set({ trigger: (e.target.value as RunTrigger) || undefined })}
          className="w-36"
          aria-label="Filter by trigger"
        >
          <option value="">Any trigger</option>
          {TRIGGERS.map((trigger) => (
            <option key={trigger.value} value={trigger.value}>
              {trigger.label}
            </option>
          ))}
        </NativeSelect>
        {runs.data ? (
          <span className="text-muted-foreground ml-auto text-[12.5px]">
            {formatNumber(total)} run{total === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
      {runs.error ? <ErrorNotice message={runs.error.message} /> : null}
      {!items ? (
        <Skeleton className="h-96" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<History />}
            title={Object.values(filters).some(Boolean) ? "No run matches" : "No runs yet"}
            description="Open a flow and press Run, or start one from the API or a webhook."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] text-[13px]">
              <thead className="border-border bg-muted/50 text-subtle border-b text-left text-[11.5px] tracking-wide uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 font-medium">Flow</th>
                  <th className="px-3 py-2.5 font-medium">Trigger</th>
                  <th className="px-3 py-2.5 font-medium">Started</th>
                  <th className="px-3 py-2.5 text-right font-medium">Duration</th>
                  <th className="px-3 py-2.5 text-right font-medium">Tokens</th>
                  <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-border divide-y">
                {items.map((run) => (
                  <tr
                    key={run.id}
                    className="hover:bg-muted/40 cursor-pointer transition-colors"
                    onClick={() => router.push(`/w/${workspace}/runs/${run.id}`)}
                  >
                    <td className="px-4 py-2.5">
                      <StatusBadge status={run.status} short />
                    </td>
                    <td className="max-w-[18rem] px-3 py-2.5">
                      <Link
                        href={`/w/${workspace}/runs/${run.id}`}
                        className="hover:text-primary font-medium"
                        onClick={(e) => e.stopPropagation()}
                        data-testid="run-link"
                      >
                        {run.flow_name}
                      </Link>{" "}
                      <Badge tone="outline">{run.version_label}</Badge>
                      {run.error ? (
                        <span className="text-danger mt-0.5 block truncate text-[12px]">
                          {run.error.message}
                        </span>
                      ) : null}
                    </td>
                    <td className="text-muted-foreground px-3 py-2.5">
                      <span className="block">{TRIGGER_LABELS[run.trigger] ?? run.trigger}</span>
                      {run.triggered_by && run.trigger !== "webhook" ? (
                        <span className="text-subtle block truncate text-[12px]">
                          {run.triggered_by}
                        </span>
                      ) : null}
                    </td>
                    <td className="text-muted-foreground px-3 py-2.5">
                      {formatRelative(run.created_at)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {formatDuration(run.duration_ms)}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {formatNumber(run.prompt_tokens + run.completion_tokens)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {formatCost(run.cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-border flex items-center justify-between border-t px-4 py-2.5">
            <span className="text-muted-foreground text-[12.5px]">
              {offset + 1} to {Math.min(offset + PAGE, total)} of {formatNumber(total)}
            </span>
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
              >
                <ChevronLeft /> Newer
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset((o) => o + PAGE)}
              >
                Older <ChevronRight />
              </Button>
            </div>
          </div>
        </Card>
      )}
    </PageBody>
  );
}
