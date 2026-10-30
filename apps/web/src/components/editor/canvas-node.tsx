"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CircleAlert } from "lucide-react";
import { memo } from "react";

import { NodeIcon } from "@/components/node-icon";
import { StatusDot } from "@/components/status";
import { cn } from "@/lib/cn";
import type { CanvasNode } from "@/lib/graph";
import { definitionOf, displayLabel, handleLabel, outputHandles } from "@/lib/nodes";

const RUN_RING: Record<string, string> = {
  succeeded: "ring-2 ring-success/60",
  failed: "ring-2 ring-danger/70",
  running: "ring-2 ring-info/70",
  waiting: "ring-2 ring-warning/80",
  cancelled: "ring-2 ring-subtle/40",
};

/** One line under the title, so a flow reads at a glance without opening every node. */
function summary(type: string, config: Record<string, unknown>): string {
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  switch (type) {
    case "start": {
      const inputs = Array.isArray(config.inputs) ? (config.inputs as { name: string }[]) : [];
      return inputs.length ? inputs.map((i) => i.name).join(", ") : "No inputs";
    }
    case "llm":
      return text(config.prompt) || "Write a prompt";
    case "agent":
      return text(config.task) || "Describe the task";
    case "http":
      return `${text(config.method) || "GET"} ${text(config.url) || "no URL yet"}`;
    case "knowledge":
      return text(config.query) || "Query from the agent";
    case "calculator":
      return text(config.expression) || "Expression from the agent";
    case "json_transform":
      return text(config.expression) || "No expression yet";
    case "loop":
      return text(config.items) ? `For each in ${text(config.items)}` : "Choose the items";
    case "approval":
      return text(config.title) || "Review required";
    case "output": {
      const fields = Array.isArray(config.fields) ? (config.fields as { name: string }[]) : [];
      return fields.map((f) => f.name).join(", ") || "No fields";
    }
    default:
      return "";
  }
}

function FlowNodeView({ data, selected }: NodeProps<CanvasNode>) {
  const { node, errors, warnings, runStatus, runCount } = data;
  const definition = definitionOf(node.type);
  const handles = outputHandles(node);
  const flowHandles = handles.filter((h) => h !== "tool");
  const many = flowHandles.length > 1;
  const model = definition?.usesModel && typeof node.config.model === "string";
  return (
    <div
      className={cn(
        "bg-card text-card-foreground relative w-62 rounded-xl border shadow-sm transition-shadow",
        selected ? "border-primary shadow-md" : "border-border",
        errors > 0 && !selected && "border-danger/60",
        runStatus && RUN_RING[runStatus],
      )}
      data-testid={`node-${node.id}`}
    >
      {definition?.inputs.includes("in") ? (
        <Handle
          type="target"
          position={Position.Left}
          id="in"
          className="!size-3 !border-2"
          aria-label="Input"
        />
      ) : null}
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <NodeIcon type={node.type} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] leading-tight font-semibold">{displayLabel(node)}</p>
          <p
            className="text-muted-foreground truncate text-[11.5px]"
            title={summary(node.type, node.config)}
          >
            {summary(node.type, node.config)}
          </p>
          {model ? (
            <p className="text-subtle mt-0.5 truncate font-mono text-[10.5px]">
              {String(node.config.model)}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {runStatus ? <StatusDot status={runStatus} className="mt-1" /> : null}
          {runCount && runCount > 1 ? (
            <span className="text-subtle text-[10.5px] tabular-nums">x{runCount}</span>
          ) : null}
          {errors > 0 ? (
            <span
              className="text-danger flex items-center gap-0.5 text-[11px] font-medium"
              title={`${errors} problem${errors === 1 ? "" : "s"}`}
            >
              <CircleAlert className="size-3.5" aria-hidden />
              {errors}
            </span>
          ) : warnings > 0 ? (
            <CircleAlert
              className="text-warning size-3.5"
              aria-label={`${warnings} warning${warnings === 1 ? "" : "s"}`}
            />
          ) : null}
        </div>
      </div>
      {many ? (
        <div className="border-border border-t px-3 py-1.5">
          {flowHandles.map((handle) => (
            <div
              key={handle}
              className="text-muted-foreground relative flex h-5 items-center justify-end text-[11px]"
            >
              {handleLabel(node, handle)}
              <Handle
                type="source"
                position={Position.Right}
                id={handle}
                className="!-right-[18px] !size-3 !border-2"
                style={{ top: "50%" }}
                aria-label={handleLabel(node, handle)}
              />
            </div>
          ))}
        </div>
      ) : flowHandles.length === 1 ? (
        <Handle
          type="source"
          position={Position.Right}
          id={flowHandles[0]}
          className="!size-3 !border-2"
          aria-label="Next"
        />
      ) : null}
      {handles.includes("tool") ? (
        <Handle
          type="source"
          position={Position.Top}
          id="tool"
          className="as-tool-handle !border-info !size-3 !border-2"
          title="Lend this node to an agent as a tool"
          aria-label="As a tool"
        />
      ) : null}
      {definition?.inputs.includes("tools") ? (
        <>
          <Handle
            type="target"
            position={Position.Bottom}
            id="tools"
            className="!border-info !size-3 !border-2"
            title="Connect tools here"
            aria-label="Tools"
          />
          <span className="text-info pointer-events-none absolute -bottom-5 left-1/2 -translate-x-1/2 text-[10.5px] font-medium">
            Tools
          </span>
        </>
      ) : null}
    </div>
  );
}

export const FlowNode = memo(FlowNodeView);

const NOTE: Record<string, string> = {
  yellow: "bg-note-yellow",
  blue: "bg-note-blue",
  green: "bg-note-green",
  pink: "bg-note-pink",
  gray: "bg-note-gray",
};

function NoteNodeView({ data, selected }: NodeProps<CanvasNode>) {
  const { node } = data;
  const text = typeof node.config.text === "string" ? node.config.text : "";
  return (
    <div
      className={cn(
        "text-note-ink w-60 rounded-lg p-3 text-[12.5px] leading-relaxed whitespace-pre-wrap shadow-sm",
        NOTE[String(node.config.color)] ?? NOTE.yellow,
        selected && "ring-primary ring-2",
      )}
      data-testid={`node-${node.id}`}
    >
      {node.label ? <p className="mb-1 font-semibold">{node.label}</p> : null}
      {text || <span className="opacity-60">Double-click to write a note</span>}
    </div>
  );
}

export const NoteNode = memo(NoteNodeView);
