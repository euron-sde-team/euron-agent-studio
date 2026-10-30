"use client";

import { CircleAlert, Copy, Trash2, X } from "lucide-react";

import { NodeForm } from "@/components/editor/forms";
import { NumberField, Section, SwitchField, issueAt } from "@/components/editor/fields";
import { JsonView } from "@/components/json-view";
import { NodeIcon } from "@/components/node-icon";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { formatCost, formatDuration, formatNumber } from "@/lib/format";
import { definitionOf } from "@/lib/nodes";
import type { TraceStep } from "@/lib/trace";
import type { GraphDocument, GraphNode, Issue, NodeSettings } from "@/lib/types";
import type { Variable } from "@/lib/variables";

function AdvancedSettings({
  node,
  issues,
  readOnly,
  onChange,
}: {
  node: GraphNode;
  issues: Issue[];
  readOnly: boolean;
  onChange: (settings: NodeSettings) => void;
}) {
  const definition = definitionOf(node.type);
  const settings = node.settings ?? {};
  const set = (patch: NodeSettings) => onChange({ ...settings, ...patch });
  return (
    <div className="space-y-5">
      <Section title="Time limit and retries">
        <NumberField
          label="Timeout (seconds)"
          value={settings.timeout_s ?? definition?.defaultTimeout ?? 60}
          min={1}
          max={600}
          step="any"
          disabled={readOnly}
          error={issueAt(issues, "settings.timeout_s")}
          hint="A step that runs longer is stopped and counts as failed (or retried)."
          onChange={(timeout_s) => set({ timeout_s: timeout_s ?? undefined })}
        />
        <div className="grid grid-cols-2 gap-3">
          <NumberField
            label="Retries"
            value={settings.retries ?? 0}
            min={0}
            max={5}
            disabled={readOnly}
            error={issueAt(issues, "settings.retries")}
            onChange={(retries) => set({ retries: retries ?? 0 })}
          />
          <NumberField
            label="First backoff (s)"
            value={settings.retry_backoff_s ?? 1}
            min={0}
            max={60}
            step="any"
            disabled={readOnly}
            error={issueAt(issues, "settings.retry_backoff_s")}
            onChange={(retry_backoff_s) => set({ retry_backoff_s: retry_backoff_s ?? 1 })}
          />
        </div>
        <SwitchField
          label="Continue when this step fails"
          checked={Boolean(settings.continue_on_error)}
          disabled={readOnly}
          hint="The run goes on with the error as this step's output instead of failing."
          onChange={(continue_on_error) => set({ continue_on_error })}
        />
      </Section>
      {definition?.usesModel ? (
        <Section title="Caching">
          <NumberField
            label="Reuse identical answers for (seconds)"
            value={settings.cache_ttl_s ?? 0}
            min={0}
            max={604800}
            disabled={readOnly}
            error={issueAt(issues, "settings.cache_ttl_s")}
            hint="With temperature 0, the same prompt is answered from Redis instead of the model."
            onChange={(cache_ttl_s) => set({ cache_ttl_s: cache_ttl_s ?? 0 })}
          />
        </Section>
      ) : null}
    </div>
  );
}

