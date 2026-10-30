"use client";

import { ArrowRight, BookOpen, Sparkles } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { GraphView } from "@/components/flows/graph-view";
import { NodeIcon } from "@/components/node-icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { definitionOf } from "@/lib/nodes";
import { canEdit, useCreateFlow, useCurrentWorkspace, useTemplates } from "@/lib/queries";

export default function TemplatesPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const router = useRouter();
  const current = useCurrentWorkspace(workspace);
  const templates = useTemplates();
  const create = useCreateFlow(workspace);
  const [busy, setBusy] = useState<string | null>(null);
  const editable = canEdit(current?.role);

  async function use(slug: string, name: string) {
    setBusy(slug);
    try {
      const flow = await create.mutateAsync({ name, template: slug });
      toast.success(`${name} added to your flows`);
      router.push(`/w/${workspace}/flows/${flow.id}`);
    } catch (error) {
      toast.error((error as Error).message);
      setBusy(null);
    }
  }

  return (
    <PageBody>
      <PageHeader
        title="Templates"
        description="Ready-made flows with sample inputs and the knowledge they need. Use one, run it, then make it yours."
      />
      {templates.error ? <ErrorNotice message={templates.error.message} /> : null}
      {!templates.data ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {templates.data.map((template) => (
            <Card
              key={template.slug}
              className="flex flex-col overflow-hidden"
              data-testid={`gallery-${template.slug}`}
            >
              <GraphView
                graph={template.graph}
                preview
                className="bg-canvas border-border h-56 border-b"
              />
              <div className="flex flex-1 flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[16px] font-semibold tracking-tight">{template.name}</h2>
                    <p className="text-subtle text-[12px] font-medium tracking-wide uppercase">
                      {template.category}
                    </p>
                  </div>
                  <Badge tone="outline">{template.node_count} steps</Badge>
                </div>
                <p className="text-muted-foreground mt-2 text-[13px]">{template.description}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {template.node_types
                    .filter((t) => t !== "note")
                    .map((type) => (
                      <span
                        key={type}
                        className="border-border text-muted-foreground inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11.5px]"
                      >
                        <NodeIcon type={type} className="size-4 rounded [&_svg]:size-2.5" />
                        {definitionOf(type)?.label ?? type}
                      </span>
                    ))}
                </div>
                {template.requires_knowledge.length ? (
                  <p className="text-muted-foreground mt-3 flex items-center gap-1.5 text-[12.5px]">
                    <BookOpen className="size-3.5" aria-hidden />
                    Installs the {template.requires_knowledge.join(", ")} knowledge base
                  </p>
                ) : null}
                <div className="mt-auto flex items-center justify-between gap-3 pt-4">
                  <span className="text-muted-foreground flex items-center gap-1.5 text-[12px]">
                    <Sparkles className="size-3.5" aria-hidden /> Runs offline with its sample
                  </span>
                  {editable ? (
                    <Button
                      onClick={() => void use(template.slug, template.name)}
                      disabled={busy !== null}
                      data-testid={`use-${template.slug}`}
                    >
                      Use template <ArrowRight />
                    </Button>
                  ) : null}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </PageBody>
  );
}
