"use client";

import { Library, Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { Input, Label, Textarea } from "@/components/ui/input";
import { PageBody, PageHeader } from "@/components/ui/page";
import { formatNumber, formatRelative } from "@/lib/format";
import {
  canEdit,
  useCurrentWorkspace,
  useKnowledgeActions,
  useKnowledgeBases,
} from "@/lib/queries";

function CreateForm({ workspace, onDone }: { workspace: string; onDone: () => void }) {
  const router = useRouter();
  const actions = useKnowledgeActions(workspace);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const kb = await actions.create.mutateAsync({ name, description });
    onDone();
    router.push(`/w/${workspace}/knowledge/${kb.id}`);
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="kb-name">Name</Label>
        <Input
          id="kb-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Product handbook"
          required
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="kb-description">Description</Label>
        <Textarea
          id="kb-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What it covers, so people pick the right one in a flow"
        />
      </div>
      {actions.create.error ? <ErrorNotice message={actions.create.error.message} /> : null}
      <DialogFooter>
        <Button type="submit" disabled={!name.trim() || actions.create.isPending}>
          Create
        </Button>
      </DialogFooter>
    </form>
  );
}

export default function KnowledgePage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const kbs = useKnowledgeBases(workspace);
  const [creating, setCreating] = useState(false);
  const editable = canEdit(current?.role);
  const items = kbs.data?.items;

  return (
    <PageBody>
      <PageHeader
        title="Knowledge"
        description="Markdown and text documents that Knowledge search steps and agents search, with citations."
        actions={
          editable ? (
            <Button onClick={() => setCreating(true)} data-testid="new-kb">
              <Plus /> New knowledge base
            </Button>
          ) : null
        }
      />
      {kbs.error ? <ErrorNotice message={kbs.error.message} /> : null}
      {!items ? (
        <Skeleton className="h-64" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Library />}
            title="No knowledge bases yet"
            description="Templates that search documents install theirs; you can also create one and upload files."
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((kb) => (
            <Link
              key={kb.id}
              href={`/w/${workspace}/knowledge/${kb.id}`}
              className="group"
              data-testid="kb-link"
            >
              <Card className="group-hover:border-primary/40 h-full p-5 transition-colors">
                <div className="flex items-start gap-3">
                  <span className="bg-info-soft text-info flex size-9 items-center justify-center rounded-lg">
                    <Library className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[14.5px] font-semibold tracking-tight">{kb.name}</p>
                    <p className="text-muted-foreground line-clamp-2 text-[12.5px]">
                      {kb.description || "No description"}
                    </p>
                  </div>
                </div>
                <dl className="text-muted-foreground mt-4 flex gap-5 text-[12.5px]">
                  <div>
                    <dt className="text-subtle text-[11px] uppercase">Documents</dt>
                    <dd className="text-foreground text-[15px] font-semibold tabular-nums">
                      {formatNumber(kb.document_count)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-subtle text-[11px] uppercase">Passages</dt>
                    <dd className="text-foreground text-[15px] font-semibold tabular-nums">
                      {formatNumber(kb.chunk_count)}
                    </dd>
                  </div>
                  <div className="ml-auto self-end">updated {formatRelative(kb.updated_at)}</div>
                </dl>
              </Card>
            </Link>
          ))}
        </div>
      )}
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent title="New knowledge base">
          <CreateForm workspace={workspace} onDone={() => setCreating(false)} />
        </DialogContent>
      </Dialog>
    </PageBody>
  );
}