export function StepDetail({ step }: { step: TraceStep }) {
  const toolCalls = step.events.filter((e) => e.type === "tool_call");
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={step.status} short />
        {step.iteration ? <Badge tone="outline">Item {step.iteration}</Badge> : null}
        {step.attempt > 1 ? <Badge tone="warning">Attempt {step.attempt}</Badge> : null}
        {step.cached ? <Badge tone="info">Cached</Badge> : null}
      </div>
      <dl className="text-muted-foreground grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
        <dt>Latency</dt>
        <dd className="text-foreground tabular-nums">{formatDuration(step.latencyMs)}</dd>
        {step.model ? (
          <>
            <dt>Model</dt>
            <dd className="text-foreground truncate font-mono text-[12px]">{step.model}</dd>
            <dt>Tokens</dt>
            <dd className="text-foreground tabular-nums">
              {formatNumber(step.promptTokens)} in, {formatNumber(step.completionTokens)} out
            </dd>
            <dt>Cost</dt>
            <dd className="text-foreground tabular-nums">{formatCost(step.costUsd)}</dd>
          </>
        ) : null}
      </dl>
      {step.error ? (
        <div
          className="border-danger/30 bg-danger-soft text-danger rounded-lg border px-3 py-2 text-xs"
          role="alert"
        >
          <span className="font-mono">{step.error.code}</span>: {step.error.message}
        </div>
      ) : null}
      {toolCalls.length ? (
        <div className="space-y-1.5">
          <p className="text-[12.5px] font-medium">Tool calls</p>
          <ol className="space-y-2">
            {toolCalls.map((call, index) => (
              <li key={index} className="border-border rounded-lg border p-2">
                <p className="flex items-center justify-between gap-2 text-[12.5px]">
                  <code className="font-mono font-medium">{String(call.name)}</code>
                  <span className="text-muted-foreground tabular-nums">
                    {formatDuration(Number(call.latency_ms ?? 0))}
                  </span>
                </p>
                <JsonView value={call.arguments} label="Arguments" className="mt-1.5" />
                <details className="mt-1.5">
                  <summary className="text-muted-foreground cursor-pointer text-[12px]">
                    Result
                  </summary>
                  <JsonView value={call.result} label="Result" className="mt-1.5" />
                </details>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <p className="text-[12.5px] font-medium">Input</p>
        <JsonView value={step.input} label="Step input" empty="No input recorded." />
      </div>
      <div className="space-y-1.5">
        <p className="text-[12.5px] font-medium">Output</p>
        <JsonView value={step.output} label="Step output" empty="No output yet." />
      </div>
    </div>
  );
}

export function Inspector({
  node,
  graph,
  issues,
  variables,
  readOnly,
  workspace,
  steps,
  onChange,
  onDelete,
  onDuplicate,
  onClose,
  onSelectNode,
}: {
  node: GraphNode;
  graph: GraphDocument;
  issues: Issue[];
  variables: Variable[];
  readOnly: boolean;
  workspace: string;
  steps: TraceStep[];
  onChange: (node: GraphNode) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onClose: () => void;
  onSelectNode: (id: string) => void;
}) {
  const definition = definitionOf(node.type);
  const general = issues.filter((i) => !i.field);
  const isStart = node.type === "start";
  const executable = definition?.executable ?? true;
  return (
    <div className="flex h-full flex-col" data-testid="inspector">
      <div className="border-border flex items-start gap-2.5 border-b px-4 py-3">
        <NodeIcon type={node.type} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <Input
            aria-label="Node name"
            value={node.label}
            placeholder={definition?.label ?? node.type}
            disabled={readOnly}
            className="h-8 border-transparent px-1.5 text-[14px] font-semibold shadow-none hover:border-[var(--input)] focus-visible:border-[var(--ring)]"
            onChange={(e) => onChange({ ...node, label: e.target.value })}
          />
          <p className="text-muted-foreground px-1.5 text-[11.5px]">
            {definition?.label ?? node.type} &middot;{" "}
            <Tooltip content="Other steps read this node as {{id.field}}">
              <code className="font-mono">{node.id}</code>
            </Tooltip>
          </p>
        </div>
        {!readOnly && !isStart ? (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Duplicate node"
              onClick={onDuplicate}
            >
              <Copy />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Delete node" onClick={onDelete}>
              <Trash2 />
            </Button>
          </>
        ) : null}
        <Button variant="ghost" size="icon-sm" aria-label="Close settings" onClick={onClose}>
          <X />
        </Button>
      </div>
      {general.length ? (
        <ul className="border-border space-y-1 border-b px-4 py-2.5">
          {general.map((issue, index) => (
            <li
              key={index}
              className={
                issue.severity === "error"
                  ? "text-danger flex gap-1.5 text-xs"
                  : "text-warning flex gap-1.5 text-xs"
              }
            >
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
      <Tabs defaultValue="settings" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="px-3">
          <TabsTrigger value="settings">Settings</TabsTrigger>
          {executable && !isStart ? <TabsTrigger value="advanced">Advanced</TabsTrigger> : null}
          {executable ? (
            <TabsTrigger value="run" data-testid="inspector-run-tab">
              Last run{steps.length ? ` (${steps.length})` : ""}
            </TabsTrigger>
          ) : null}
        </TabsList>
        <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-4 pb-6">
          <TabsContent value="settings" className="space-y-5">
            <NodeForm
              node={node}
              graph={graph}
              issues={issues}
              variables={variables}
              readOnly={readOnly}
              workspace={workspace}
              onSelectNode={onSelectNode}
              set={(patch) => onChange({ ...node, config: { ...node.config, ...patch } })}
            />
          </TabsContent>
          <TabsContent value="advanced">
            <AdvancedSettings
              node={node}
              issues={issues}
              readOnly={readOnly}
              onChange={(settings) => onChange({ ...node, settings })}
            />
          </TabsContent>
          <TabsContent value="run" className="space-y-4">
            {steps.length ? (
              steps.map((step) => (
                <div key={step.key} className="border-border border-b pb-4 last:border-b-0">
                  <StepDetail step={step} />
                </div>
              ))
            ) : (
              <p className="text-muted-foreground text-[13px]">
                Run the flow to see what this step received and returned.
              </p>
            )}
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
