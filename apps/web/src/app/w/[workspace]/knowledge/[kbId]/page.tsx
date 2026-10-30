"use client";

import { ArrowLeft, Download, FileText, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { UploadZone } from "@/components/knowledge/upload-zone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton, Spinner } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { PageBody } from "@/components/ui/page";
import { apiFile, saveText, ws } from "@/lib/api";
import { plural } from "@/lib/describe";
import { formatBytes, formatRelative } from "@/lib/format";
import { highlightParts } from "@/lib/highlight";
import {
  canEdit,
  useCurrentWorkspace,
  useDocumentActions,
  useDocuments,
  useKnowledgeActions,
  useKnowledgeBase,
} from "@/lib/queries";

function SearchTester({ workspace, kbId }: { workspace: string; kbId: string }) {
  const actions = useDocumentActions(workspace, kbId);
  const [query, setQuery] = useState("");
  const result = actions.search.data;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) actions.search.mutate({ query, top_k: 5 });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Try a search</CardTitle>
          <CardDescription>
            Exactly what a Knowledge search step returns for this query.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <form onSubmit={submit} className="flex gap-2">
          <div className="relative flex-1">
            <Search
              className="text-subtle pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="How many vacation days do we get?"
              className="pl-9"
              aria-label="Search query"
            />
          </div>
          <Button type="submit" disabled={!query.trim() || actions.search.isPending}>
            {actions.search.isPending ? <Spinner className="text-primary-foreground" /> : null}
            Search
          </Button>
        </form>
        {actions.search.error ? <ErrorNotice message={actions.search.error.message} /> : null}
        {result ? (
          result.results.length ? (
            <ol className="space-y-2" data-testid="search-results">
              {result.results.map((hit, index) => (
                <li key={hit.chunk_id} className="border-border rounded-lg border p-3">
                  <p className="flex items-center gap-2 text-[12.5px]">
                    <Badge tone="primary">[{index + 1}]</Badge>
                    <span className="font-medium">{hit.title}</span>
                    {hit.heading ? (
                      <span className="text-muted-foreground truncate">&rsaquo; {hit.heading}</span>
                    ) : null}
                    <span className="text-subtle ml-auto tabular-nums">{hit.score.toFixed(3)}</span>
                  </p>
                  <p className="text-muted-foreground mt-1.5 text-[12.5px] leading-relaxed">
                    {highlightParts(hit.snippet).map((part, i) =>
                      part.mark ? (
                        <mark key={i} className="bg-accent text-accent-foreground rounded px-0.5">
                          {part.text}
                        </mark>
                      ) : (
                        <span key={i}>{part.text}</span>
                      ),
                    )}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-muted-foreground text-[13px]">No passage matches that query.</p>
          )
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function KnowledgeBasePage() {
  const { workspace, kbId } = useParams<{ workspace: string; kbId: string }>();
  const router = useRouter();
  const current = useCurrentWorkspace(workspace);
  const kb = useKnowledgeBase(workspace, kbId);
  const documents = useDocuments(workspace, kbId);
  const actions = useDocumentActions(workspace, kbId);
  const kbActions = useKnowledgeActions(workspace);
  const editable = canEdit(current?.role);

  if (kb.error) {
    return (
      <EmptyState
        className="h-full"
        title="Knowledge base not found"
        description={kb.error.message}
        action={
          <Button asChild variant="secondary">
            <Link href={`/w/${workspace}/knowledge`}>Back to knowledge</Link>
          </Button>
        }
      />
    );
  }

  return (
    <PageBody>
      <header className="flex flex-wrap items-start gap-3 pb-6">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back to knowledge">
          <Link href={`/w/${workspace}/knowledge`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="min-h-8 text-[22px] font-semibold tracking-tight">{kb.data?.name}</h1>
          <p className="text-muted-foreground mt-1 text-[13.5px]">
            {kb.data ? kb.data.description || "No description" : null}
          </p>
        </div>
        {editable ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              if (!window.confirm(`Delete ${kb.data?.name} and all its documents?`)) return;
              await kbActions.remove.mutateAsync(kbId);
              router.replace(`/w/${workspace}/knowledge`);
            }}
          >
            <Trash2 /> Delete
          </Button>
        ) : null}
      </header>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          {editable ? <UploadZone workspace={workspace} kbId={kbId} /> : null}
          <Card className="overflow-hidden">
            {!documents.data ? (
              <Skeleton className="m-4 h-40" />
            ) : documents.data.items.length === 0 ? (
              <EmptyState
                icon={<FileText />}
                title="No documents yet"
                description="Upload Markdown or text files to make them searchable."
              />
            ) : (
              <ul className="divide-border divide-y" data-testid="documents">
                {documents.data.items.map((document) => (
                  <li key={document.id} className="flex items-center gap-3 px-4 py-3">
                    <span className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-lg">
                      <FileText className="size-4" aria-hidden />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13.5px] font-medium">{document.title}</p>
                      <p className="text-muted-foreground truncate text-xs">
                        {document.filename} &middot; {formatBytes(document.size_bytes)} &middot;{" "}
                        {plural(document.chunk_count, "passage")} &middot;{" "}
                        {formatRelative(document.created_at)}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Download ${document.filename}`}
                      onClick={async () => {
                        const file = await apiFile(
                          `${ws(workspace)}/knowledge-bases/${kbId}/documents/${document.id}/content`,
                        );
                        saveText(
                          file.text,
                          file.filename ?? document.filename,
                          document.content_type,
                        );
                      }}
                    >
                      <Download />
                    </Button>
                    {editable ? (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Delete ${document.filename}`}
                        onClick={async () => {
                          await actions.remove.mutateAsync(document.id);
                          toast.success(`${document.title} deleted`);
                        }}
                      >
                        <Trash2 />
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="self-start">
          <SearchTester workspace={workspace} kbId={kbId} />
        </div>
      </div>
    </PageBody>
  );
}
