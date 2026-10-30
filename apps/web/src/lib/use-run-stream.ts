"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiUrl, ws } from "@/lib/api";
import { qk } from "@/lib/queries";
import { FINAL, applyEvent, emptyTrace, type TraceState } from "@/lib/trace";

const EVENTS = [
  "run.queued",
  "run.started",
  "step.started",
  "step.progress",
  "step.finished",
  "step.waiting",
  "approval.decided",
  "run.waiting",
  "run.finished",
];

type Store = { key: string | null; trace: TraceState; connected: boolean };

/**
 * Follow a run's live trace over server-sent events. EventSource reconnects on its own and
 * sends Last-Event-ID, so the server resumes exactly where the stream stopped; the reducer is
 * idempotent, so a replay never double counts. `generation` restarts the stream (after an
 * approval, for example). State is keyed by run and generation, so a new stream starts from
 * an empty trace without resetting anything inside the effect.
 */
export function useRunStream(
  workspace: string,
  runId: string | null,
  generation = 0,
): TraceState & { connected: boolean } {
  const client = useQueryClient();
  const key = runId ? `${runId}:${generation}` : null;
  const [store, setStore] = useState<Store>({ key: null, trace: emptyTrace(), connected: false });

  useEffect(() => {
    if (!runId || !key) return;
    const source = new EventSource(apiUrl(`${ws(workspace)}/runs/${runId}/events`), {
      withCredentials: true,
    });
    const update = (change: (current: Store) => Partial<Store>) =>
      setStore((current) => {
        const base: Store =
          current.key === key ? current : { key, trace: emptyTrace(), connected: false };
        return { ...base, ...change(base) };
      });
    const refresh = () => {
      void client.invalidateQueries({ queryKey: qk.run(workspace, runId) });
      void client.invalidateQueries({ queryKey: qk.runsAll(workspace) });
      void client.invalidateQueries({ queryKey: qk.approvalsAll(workspace) });
      void client.invalidateQueries({ queryKey: qk.dashboard(workspace) });
    };
    const onEvent = (event: MessageEvent<string>) => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        return;
      }
      update((current) => ({
        trace: applyEvent(current.trace, { id: event.lastEventId || null, type: event.type, data }),
      }));
      if (event.type === "run.finished") {
        source.close();
        update(() => ({ connected: false }));
        refresh();
      } else if (event.type === "run.waiting") {
        refresh();
        // A trace rebuilt from the database has no ids: it will not grow, so stop listening.
        if (!event.lastEventId) source.close();
      }
    };
    for (const name of EVENTS) source.addEventListener(name, onEvent as EventListener);
    source.onopen = () => update(() => ({ connected: true }));
    source.onerror = () => update(() => ({ connected: source.readyState === EventSource.OPEN }));
    return () => source.close();
  }, [workspace, runId, key, client]);

  const current = store.key === key ? store : { trace: emptyTrace(), connected: false };
  return { ...current.trace, connected: current.connected };
}

export const isFinal = (status: string) => (FINAL as string[]).includes(status);
