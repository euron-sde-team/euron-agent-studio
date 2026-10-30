"use client";

import { Background, BackgroundVariant, Controls, ReactFlow } from "@xyflow/react";
import { useMemo } from "react";

import { FlowNode, NoteNode } from "@/components/editor/canvas-node";
import { toCanvas, type CanvasEdge, type CanvasNode } from "@/lib/graph";
import type { GraphDocument, StepStatus } from "@/lib/types";

const nodeTypes = { flow: FlowNode, note: NoteNode };

/**
 * A read-only canvas: template previews, and runs drawn as they happened (rings for each
 * node's outcome, the taken path highlighted, nodes the run never reached quiet and dashed).
 */
export function GraphView({
  graph,
  statuses,
  fired,
  selectedNode,
  onSelectNode,
  className,
  controls = false,
  preview = false,
}: {
  graph: GraphDocument;
  statuses?: Map<string, { status: StepStatus; count: number }>;
  fired?: Map<string, Set<string>>;
  selectedNode?: string | null;
  onSelectNode?: (id: string) => void;
  className?: string;
  controls?: boolean;
  /** Small previews fit the whole graph, however wide; inspectors keep text legible. */
  preview?: boolean;
}) {
  const base = useMemo(() => toCanvas(graph), [graph]);
  const nodes: CanvasNode[] = base.nodes.map((node) => {
    const run = statuses?.get(node.id);
    const reached = run && run.status !== "skipped";
    return {
      ...node,
      selected: node.id === selectedNode,
      className: statuses && node.data.node.type !== "note" && !reached ? "as-not-run" : undefined,
      data: {
        ...node.data,
        runStatus: reached ? run.status : undefined,
        runCount: run?.count,
      },
    };
  });
  const edges: CanvasEdge[] = base.edges.map((edge) => {
    if (!fired) return edge;
    const taken = fired.get(edge.source)?.has(edge.sourceHandle ?? "out");
    return {
      ...edge,
      style: taken ? { stroke: "var(--primary)", strokeWidth: 2 } : { opacity: 0.4 },
    };
  });
  return (
    <div className={className ?? "bg-canvas h-80 rounded-xl"}>
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onSelectNode ? (_, node) => onSelectNode(node.id) : undefined}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={Boolean(onSelectNode)}
        deleteKeyCode={null}
        zoomOnScroll={false}
        preventScrolling={false}
        fitView
        fitViewOptions={{
          padding: 0.1,
          maxZoom: preview ? 0.8 : 1,
          minZoom: preview ? 0.05 : 0.3,
        }}
        minZoom={preview ? 0.05 : 0.15}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "smoothstep" }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={18}
          size={1.2}
          color="var(--canvas-dot)"
        />
        {controls ? <Controls showInteractive={false} position="bottom-left" /> : null}
      </ReactFlow>
    </div>
  );
}
