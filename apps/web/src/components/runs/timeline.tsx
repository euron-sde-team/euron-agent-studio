"use client";

import { STATUS } from "@/components/status";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { timeline } from "@/lib/runs";
import type { TraceStep } from "@/lib/trace";

const BAR: Record<string, string> = {
  succeeded: "bg-success/80",
  failed: "bg-danger",
  running: "bg-info animate-pulse",
  waiting:
    "bg-warning/70 bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgb(255_255_255/0.25)_4px_8px)]",
  cancelled: "bg-subtle/60",
  skipped: "bg-input",
};

/** A Gantt view of the steps that started, on one time axis: parallel branches overlap. */
export function Timeline({
  steps,
  runStart,
  now,
  selected,
  onSelect,
}: {
  steps: TraceStep[];
  runStart: string | null;
  now: number;
  selected: string | null;
  onSelect: (key: string) => void;
}) {
  const { rows, spanMs } = timeline(steps, runStart, now);
  const skipped = steps.filter((s) => s.status === "skipped").length;
  if (!rows.length) {
    return <p className="text-muted-foreground px-5 py-6 text-[13px]">No step has started yet.</p>;
  }
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="px-5 pb-4" data-testid="timeline">
      <div className="text-subtle ml-[38%] flex justify-between pb-1.5 text-[11px] tabular-nums sm:ml-[30%]">
        {ticks.map((tick) => (
          <span key={tick}>{formatDuration(spanMs * tick)}</span>
        ))}
      </div>
      <ol className="space-y-0.5">
        {rows.map((row) => {
          const status = STATUS[row.step.status];
          const name = `${row.step.label || row.step.nodeId}${row.step.iteration ? ` #${row.step.iteration}` : ""}`;
          return (
            <li key={row.step.key}>
              <button
                type="button"
                onClick={() => onSelect(row.step.key)}
                className={cn(
                  "hover:bg-muted flex w-full items-center gap-3 rounded-md px-1.5 py-1 text-left transition-colors",
                  selected === row.step.key && "bg-accent hover:bg-accent",
                )}
                aria-label={`${name}: ${status.label}, ${formatDuration(row.step.latencyMs)}`}
              >
                <span className="w-[38%] truncate text-[12.5px] sm:w-[30%]">{name}</span>
                <span className="bg-muted/60 relative h-4 flex-1 rounded-sm">
                  <span
                    className={cn("absolute top-0 h-full rounded-sm", BAR[row.step.status])}
                    style={{ left: `${row.offset * 100}%`, width: `${row.width * 100}%` }}
                  />
                </span>
                <span className="text-muted-foreground w-16 shrink-0 text-right text-[11.5px] tabular-nums">
                  {row.step.latencyMs !== null ? formatDuration(row.step.latencyMs) : status.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {skipped ? (
        <p className="text-subtle mt-2 text-[12px]">
          {skipped} skipped step{skipped === 1 ? "" : "s"} on branches that did not run.
        </p>
      ) : null}
    </div>
  );
}
