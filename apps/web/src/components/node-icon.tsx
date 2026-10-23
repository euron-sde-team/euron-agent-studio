import {
  Blocks,
  BookOpen,
  Bot,
  Braces,
  Calculator,
  Flag,
  GitBranch,
  Globe,
  Play,
  Repeat,
  Sparkles,
  StickyNote,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/cn";
import { definitionOf, type NodeCategory } from "@/lib/nodes";

const ICONS: Record<string, LucideIcon> = {
  start: Play,
  llm: Sparkles,
  agent: Bot,
  http: Globe,
  knowledge: BookOpen,
  calculator: Calculator,
  json_transform: Braces,
  condition: GitBranch,
  loop: Repeat,
  approval: UserCheck,
  output: Flag,
  note: StickyNote,
};

/** The category colours the chip, so a glance tells model calls from tools from logic. */
const CATEGORY: Record<NodeCategory, string> = {
  io: "bg-muted text-foreground",
  ai: "bg-accent text-accent-foreground",
  tool: "bg-info-soft text-info",
  logic: "bg-success-soft text-success",
  human: "bg-warning-soft text-warning",
  canvas: "bg-muted text-muted-foreground",
};

export function NodeIcon({ type, className }: { type: string; className?: string }) {
  const Icon = ICONS[type] ?? Blocks;
  const category = definitionOf(type)?.category ?? "io";
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg [&_svg]:size-4",
        CATEGORY[category],
        className,
      )}
      aria-hidden
    >
      <Icon />
    </span>
  );
}
