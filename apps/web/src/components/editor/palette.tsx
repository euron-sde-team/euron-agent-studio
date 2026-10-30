"use client";

import { Search } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";

import { NodeIcon } from "@/components/node-icon";
import { Input } from "@/components/ui/input";
import { NODE_TYPES, type NodeCategory, type NodeDefinition } from "@/lib/nodes";

const GROUPS: { key: NodeCategory; label: string }[] = [
  { key: "ai", label: "AI" },
  { key: "tool", label: "Tools" },
  { key: "logic", label: "Logic" },
  { key: "human", label: "People" },
  { key: "io", label: "Inputs and outputs" },
  { key: "canvas", label: "Canvas" },
];

export const DRAG_TYPE = "application/x-agentstudio-node";

export function Palette({
  onAdd,
  hasStart,
}: {
  onAdd: (definition: NodeDefinition) => void;
  hasStart: boolean;
}) {
  const [query, setQuery] = useState("");
  const available = useMemo(() => {
    const q = query.trim().toLowerCase();
    return NODE_TYPES.filter((d) => !(d.type === "start" && hasStart)).filter(
      (d) => !q || `${d.label} ${d.description} ${d.type}`.toLowerCase().includes(q),
    );
  }, [query, hasStart]);

  function onDragStart(event: DragEvent, definition: NodeDefinition) {
    event.dataTransfer.setData(DRAG_TYPE, definition.type);
    event.dataTransfer.effectAllowed = "move";
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative p-3">
        <Search
          className="text-subtle pointer-events-none absolute top-1/2 left-5 size-4 -translate-y-1/2"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search nodes"
          className="pl-8"
          aria-label="Search nodes"
        />
      </div>
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {GROUPS.map((group) => {
          const items = available.filter((d) => d.category === group.key);
          if (!items.length) return null;
          return (
            <section key={group.key} className="mb-3">
              <h3 className="text-subtle px-1 pb-1.5 text-[11px] font-medium tracking-wider uppercase">
                {group.label}
              </h3>
              <ul className="space-y-1">
                {items.map((definition) => (
                  <li key={definition.type}>
                    <button
                      type="button"
                      draggable
                      onDragStart={(event) => onDragStart(event, definition)}
                      onClick={() => onAdd(definition)}
                      className="hover:border-border hover:bg-card flex w-full items-center gap-2.5 rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors"
                      title={`${definition.description}. Drag onto the canvas or click to add.`}
                      data-testid={`palette-${definition.type}`}
                    >
                      <NodeIcon type={definition.type} className="size-7" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">
                          {definition.label}
                        </span>
                        <span className="text-muted-foreground block truncate text-[11.5px]">
                          {definition.description}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {available.length === 0 ? (
          <p className="text-muted-foreground px-1 text-[13px]">No node matches.</p>
        ) : null}
      </div>
    </div>
  );
}
