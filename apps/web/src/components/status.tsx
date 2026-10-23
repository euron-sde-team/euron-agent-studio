import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Hourglass,
  Loader2,
  MinusCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { ApprovalStatus, RunStatus, StepStatus } from "@/lib/types";

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "outline" | "info";
type AnyStatus = RunStatus | StepStatus | ApprovalStatus;

export const STATUS: Record<AnyStatus, { label: string; tone: Tone; icon: LucideIcon }> = {
  succeeded: { label: "Succeeded", tone: "success", icon: CheckCircle2 },
  failed: { label: "Failed", tone: "danger", icon: XCircle },
  running: { label: "Running", tone: "info", icon: Loader2 },
  queued: { label: "Queued", tone: "neutral", icon: Clock3 },
  waiting: { label: "Waiting for approval", tone: "warning", icon: Hourglass },
  cancelled: { label: "Cancelled", tone: "neutral", icon: Ban },
  skipped: { label: "Skipped", tone: "outline", icon: MinusCircle },
  pending: { label: "Pending", tone: "warning", icon: Hourglass },
  approved: { label: "Approved", tone: "success", icon: CheckCircle2 },
  rejected: { label: "Rejected", tone: "danger", icon: XCircle },
  expired: { label: "Expired", tone: "neutral", icon: CircleDashed },
};

export function StatusBadge({
  status,
  className,
  short,
}: {
  status: AnyStatus;
  className?: string;
  short?: boolean;
}) {
  const { label, tone, icon: Icon } = STATUS[status] ?? STATUS.queued;
  return (
    <Badge tone={tone} className={className}>
      <Icon className={cn(status === "running" && "animate-spin")} aria-hidden />
      {short && status === "waiting" ? "Waiting" : label}
    </Badge>
  );
}

const DOT: Record<string, string> = {
  succeeded: "bg-success",
  failed: "bg-danger",
  running: "bg-info animate-pulse-dot",
  queued: "bg-subtle",
  waiting: "bg-warning animate-pulse-dot",
  cancelled: "bg-subtle",
  skipped: "bg-input",
  pending: "bg-warning",
  approved: "bg-success",
  rejected: "bg-danger",
  expired: "bg-subtle",
};

/** A coloured dot for dense lists and the canvas. */
export function StatusDot({ status, className }: { status: AnyStatus; className?: string }) {
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", DOT[status], className)}
      aria-hidden
    />
  );
}
