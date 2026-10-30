"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import {
  ArrowLeft,
  CircleAlert,
  CloudCheck,
  Copy,
  FileCode2,
  FileJson,
  History,
  LayoutGrid,
  ListChecks,
  Loader2,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Play,
  Redo2,
  Rocket,
  Trash2,
  Undo2,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { FlowNode, NoteNode } from "@/components/editor/canvas-node";
import {
  DetailsDialog,
  ExportDialog,
  PublishDialog,
  RunDialog,
  TriggersDialog,
  VersionsDialog,
} from "@/components/editor/dialogs";
import { Inspector } from "@/components/editor/inspector";
import { DRAG_TYPE, Palette } from "@/components/editor/palette";
import { RunPanel } from "@/components/editor/run-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { ApiError, api, saveText, ws } from "@/lib/api";
import { cn } from "@/lib/cn";
import { slugify } from "@/lib/format";
import {
  autoLayout,
  checkConnection,
  edgeId,
  toCanvas,
  toCanvasNode,
  toGraph,
  type CanvasEdge,
  type CanvasNode,
} from "@/lib/graph";
import { emptyHistory, record, redo, undo, type History as UndoHistory } from "@/lib/history";
import {
  defaultConfig,
  definitionOf,
  displayLabel,
  nextNodeId,
  outputHandles,
  type NodeDefinition,
} from "@/lib/nodes";
import { canEdit, useFlowActions, useRunActions, useSaveDraft, useSecrets } from "@/lib/queries";
import { PALETTE_KEY, readLocal, writeLocal } from "@/lib/storage";
import { nodeStatuses } from "@/lib/trace";
import type { Flow, FlowDocument, GraphDocument, GraphNode, Issue, Role } from "@/lib/types";
import { useRunStream } from "@/lib/use-run-stream";
import { variablesFor } from "@/lib/variables";

const nodeTypes = { flow: FlowNode, note: NoteNode };
const AUTOSAVE_MS = 1000;
const COALESCE_MS = 800;

type SaveState = "saved" | "dirty" | "saving" | "error";
type DialogName = "run" | "publish" | "versions" | "export" | "triggers" | "details" | null;

function message(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return Boolean(
    element &&
    (element.tagName === "INPUT" ||
      element.tagName === "TEXTAREA" ||
      element.tagName === "SELECT" ||
      element.isContentEditable),
  );
}

