"use client";

import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { FieldHint, Input, Label } from "@/components/ui/input";
import { formatRelative } from "@/lib/format";
import { useSecretActions, useSecrets } from "@/lib/queries";
import type { Secret } from "@/lib/types";

function SecretForm({
  workspace,
  secret,
  onDone,
}: {
  workspace: string;
  secret: Secret | null;
  onDone: () => void;
}) {
  const actions = useSecretActions(workspace);
  const [name, setName] = useState(secret?.name ?? "");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState(secret?.description ?? "");
  const mutation = secret ? actions.update : actions.create;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (secret) {
      await actions.update.mutateAsync({
        name: secret.name,
        description,
        ...(value ? { value } : {}),
      });
      toast.success(`${secret.name} updated`);
    } else {
      await actions.create.mutateAsync({ name, value, description });
      toast.success(`${name} stored`);
    }
    onDone();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="secret-name">Name</Label>
        <Input
          id="secret-name"
          value={name}
          disabled={Boolean(secret)}
          className="font-mono"
          placeholder="CRM_TOKEN"
          onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))}
          required
          autoFocus={!secret}
        />
        <FieldHint>
          Used in flows as <code className="font-mono">{`{{secrets.${name || "NAME"}}}`}</code>
        </FieldHint>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="secret-value">{secret ? "New value (leave empty to keep)" : "Value"}</Label>
        <Input
          id="secret-value"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required={!secret}
          autoFocus={Boolean(secret)}
        />
        <FieldHint>
          Encrypted at rest. Never shown again, masked as [secret:NAME] in every trace.
        </FieldHint>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="secret-description">Description</Label>
        <Input
          id="secret-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Read-only token for the CRM sandbox"
        />
      </div>
      {mutation.error ? <ErrorNotice message={mutation.error.message} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!name || (!secret && !value) || mutation.isPending}>
          {secret ? "Save" : "Store secret"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function SecretsPanel({ workspace, isOwner }: { workspace: string; isOwner: boolean }) {
  const secrets = useSecrets(workspace);
  const actions = useSecretActions(workspace);
  const [editing, setEditing] = useState<Secret | "new" | null>(null);
  const items = secrets.data?.items ?? [];

  return (
    <Card>
      <div className="border-border flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <p className="text-muted-foreground text-[13px]">
          Tokens and passwords your flows send to other systems. Values are write-only.
        </p>
        {isOwner ? (
          <Button size="sm" onClick={() => setEditing("new")}>
            <LockKeyhole /> Add secret
          </Button>
        ) : null}
      </div>
      {secrets.isLoading ? (
        <div className="p-5">
          <Skeleton className="h-10" />
        </div>
      ) : items.length ? (
        <ul className="divide-border divide-y">
          {items.map((secret) => (
            <li key={secret.name} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[13px] font-medium">{secret.name}</p>
                <p className="text-muted-foreground text-xs">
                  {secret.description || "No description"} &middot; updated{" "}
                  {formatRelative(secret.updated_at)} &middot;{" "}
                  {secret.last_used_at
                    ? `used ${formatRelative(secret.last_used_at)}`
                    : "not used yet"}
                </p>
              </div>
              {isOwner ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(secret)}>
                    Replace
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      if (!window.confirm(`Delete ${secret.name}? Flows that use it will fail.`))
                        return;
                      await actions.remove.mutateAsync(secret.name);
                      toast.success(`${secret.name} deleted`);
                    }}
                  >
                    Delete
                  </Button>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={<LockKeyhole />}
          title="No secrets yet"
          description="Store API tokens here and reference them in HTTP steps as {{secrets.NAME}}."
        />
      )}
      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent title={editing === "new" ? "Add a secret" : "Replace a secret"}>
          {editing !== null ? (
            <SecretForm
              workspace={workspace}
              secret={editing === "new" ? null : editing}
              onDone={() => setEditing(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
