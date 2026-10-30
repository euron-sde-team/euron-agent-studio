"use client";

import { ArrowUpRight, Ban, ChevronDown, ChevronUp, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { JsonView } from "@/components/json-view";
import { NodeIcon } from "@/components/node-icon";
import { StatusBadge, StatusDot } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { formatCost, formatDuration, formatNumber } from "@/lib/format";
import { useDecide, useRun } from "@/lib/queries";
import { totals, type TraceState } from "@/lib/trace";
import type { Approval } from "@/lib/types";

function ApprovalBox({
  workspace,
  approval,
  onDecided,
}: {
  workspace: string;
  approval: Approval;
  onDecided: () => void;
}) {
  const decide = useDecide(workspace);
  const [comment, setComment] = useState("");
  async function send(decision: "approve" | "reject") {
    await decide.mutateAsync({ id: approval.id, decision, comment });
    onDecided();
  }
  return (
    <div className="border-warning/40 bg-warning-soft/60 space-y-2 rounded-lg border p-3">
      <p className="text-[13px] font-semibold">{approval.title}</p>
      {approval.message ? (
        <p className="text-foreground/90 max-h-40 overflow-y-auto text-[12.5px] whitespace-pre-wrap">
          {approval.message}
        </p>
      ) : null}
      <Textarea
        rows={2}
        aria-label="Comment for the record"
        placeholder="Comment (optional)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={decide.isPending}
          onClick={() => void send("reject")}
        >
          Reject
        </Button>
        <Button size="sm" disabled={decide.isPending} onClick={() => void send("approve")}>
          Approve
        </Button>
      </div>
    </div>
  );
}

/** The live trace of a test run, docked under the canvas. */
export function RunPanel({
  workspace,
  runId,
  trace,
  selectedNode,
  onSelectNode,
  onCancel,
  onClose,
  onDecided,
  canDecide,
}: {
  workspace: string;
  runId: string;
  trace: TraceState;
  selectedNode: string | null;
  onSelectNode: (id: string) => void;
  onCancel: () => void;
  onClose: () => void;
  onDecided: () => void;
  canDecide: boolean;
}) {
  const [open, setOpen] = useState(true);
  const run = useRun(workspace, runId);
  const sum = totals(trace);
  const promptTokens = trace.promptTokens || sum.promptTokens;
  const completionTokens = trace.completionTokens || sum.completionTokens;
  const cost = trace.costUsd || sum.costUsd;
  const pending = (run.data?.approvals ?? []).filter((a) => a.status === "pending");
  const steps = [...trace.steps].sort((a, b) => a.seq - b.seq);
  const active = trace.status === "queued" || trace.status === "running";

  return (
    <div
      className={cn(
        "border-border bg-card flex shrink-0 flex-col border-t",
        open ? "h-[19rem]" : "h-auto",
      )}
      data-testid="run-panel"
    >
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <StatusBadge status={trace.status} />
        <span className="text-muted-foreground text-[12.5px] tabular-nums">
          {trace.durationMs !== null ? formatDuration(trace.durationMs) : `${steps.length} steps`}{" "}
          &middot; {formatNumber(promptTokens + completionTokens)} tokens &middot;{" "}
          {formatCost(cost)}
          {run.data?.cost_simulated ? " (simulated)" : ""}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {active || trace.status === "waiting" ? (
            <Button variant="ghost" size="sm" onClick={onCancel} aria-label="Cancel run">
              <Ban /> Cancel
            </Button>
          ) : null}
          <Button asChild variant="ghost" size="sm">
            <Link href={`/w/${workspace}/runs/${runId}`}>
              Open run <ArrowUpRight />
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={open ? "Collapse trace" : "Expand trace"}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <ChevronDown /> : <ChevronUp />}
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Close run panel" onClick={onClose}>
            <X />
          </Button>
        </div>
      </div>
      {open ? (
        <div className="border-border scroll-quiet grid min-h-0 flex-1 gap-3 overflow-y-auto border-t p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <ol className="space-y-0.5" aria-label="Steps">
            {steps.length === 0 ? (
              <li className="text-muted-foreground px-1 text-[12.5px]">
                Waiting for the first step...
              </li>
            ) : null}
            {steps.map((step) => (
              <li key={step.key}>
                <button
                  type="button"
                  onClick={() => onSelectNode(step.nodeId)}
                  className={cn(
                    "hover:bg-muted flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12.5px]",
                    selectedNode === step.nodeId && "bg-accent hover:bg-accent",
                  )}
                >
                  <StatusDot status={step.status} />
                  <NodeIcon type={step.nodeType} className="size-5 rounded-md [&_svg]:size-3" />
                  <span className="min-w-0 flex-1 truncate">
                    {step.label || step.nodeId}
                    {step.iteration ? (
                      <span className="text-subtle"> #{step.iteration}</span>
                    ) : null}
                  </span>
                  <span className="text-muted-foreground shrink-0 tabular-nums">
                    {step.status === "skipped" ? "skipped" : formatDuration(step.latencyMs)}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <div className="space-y-3">
            {canDecide
              ? pending.map((approval) => (
                  <ApprovalBox
                    key={approval.id}
                    workspace={workspace}
                    approval={approval}
                    onDecided={onDecided}
                  />
                ))
              : null}
            {trace.error ? (
              <div
                className="border-danger/30 bg-danger-soft text-danger rounded-lg border px-3 py-2 text-xs"
                role="alert"
              >
                <span className="font-mono">{trace.error.code}</span>: {trace.error.message}
              </div>
            ) : null}
            {trace.outputs ? (
              <div className="space-y-1.5">
                <p className="text-[12.5px] font-medium">Outputs</p>
                <JsonView value={trace.outputs} label="Run outputs" />
              </div>
            ) : !pending.length && !trace.error ? (
              <p className="text-muted-foreground text-[12.5px]">
                {trace.status === "waiting"
                  ? "Waiting for a person to approve or reject."
                  : "Outputs appear here when the run finishes. Click a step to inspect it."}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