function EditorCanvas({
  workspace,
  flow: source,
  role,
}: {
  workspace: string;
  flow: Flow;
  role: Role;
}) {
  const router = useRouter();
  const reactFlow = useReactFlow<CanvasNode, CanvasEdge>();
  const readOnly = !canEdit(role);
  const save = useSaveDraft(workspace, source.id);
  const actions = useFlowActions(workspace, source.id);
  const runActions = useRunActions(workspace);
  const secrets = useSecrets(workspace, role !== "viewer");

  // Details and webhook changes arrive through the query cache; the graph stays the editor's.
  const [published, setPublished] = useState<Pick<Flow, "published_version" | "latest_version">>();
  const flow = useMemo(() => ({ ...source, ...published }), [source, published]);
  const [initial] = useState(() => toCanvas(source.graph));
  const [nodes, setNodes] = useState<CanvasNode[]>(initial.nodes);
  const [edges, setEdges] = useState<CanvasEdge[]>(initial.edges);
  const [issues, setIssues] = useState<Issue[]>(source.issues);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [selected, setSelected] = useState<string | null>(null);
  // The editor only renders in the browser (after the flow loads), so storage is safe here.
  const [palette, setPalette] = useState(() => readLocal(PALETTE_KEY) !== "closed");
  const [dialog, setDialog] = useState<DialogName>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [streamGeneration, setStreamGeneration] = useState(0);
  const [history, setHistory] = useState<UndoHistory<GraphDocument>>(emptyHistory);
  const [inspectorKey, setInspectorKey] = useState(0);
  const revision = useRef(source.draft_revision);
  const version = useRef(0);
  const lastRecord = useRef<{ key: string; at: number } | null>(null);

  const trace = useRunStream(workspace, runId, streamGeneration);

  // Opening or closing the run trace resizes the canvas: fit the flow to the space it has.
  useEffect(() => {
    const frame = requestAnimationFrame(
      () => void reactFlow.fitView({ padding: 0.15, maxZoom: 1.05, duration: 250 }),
    );
    return () => cancelAnimationFrame(frame);
  }, [runId, reactFlow]);
  const graph = useMemo(() => toGraph(nodes, edges), [nodes, edges]);

  // ------------------------------------------------------------------------------------
  // Editing, history and autosave
  // ------------------------------------------------------------------------------------

  /** Remember the graph before a change; bursts of typing on one field become one step. */
  const remember = useCallback(
    (key = "") => {
      const now = Date.now();
      const last = lastRecord.current;
      if (key && last && last.key === key && now - last.at < COALESCE_MS) {
        lastRecord.current = { key, at: now };
        return;
      }
      lastRecord.current = { key, at: now };
      setHistory((h) => record(h, toGraph(nodes, edges)));
    },
    [nodes, edges],
  );

  const touch = useCallback(() => {
    version.current += 1;
    setSaveState("dirty");
  }, []);

  const persist = useCallback(async (): Promise<boolean> => {
    if (readOnly) return true;
    const started = version.current;
    setSaveState("saving");
    try {
      const saved = await save.mutateAsync({
        graph: { ...toGraph(nodes, edges), viewport: reactFlow.getViewport() },
        base_revision: revision.current,
      });
      revision.current = saved.draft_revision;
      setIssues(saved.issues);
      setSaveState(version.current === started ? "saved" : "dirty");
      return true;
    } catch (error) {
      setSaveState("error");
      if (error instanceof ApiError && error.code === "revision_conflict") {
        toast.error("Someone else saved this flow.", {
          description: "Reload to see their changes; your unsaved edits will be lost.",
          action: { label: "Reload", onClick: () => window.location.reload() },
          duration: 20_000,
        });
      } else {
        toast.error("Could not save the draft", { description: message(error) ?? undefined });
      }
      return false;
    }
  }, [readOnly, save, nodes, edges, reactFlow]);

  useEffect(() => {
    if (saveState !== "dirty" || readOnly) return;
    const timer = setTimeout(() => void persist(), AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [saveState, persist, readOnly, nodes, edges]);

  useEffect(() => {
    if (saveState === "saved") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [saveState]);

  const load = useCallback((document: GraphDocument) => {
    const canvas = toCanvas(document);
    setNodes(canvas.nodes);
    setEdges(canvas.edges);
    setInspectorKey((k) => k + 1);
  }, []);

  const step = useCallback(
    (direction: "undo" | "redo") => {
      if (readOnly) return;
      const current = toGraph(nodes, edges);
      const result = direction === "undo" ? undo(history, current) : redo(history, current);
      if (!result) return;
      setHistory(result.history);
      lastRecord.current = null;
      load(result.state);
      touch();
    },
    [readOnly, nodes, edges, history, load, touch],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      // The Start node is the flow's entry point: it can move but never be deleted.
      let visible = changes.filter(
        (c) =>
          !(c.type === "remove" && nodes.find((n) => n.id === c.id)?.data.node.type === "start"),
      );
      if (readOnly) visible = visible.filter((c) => c.type === "select" || c.type === "dimensions");
      const structural = visible.some(
        (c) => c.type === "remove" || (c.type === "position" && c.dragging === false),
      );
      const dragStart = visible.some((c) => c.type === "position" && c.dragging === true);
      if (dragStart && !lastRecord.current?.key.startsWith("drag")) remember("drag");
      else if (visible.some((c) => c.type === "remove")) remember();
      setNodes((current) => applyNodeChanges(visible, current));
      if (structural) {
        lastRecord.current = null;
        touch();
      }
      const removed = visible.filter((c) => c.type === "remove").map((c) => c.id);
      if (removed.length) {
        setEdges((current) =>
          current.filter((e) => !removed.includes(e.source) && !removed.includes(e.target)),
        );
        if (selected && removed.includes(selected)) setSelected(null);
      }
    },
    [nodes, readOnly, remember, touch, selected],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) => {
      const visible = readOnly ? changes.filter((c) => c.type === "select") : changes;
      if (visible.some((c) => c.type === "remove")) remember();
      setEdges((current) => applyEdgeChanges(visible, current));
      if (visible.some((c) => c.type === "remove")) touch();
    },
    [readOnly, remember, touch],
  );

  const isValidConnection = useCallback(
    (connection: Connection | CanvasEdge) =>
      checkConnection(
        nodes.find((n) => n.id === connection.source)?.data.node,
        nodes.find((n) => n.id === connection.target)?.data.node,
        connection.sourceHandle,
        connection.targetHandle,
        edges,
      ).ok,
    [nodes, edges],
  );

  const connect = useCallback(
    (source: string, sourceHandle: string, target: string, targetHandle: string) => {
      remember();
      setEdges((current) => [
        ...current,
        {
          id: edgeId(source, sourceHandle, target, targetHandle),
          source,
          target,
          sourceHandle,
          targetHandle,
          className: targetHandle === "tools" ? "as-tool-edge" : undefined,
        },
      ]);
      touch();
    },
    [remember, touch],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (readOnly) return;
      const check = checkConnection(
        nodes.find((n) => n.id === connection.source)?.data.node,
        nodes.find((n) => n.id === connection.target)?.data.node,
        connection.sourceHandle,
        connection.targetHandle,
        edges,
      );
      if (!check.ok) {
        toast.message(check.reason);
        return;
      }
      connect(
        connection.source,
        connection.sourceHandle ?? "out",
        connection.target,
        connection.targetHandle ?? "in",
      );
    },
    [readOnly, nodes, edges, connect],
  );

  const addNode = useCallback(
    (definition: NodeDefinition, position?: { x: number; y: number }) => {
      if (readOnly) return;
      if (definition.type === "start" && nodes.some((n) => n.data.node.type === "start")) return;
      remember();
      const anchor = nodes.find((n) => n.id === selected);
      const id = nextNodeId(
        definition.type,
        nodes.map((n) => n.id),
      );
      const placed =
        position ??
        (anchor
          ? {
              x: anchor.position.x + (definition.tool ? 0 : 320),
              y: anchor.position.y + (definition.tool ? 190 : 0),
            }
          : reactFlow.screenToFlowPosition({
              x: window.innerWidth / 2,
              y: window.innerHeight / 2,
            }));
      const node: GraphNode = {
        id,
        type: definition.type,
        position: placed,
        label: "",
        config: defaultConfig(definition.type),
        settings: {},
      };
      setNodes((current) => [
        ...current.map((n) => ({ ...n, selected: false })),
        { ...toCanvasNode(node), selected: true },
      ]);
      // Added next to a selected node: wire them, the way people build left to right.
      if (anchor && !position && definition.executable && definition.type !== "start") {
        const anchorNode = anchor.data.node;
        if (anchorNode.type === "agent" && definition.tool) {
          connect(id, "tool", anchor.id, "tools");
        } else {
          const handle = outputHandles(anchorNode).find((h) => h !== "tool");
          if (handle && definition.inputs.includes("in")) connect(anchor.id, handle, id, "in");
        }
      }
      setSelected(id);
      touch();
    },
    [readOnly, nodes, selected, reactFlow, remember, connect, touch],
  );

  const updateNode = useCallback(
    (node: GraphNode) => {
      remember(`edit:${node.id}`);
      setNodes((current) =>
        current.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, node } } : n)),
      );
      touch();
    },
    [remember, touch],
  );

  const removeNode = useCallback(
    (id: string) => {
      remember();
      setNodes((current) => current.filter((n) => n.id !== id));
      setEdges((current) => current.filter((e) => e.source !== id && e.target !== id));
      setSelected(null);
      touch();
    },
    [remember, touch],
  );

  const duplicateNode = useCallback(
    (id: string) => {
      const source = nodes.find((n) => n.id === id);
      if (!source || source.data.node.type === "start") return;
      remember();
      const type = source.data.node.type as NodeDefinition["type"];
      const copy: GraphNode = {
        ...structuredClone(source.data.node),
        id: nextNodeId(
          type,
          nodes.map((n) => n.id),
        ),
        label: source.data.node.label ? `${source.data.node.label} (copy)` : "",
        position: { x: source.position.x + 40, y: source.position.y + 140 },
      };
      setNodes((current) => [
        ...current.map((n) => ({ ...n, selected: false })),
        { ...toCanvasNode(copy), selected: true },
      ]);
      setSelected(copy.id);
      touch();
    },
    [nodes, remember, touch],
  );

  const tidy = useCallback(() => {
    if (readOnly) return;
    remember();
    setNodes((current) =>
      autoLayout(current, edges, (id) => {
        const internal = reactFlow.getInternalNode(id);
        const measured = internal?.measured;
        return measured?.width && measured.height
          ? { width: measured.width, height: measured.height }
          : undefined;
      }),
    );
    touch();
    requestAnimationFrame(() => void reactFlow.fitView({ padding: 0.15, duration: 300 }));
  }, [readOnly, edges, reactFlow, remember, touch]);

  function onDrop(event: DragEvent) {
    event.preventDefault();
    const type = event.dataTransfer.getData(DRAG_TYPE);
    const definition = definitionOf(type);
    if (definition)
      addNode(definition, reactFlow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const mod = event.metaKey || event.ctrlKey;
      if (!mod) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        if (saveState !== "saved") void persist();
        return;
      }
      if (isTyping(event.target)) return;
      if (key === "z") {
        event.preventDefault();
        step(event.shiftKey ? "redo" : "undo");
      } else if (key === "y") {
        event.preventDefault();
        step("redo");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, persist, saveState]);

  // ------------------------------------------------------------------------------------
  // Runs, issues and what the canvas paints
  // ------------------------------------------------------------------------------------

  const statuses = useMemo(() => nodeStatuses(trace.steps), [trace.steps]);
  const fired = useMemo(() => {
    const handles = new Map<string, Set<string>>();
    for (const s of trace.steps) {
      if (s.status !== "succeeded") continue;
      const set = handles.get(s.nodeId) ?? new Set<string>();
      for (const h of s.handles.length
        ? s.handles
        : outputHandles({ type: s.nodeType, config: {} }))
        set.add(h);
      handles.set(s.nodeId, set);
    }
    return handles;
  }, [trace.steps]);

  const counts = useMemo(() => {
    const map = new Map<string, { errors: number; warnings: number }>();
    for (const issue of issues) {
      if (!issue.node_id) continue;
      const entry = map.get(issue.node_id) ?? { errors: 0, warnings: 0 };
      if (issue.severity === "error") entry.errors += 1;
      else entry.warnings += 1;
      map.set(issue.node_id, entry);
    }
    return map;
  }, [issues]);

  const renderedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const count = counts.get(node.id);
        const status = runId ? statuses.get(node.id) : undefined;
        return {
          ...node,
          data: {
            ...node.data,
            errors: count?.errors ?? 0,
            warnings: count?.warnings ?? 0,
            runStatus: status?.status,
            runCount: status?.count,
          },
        };
      }),
    [nodes, counts, statuses, runId],
  );

  const badEdges = useMemo(() => new Set(issues.map((i) => i.edge_id).filter(Boolean)), [issues]);
  const renderedEdges = useMemo(
    () =>
      edges.map((edge) => {
        const taken = runId && fired.get(edge.source)?.has(edge.sourceHandle ?? "out");
        if (badEdges.has(edge.id)) return { ...edge, style: { stroke: "var(--danger)" } };
        if (!taken) return edge;
        return { ...edge, animated: true, style: { stroke: "var(--primary)" } };
      }),
    [edges, fired, runId, badEdges],
  );

  const selectedNode = nodes.find((n) => n.id === selected)?.data.node;
  const errors = issues.filter((i) => i.severity === "error");
  const start = nodes.find((n) => n.data.node.type === "start")?.data.node;
  const secretNames = useMemo(() => (secrets.data?.items ?? []).map((s) => s.name), [secrets.data]);
  const variables = useMemo(
    () => (selected ? variablesFor(graph, selected, secretNames) : []),
    [graph, selected, secretNames],
  );

  async function startRun(inputs: Record<string, unknown>, which: "draft" | "published") {
    if (saveState !== "saved" && !(await persist())) return;
    try {
      const run = await actions.run.mutateAsync({ inputs, version: which });
      setRunId(run.id);
      setStreamGeneration((g) => g + 1);
      setDialog(null);
    } catch {
      // Shown in the dialog.
    }
  }

  async function publish(notes: string) {
    if (saveState !== "saved" && !(await persist())) return;
    try {
      const version = await actions.publish.mutateAsync(notes);
      setPublished({ published_version: version.version, latest_version: version.version });
      setDialog(null);
      toast.success(`Published version ${version.version}`);
    } catch {
      // Shown in the dialog.
    }
  }

  async function exportJson() {
    const document = await api<FlowDocument>(`${ws(workspace)}/flows/${flow.id}/export`);
    saveText(JSON.stringify(document, null, 2), `${slugify(flow.name)}.json`, "application/json");
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-border bg-card flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back to flows">
          <Link href={`/w/${workspace}/flows`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0">
          <button
            type="button"
            className="hover:text-primary flex max-w-[16rem] items-center gap-1.5 truncate text-left text-[15px] font-semibold tracking-tight sm:max-w-sm"
            onClick={() => !readOnly && setDialog("details")}
            data-testid="flow-name"
          >
            <span className="truncate">{flow.name}</span>
            {!readOnly ? <Pencil className="text-subtle size-3 shrink-0" aria-hidden /> : null}
          </button>
          <div className="text-muted-foreground flex items-center gap-2 text-[11.5px]">
            {flow.published_version ? (
              <span>Version {flow.published_version} live</span>
            ) : (
              <span>Not published</span>
            )}
            <span className="flex items-center gap-1" data-testid="save-state">
              {saveState === "saving" ? (
                <>
                  <Loader2 className="size-3 animate-spin" /> Saving
                </>
              ) : saveState === "dirty" ? (
                "Unsaved changes"
              ) : saveState === "error" ? (
                <span className="text-danger">Not saved</span>
              ) : (
                <>
                  <CloudCheck className="size-3" /> Saved
                </>
              )}
            </span>
            {readOnly ? <Badge tone="outline">View only</Badge> : null}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {!readOnly ? (
            <div className="border-border mr-1 hidden items-center rounded-lg border sm:flex">
              <Tooltip content="Undo (Ctrl or Cmd + Z)">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Undo"
                  disabled={!history.past.length}
                  onClick={() => step("undo")}
                >
                  <Undo2 />
                </Button>
              </Tooltip>
              <Tooltip content="Redo (Shift + Ctrl or Cmd + Z)">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Redo"
                  disabled={!history.future.length}
                  onClick={() => step("redo")}
                >
                  <Redo2 />
                </Button>
              </Tooltip>
              <Tooltip content="Tidy up: lay the flow out left to right">
                <Button variant="ghost" size="icon-sm" aria-label="Tidy up" onClick={tidy}>
                  <LayoutGrid />
                </Button>
              </Tooltip>
            </div>
          ) : null}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="secondary" size="sm" data-testid="issues-button">
                {errors.length ? (
                  <CircleAlert className="text-danger" />
                ) : (
                  <ListChecks className="text-success" />
                )}
                {errors.length
                  ? `${errors.length} problem${errors.length === 1 ? "" : "s"}`
                  : "Valid"}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-96">
              {issues.length === 0 ? (
                <p className="text-muted-foreground text-[13px]">
                  The flow is valid and ready to run or publish.
                </p>
              ) : (
                <ul className="max-h-80 space-y-1 overflow-y-auto" data-testid="issues-list">
                  {issues.map((issue, index) => (
                    <li key={index}>
                      <button
                        type="button"
                        className="hover:bg-muted flex w-full gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px]"
                        onClick={() => issue.node_id && setSelected(issue.node_id)}
                      >
                        <CircleAlert
                          className={cn(
                            "mt-0.5 size-3.5 shrink-0",
                            issue.severity === "error" ? "text-danger" : "text-warning",
                          )}
                          aria-hidden
                        />
                        <span>
                          {issue.node_id ? (
                            <span className="font-medium">
                              {displayLabel(
                                nodes.find((n) => n.id === issue.node_id)?.data.node ?? {
                                  type: "",
                                  label: issue.node_id,
                                },
                              )}
                              :{" "}
                            </span>
                          ) : null}
                          {issue.message}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </PopoverContent>
          </Popover>
          {!readOnly ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setDialog("run")}
                data-testid="run-flow"
              >
                <Play /> Run
              </Button>
              <Button size="sm" onClick={() => setDialog("publish")} data-testid="publish">
                <Rocket /> Publish
              </Button>
            </>
          ) : null}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setDialog("export")}
            data-testid="export-python"
          >
            <FileCode2 /> <span className="hidden md:inline">Export to Python</span>
            <span className="md:hidden">Python</span>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="More actions">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setDialog("triggers")}>
                <Webhook /> Triggers: API and webhook
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setDialog("versions")}>
                <History /> Versions
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void exportJson()}>
                <FileJson /> Export JSON
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={readOnly}
                onSelect={async () => {
                  const copy = await actions.duplicate.mutateAsync();
                  router.push(`/w/${workspace}/flows/${copy.id}`);
                }}
              >
                <Copy /> Duplicate flow
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                destructive
                disabled={readOnly}
                onSelect={async () => {
                  if (!window.confirm(`Delete "${flow.name}" with its versions and runs?`)) return;
                  await actions.remove.mutateAsync();
                  router.replace(`/w/${workspace}/flows`);
                }}
              >
                <Trash2 /> Delete flow
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {!readOnly && palette ? (
          <aside
            className="border-border bg-sidebar hidden w-64 shrink-0 border-r md:block"
            aria-label="Nodes"
          >
            <Palette onAdd={(definition) => addNode(definition)} hasStart={Boolean(start)} />
          </aside>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          <div
            className="relative min-h-0 flex-1"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            data-testid="canvas"
          >
            <ReactFlow<CanvasNode, CanvasEdge>
              nodes={renderedNodes}
              edges={renderedEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onNodeClick={(_, node) => setSelected(node.id)}
              onPaneClick={() => setSelected(null)}
              nodesDraggable={!readOnly}
              nodesConnectable={!readOnly}
              deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
              // Always fit on open: a stored viewport was made for someone else's screen.
              fitView
              fitViewOptions={{ padding: 0.15, maxZoom: 1.05 }}
              minZoom={0.2}
              proOptions={{ hideAttribution: true }}
              defaultEdgeOptions={{ type: "smoothstep" }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={18}
                size={1.2}
                color="var(--canvas-dot)"
              />
              <Controls showInteractive={false} position="bottom-left" />
              <MiniMap
                pannable
                zoomable
                position="bottom-right"
                className="!hidden xl:!block"
                ariaLabel="Minimap"
              />
            </ReactFlow>
            {!readOnly ? (
              <Button
                variant="secondary"
                size="icon-sm"
                className="absolute top-3 left-3 hidden md:inline-flex"
                aria-label={palette ? "Hide nodes" : "Show nodes"}
                onClick={() =>
                  setPalette((open) => {
                    writeLocal(PALETTE_KEY, open ? "closed" : "open");
                    return !open;
                  })
                }
              >
                {palette ? <PanelLeftClose /> : <PanelLeftOpen />}
              </Button>
            ) : null}
          </div>
          {runId ? (
            <RunPanel
              workspace={workspace}
              runId={runId}
              trace={trace}
              selectedNode={selected}
              canDecide={!readOnly}
              onSelectNode={setSelected}
              onClose={() => setRunId(null)}
              onDecided={() => setStreamGeneration((g) => g + 1)}
              onCancel={async () => {
                try {
                  await runActions.cancel.mutateAsync(runId);
                  setStreamGeneration((g) => g + 1);
                } catch (error) {
                  toast.error(message(error) ?? "Could not cancel the run");
                }
              }}
            />
          ) : null}
        </div>
        {selectedNode ? (
          <aside
            className="border-border bg-card fixed inset-0 z-30 w-full border-l md:static md:z-auto md:w-[25rem] md:shrink-0"
            aria-label="Node settings"
          >
            <Inspector
              key={`${selectedNode.id}:${inspectorKey}`}
              node={selectedNode}
              graph={graph}
              workspace={workspace}
              issues={issues.filter((i) => i.node_id === selectedNode.id)}
              variables={variables}
              readOnly={readOnly}
              steps={runId ? trace.steps.filter((s) => s.nodeId === selectedNode.id) : []}
              onChange={updateNode}
              onDelete={() => removeNode(selectedNode.id)}
              onDuplicate={() => duplicateNode(selectedNode.id)}
              onClose={() => setSelected(null)}
              onSelectNode={setSelected}
            />
          </aside>
        ) : null}
      </div>

      <RunDialog
        open={dialog === "run"}
        onOpenChange={(open) => setDialog(open ? "run" : null)}
        start={start}
        published={Boolean(flow.published_version)}
        pending={actions.run.isPending || save.isPending}
        error={message(actions.run.error)}
        onRun={(inputs, which) => void startRun(inputs, which)}
      />
      <PublishDialog
        open={dialog === "publish"}
        onOpenChange={(open) => setDialog(open ? "publish" : null)}
        flow={flow}
        errors={errors}
        pending={actions.publish.isPending || save.isPending}
        error={message(actions.publish.error)}
        onPublish={(notes) => void publish(notes)}
      />
      <VersionsDialog
        open={dialog === "versions"}
        onOpenChange={(open) => setDialog(open ? "versions" : null)}
        workspace={workspace}
        flowId={flow.id}
        readOnly={readOnly}
        pending={actions.restore.isPending}
        onRestore={async (number) => {
          remember();
          const restored = await actions.restore.mutateAsync(number);
          revision.current = restored.draft_revision;
          load(restored.graph);
          setIssues(restored.issues);
          setSaveState("saved");
          setDialog(null);
          toast.success(`Version ${number} copied into the draft`);
        }}
      />
      <ExportDialog
        open={dialog === "export"}
        onOpenChange={(open) => setDialog(open ? "export" : null)}
        workspace={workspace}
        flow={flow}
      />
      <TriggersDialog
        open={dialog === "triggers"}
        onOpenChange={(open) => setDialog(open ? "triggers" : null)}
        workspace={workspace}
        flow={flow}
        canManage={!readOnly}
      />
      <DetailsDialog
        open={dialog === "details"}
        onOpenChange={(open) => setDialog(open ? "details" : null)}
        workspace={workspace}
        flow={flow}
      />
    </div>
  );
}

export function FlowEditor(props: { workspace: string; flow: Flow; role: Role }) {
  return (
    <ReactFlowProvider>
      <EditorCanvas {...props} />
    </ReactFlowProvider>
  );
}
