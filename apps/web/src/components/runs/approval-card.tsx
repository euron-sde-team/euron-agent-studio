"use client";

import { Check, Hourglass, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { JsonView } from "@/components/json-view";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useDecide } from "@/lib/queries";
import type { Approval } from "@/lib/types";

/** One approval request: what the flow wants checked, and the decision when there is one. */
export function ApprovalCard({
  workspace,
  approval,
  canDecide,
  showRun = true,
  onDecided,
}: {
  workspace: string;
  approval: Approval;
  canDecide: boolean;
  showRun?: boolean;
  onDecided?: () => void;
}) {
  const decide = useDecide(workspace);
  const [comment, setComment] = useState("");
  const pending = approval.status === "pending";
  const contextKeys = Object.keys(approval.context ?? {});

  async function send(decision: "approve" | "reject") {
    try {
      await decide.mutateAsync({ id: approval.id, decision, comment });
      toast.success(decision === "approve" ? "Approved: the run continues" : "Rejected");
      setComment("");
      onDecided?.();
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  return (
    <Card className="p-4" data-testid={`approval-${approval.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="bg-warning-soft text-warning flex size-9 shrink-0 items-center justify-center rounded-lg">
          <Hourglass className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold tracking-tight">{approval.title}</p>
          <p className="text-muted-foreground text-[12.5px]">
            {showRun ? (
              <>
                <Link
                  href={`/w/${workspace}/runs/${approval.run_id}`}
                  className="text-foreground font-medium hover:underline"
                >
                  {approval.flow_name}
                </Link>{" "}
                &middot;{" "}
              </>
            ) : null}
            requested {formatRelative(approval.created_at)}
            {approval.expires_at && pending ? (
              <> &middot; expires {formatDateTime(approval.expires_at)}</>
            ) : null}
          </p>
        </div>
        <StatusBadge status={approval.status} />
      </div>
      {approval.message ? (
        <div className="border-border bg-muted/40 mt-3 max-h-72 overflow-y-auto rounded-lg border px-3.5 py-3 text-[13px] leading-relaxed whitespace-pre-wrap">
          {approval.message}
        </div>
      ) : null}
      {contextKeys.length ? (
        <details className="mt-2">
          <summary className="text-muted-foreground cursor-pointer text-[12.5px]">
            Context ({contextKeys.join(", ")})
          </summary>
          <JsonView value={approval.context} label="Approval context" className="mt-2" />
        </details>
      ) : null}
      {pending && canDecide ? (
        <div className="mt-3 space-y-2">
          <Textarea
            rows={2}
            aria-label="Comment for the record"
            placeholder="Comment for the record (optional)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              disabled={decide.isPending}
              onClick={() => void send("reject")}
              data-testid="reject"
            >
              <X /> Reject
            </Button>
            <Button
              disabled={decide.isPending}
              onClick={() => void send("approve")}
              data-testid="approve"
            >
              <Check /> Approve
            </Button>
          </div>
        </div>
      ) : !pending ? (
        <p className="text-muted-foreground mt-3 text-[12.5px]">
          {approval.status === "expired"
            ? "Nobody decided in time, so it counted as rejected."
            : approval.status === "cancelled"
              ? "The run was cancelled before anyone decided."
              : `${approval.decided_by_name ?? "Someone"} ${approval.status} it ${
                  approval.decided_at ? formatRelative(approval.decided_at) : ""
                }`}
          {approval.comment ? <>: &ldquo;{approval.comment}&rdquo;</> : null}
        </p>
      ) : (
        <p className="text-muted-foreground mt-3 text-[12.5px]">
          Waiting for an editor or owner to decide.
        </p>
      )}
    </Card>
  );
}
