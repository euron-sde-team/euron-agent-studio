"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { useModels, useUpdateWorkspace } from "@/lib/queries";
import type { Workspace } from "@/lib/types";

export function GeneralPanel({ workspace, editable }: { workspace: Workspace; editable: boolean }) {
  const update = useUpdateWorkspace(workspace.slug);
  const models = useModels();
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [model, setModel] = useState(workspace.settings.default_model);
  const [retention, setRetention] = useState(String(workspace.settings.run_retention_days));

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await update.mutateAsync({
        name,
        description,
        settings: { default_model: model, run_retention_days: Number(retention) || 90 },
      });
      toast.success("Workspace updated");
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  return (
    <Card>
      <CardContent>
        <form onSubmit={submit} className="max-w-xl space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="settings-name">Name</Label>
            <Input
              id="settings-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!editable}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="settings-description">Description</Label>
            <Textarea
              id="settings-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!editable}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="settings-model">Default model</Label>
              <NativeSelect
                id="settings-model"
                value={model}
                disabled={!editable}
                onChange={(e) => setModel(e.target.value)}
              >
                {(models.data ?? [{ ref: model, label: model, provider: "" }]).map((m) => (
                  <option key={m.ref} value={m.ref}>
                    {m.label}
                  </option>
                ))}
              </NativeSelect>
              <FieldHint>New Prompt and Agent steps start with it.</FieldHint>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="settings-retention">Keep run history for (days)</Label>
              <Input
                id="settings-retention"
                type="number"
                min={1}
                max={3650}
                value={retention}
                disabled={!editable}
                onChange={(e) => setRetention(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Address</Label>
            <FieldHint>
              This workspace lives at <code className="font-mono">/w/{workspace.slug}</code>. API
              calls accept the slug or the id <code className="font-mono">{workspace.id}</code>.
            </FieldHint>
          </div>
          {editable ? (
            <Button type="submit" disabled={update.isPending || !name.trim()}>
              Save changes
            </Button>
          ) : (
            <FieldHint>Only owners can change workspace settings.</FieldHint>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
