"use client";

import { CloudUpload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { Spinner } from "@/components/ui/feedback";
import { cn } from "@/lib/cn";
import { useDocumentActions, useSystemInfo } from "@/lib/queries";

const ACCEPT = ".md,.markdown,.txt";

export function UploadZone({ workspace, kbId }: { workspace: string; kbId: string }) {
  const system = useSystemInfo();
  const actions = useDocumentActions(workspace, kbId);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  async function send(files: File[]) {
    try {
      const documents = await actions.upload.mutateAsync(files);
      toast.success(
        documents.length === 1
          ? `${documents[0]!.title} is searchable now`
          : `${documents.length} documents are searchable now`,
      );
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length) void send(files);
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        "border-input bg-card/60 flex items-center gap-4 rounded-xl border border-dashed px-4 py-3.5 transition-colors",
        over && "border-primary bg-accent/50",
      )}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-label="Documents to upload"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length) void send(files);
        }}
      />
      <span className="bg-accent text-accent-foreground flex size-9 items-center justify-center rounded-xl">
        {actions.upload.isPending ? (
          <Spinner className="text-accent-foreground" />
        ) : (
          <CloudUpload className="size-4" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium">
          Drop Markdown or text files here or{" "}
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="text-primary font-semibold hover:underline"
          >
            browse
          </button>
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">
          .md and .txt, up to {system.data?.limits.max_document_kb ?? 2048} KB each. The same file
          twice is stored once.
        </p>
      </div>
    </div>
  );
}
