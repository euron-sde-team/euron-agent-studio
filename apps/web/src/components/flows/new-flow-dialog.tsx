"use client";

import { FileUp, Plus, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { NodeIcon } from "@/components/node-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { FieldHint, Input, Label, Textarea } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import { useCreateFlow, useImportFlow, useTemplates } from "@/lib/queries";
import type { FlowDocument } from "@/lib/types";

function BlankForm({ workspace, onDone }: { workspace: string; onDone: () => void }) {
  const router = useRouter();
  const create = useCreateFlow(workspace);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const flow = await create.mutateAsync({ name, description });
    onDone();
    router.push(`/w/${workspace}/flows/${flow.id}`);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="new-flow-name">Name</Label>
        <Input
          id="new-flow-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Refund requests"
          required
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="new-flow-description">Description</Label>
        <Textarea
          id="new-flow-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What does it do, and for whom?"
        />
        <FieldHint>It starts as Start connected to Output: add steps in between.</FieldHint>
      </div>
      {create.error ? <ErrorNotice message={create.error.message} /> : null}
      <DialogFooter>
        <Button type="submit" disabled={!name.trim() || create.isPending} data-testid="create-flow">
          Create flow
        </Button>
      </DialogFooter>
    </form>
  );
}

function TemplatePicker({ workspace, onDone }: { workspace: string; onDone: () => void }) {
  const router = useRouter();
  const templates = useTemplates();
  const create = useCreateFlow(workspace);
  const [chosen, setChosen] = useState<string | null>(null);

  async function use(slug: string, name: string) {
    setChosen(slug);
    try {
      const flow = await create.mutateAsync({ name, template: slug });
      onDone();
      router.push(`/w/${workspace}/flows/${flow.id}`);
    } catch (error) {
      toast.error((error as Error).message);
      setChosen(null);
    }
  }

  return (
    <ul className="scroll-quiet grid max-h-[58vh] gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
      {(templates.data ?? []).map((template) => (
        <li key={template.slug}>
          <button
            type="button"
            disabled={create.isPending}
            onClick={() => void use(template.slug, template.name)}
            className={cn(
              "border-border hover:border-primary/50 hover:bg-muted/40 h-full w-full rounded-xl border p-3 text-left transition-colors",
              chosen === template.slug && "border-primary",
            )}
            data-testid={`template-${template.slug}`}
          >
            <p className="text-[13.5px] font-semibold">{template.name}</p>
            <p className="text-muted-foreground mt-0.5 line-clamp-2 text-[12px]">
              {template.description}
            </p>
            <span className="mt-2 flex items-center gap-1">
              {template.node_types
                .filter((t) => t !== "start" && t !== "output" && t !== "note")
                .slice(0, 6)
                .map((type) => (
                  <NodeIcon key={type} type={type} className="size-5 rounded-md [&_svg]:size-3" />
                ))}
              <Badge tone="outline" className="ml-auto">
                {template.node_count} steps
              </Badge>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ImportForm({ workspace, onDone }: { workspace: string; onDone: () => void }) {
  const router = useRouter();
  const importFlow = useImportFlow(workspace);
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function load(file: File) {
    setProblem(null);
    let document: FlowDocument;
    try {
      document = JSON.parse(await file.text()) as FlowDocument;
    } catch {
      setProblem("That file is not JSON.");
      return;
    }
    try {
      const flow = await importFlow.mutateAsync(document);
      onDone();
      toast.success(`Imported ${flow.name}`, {
        description: flow.issues.length
          ? `${flow.issues.length} issue(s) to fix, such as knowledge bases that live elsewhere.`
          : undefined,
      });
      router.push(`/w/${workspace}/flows/${flow.id}`);
    } catch (error) {
      setProblem((error as Error).message);
    }
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="border-border hover:border-primary/50 hover:bg-muted/40 flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-10 text-center transition-colors"
      >
        <FileUp className="text-primary size-6" aria-hidden />
        <span className="text-[13.5px] font-medium">Choose an exported flow (.json)</span>
        <span className="text-muted-foreground text-[12px]">
          From Export JSON in any AgentStudio workspace.
        </span>
      </button>
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        className="hidden"
        aria-label="Flow file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void load(file);
          event.target.value = "";
        }}
      />
      {problem ? <ErrorNotice message={problem} /> : null}
    </div>
  );
}

export function NewFlowDialog({
  workspace,
  open,
  onOpenChange,
}: {
  workspace: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const close = () => onOpenChange(false);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New flow"
        description="Start from scratch, from a ready-made template, or from an exported file."
        className="w-[min(94vw,44rem)]"
      >
        <Tabs defaultValue="template">
          <TabsList>
            <TabsTrigger value="template">
              <Sparkles className="mr-1 inline size-3.5" aria-hidden /> From a template
            </TabsTrigger>
            <TabsTrigger value="blank">
              <Plus className="mr-1 inline size-3.5" aria-hidden /> Blank
            </TabsTrigger>
            <TabsTrigger value="import">
              <FileUp className="mr-1 inline size-3.5" aria-hidden /> Import
            </TabsTrigger>
          </TabsList>
          <TabsContent value="template">
            <TemplatePicker workspace={workspace} onDone={close} />
          </TabsContent>
          <TabsContent value="blank">
            <BlankForm workspace={workspace} onDone={close} />
          </TabsContent>
          <TabsContent value="import">
            <ImportForm workspace={workspace} onDone={close} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
