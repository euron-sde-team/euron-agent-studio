import type { Run } from "@/lib/types";

/** Who or what started a run, as a sentence fragment: "Started by Leo Chen". */
export function describeTrigger(run: Pick<Run, "trigger" | "triggered_by">): string {
  switch (run.trigger) {
    case "webhook":
      return "Started by a signed webhook";
    case "api":
      return run.triggered_by
        ? `Started through the API (${run.triggered_by})`
        : "Started through the API";
    case "rerun":
      return run.triggered_by ? `Re-run by ${run.triggered_by}` : "Re-run";
    default:
      return run.triggered_by ? `Started by ${run.triggered_by}` : "Started by hand";
  }
}

export const TRIGGER_LABELS: Record<string, string> = {
  manual: "By hand",
  api: "API",
  webhook: "Webhook",
  rerun: "Re-run",
};

export const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;
