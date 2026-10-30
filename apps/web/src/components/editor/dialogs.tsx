"use client";

import { Check, Copy, Download, KeyRound, RotateCcw, Webhook } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { ErrorNotice, Skeleton, Spinner } from "@/components/ui/feedback";
import { FieldHint, Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiFile, saveText, ws } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatRelative, slugify } from "@/lib/format";
import { useFlowActions, useVersions, useWebhook } from "@/lib/queries";
import { runtimeEnv } from "@/lib/runtime-env";
import type { Flow, GraphNode, InputField, Issue } from "@/lib/types";

function CopyBlock({ value, label, wrap }: { value: string; label: string; wrap?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="border-border bg-muted/60 relative rounded-lg border">
      <pre
        aria-label={label}
        tabIndex={0}
        className={cn(
          "scroll-quiet max-h-72 overflow-auto p-3 pr-20 font-mono text-[12px] leading-relaxed",
          wrap && "break-all whitespace-pre-wrap",
        )}
      >
        {value}
      </pre>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        className="absolute top-2 right-2"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------------------

function initialValue(field: InputField, sample: Record<string, unknown>): string {
  const value = sample[field.name] ?? field.default;
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function parseValue(field: InputField, raw: string): unknown {
  if (field.type === "string") return raw;
  if (!raw.trim()) return undefined;
  if (field.type === "number" || field.type === "integer") return Number(raw);
  if (field.type === "boolean") return raw === "true";
  return JSON.parse(raw);
}

export function RunDialog({
  open,
  onOpenChange,
  start,
  published,
  pending,
  error,
  onRun,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  start: GraphNode | undefined;
  published: boolean;
  pending: boolean;
  error: string | null;
  onRun: (inputs: Record<string, unknown>, version: "draft" | "published") => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Run this flow"
        description="The run starts at once; watch each step on the canvas."
        className="w-[min(94vw,36rem)]"
      >
        <RunForm
          start={start}
          published={published}
          pending={pending}
          error={error}
          onRun={onRun}
          onCancel={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function RunForm({
  start,
  published,
  pending,
  error,
  onRun,
  onCancel,
}: {
  start: GraphNode | undefined;
  published: boolean;
  pending: boolean;
  error: string | null;
  onRun: (inputs: Record<string, unknown>, version: "draft" | "published") => void;
  onCancel: () => void;
}) {
  const fields = Array.isArray(start?.config.inputs) ? (start.config.inputs as InputField[]) : [];
  const sample = (start?.config.sample ?? {}) as Record<string, unknown>;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initialValue(f, sample)])),
  );
  const [version, setVersion] = useState<"draft" | "published">("draft");
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const inputs: Record<string, unknown> = {};
    try {
      for (const field of fields) {
        const value = parseValue(field, values[field.name] ?? "");
        if (value !== undefined) inputs[field.name] = value;
      }
    } catch {
      setProblem("One of the JSON inputs is not valid JSON.");
      return;
    }
    onRun(inputs, version);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="scroll-quiet max-h-[55vh] space-y-3 overflow-y-auto pr-1">
        {fields.length === 0 ? (
          <p className="text-muted-foreground text-[13px]">This flow takes no inputs.</p>
        ) : null}
        {fields.map((field) => {
          const id = `run-input-${field.name}`;
          const long =
            field.type === "object" ||
            field.type === "array" ||
            (values[field.name]?.length ?? 0) > 80;
          return (
            <div key={field.name} className="space-y-1.5">
              <Label htmlFor={id}>
                {field.name}
                {field.required === false ? (
                  <span className="text-subtle font-normal"> (optional)</span>
                ) : null}
              </Label>
              {long ? (
                <Textarea
                  id={id}
                  rows={field.type === "string" ? 5 : 4}
                  className={field.type === "string" ? undefined : "font-mono text-[12.5px]"}
                  value={values[field.name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                />
              ) : (
                <Input
                  id={id}
                  value={values[field.name] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                />
              )}
              {field.description ? <FieldHint>{field.description}</FieldHint> : null}
            </div>
          );
        })}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="run-version">Version</Label>
        <NativeSelect
          id="run-version"
          value={version}
          onChange={(e) => setVersion(e.target.value as "draft" | "published")}
        >
          <option value="draft">The draft on the canvas</option>
          <option value="published" disabled={!published}>
            The published version{published ? "" : " (publish first)"}
          </option>
        </NativeSelect>
      </div>
      {problem || error ? <ErrorNotice message={problem ?? error ?? ""} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending} data-testid="start-run">
          {pending ? <Spinner className="text-primary-foreground" /> : null}
          Run
        </Button>
      </DialogFooter>
    </form>
  );
}

// ---------------------------------------------------------------------------------------
// Publish and versions
// ---------------------------------------------------------------------------------------

export function PublishDialog({
  open,
  onOpenChange,
  flow,
  errors,
  pending,
  error,
  onPublish,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flow: Flow;
  errors: Issue[];
  pending: boolean;
  error: string | null;
  onPublish: (notes: string) => void;
}) {
  const [notes, setNotes] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Publish version ${flow.latest_version + 1}`}
        description="Published versions are what the API, webhooks and Run published use. The draft stays editable."
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onPublish(notes);
          }}
          className="space-y-4"
        >
          {errors.length ? (
            <ErrorNotice
              message={`Fix ${errors.length} problem${errors.length === 1 ? "" : "s"} first: ${errors[0]!.message}`}
            />
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="publish-notes">What changed</Label>
            <Textarea
              id="publish-notes"
              rows={3}
              value={notes}
              placeholder="Tightened the triage prompt; refunds now need approval."
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          {error ? <ErrorNotice message={error} /> : null}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={pending || errors.length > 0}
              data-testid="confirm-publish"
            >
              Publish
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function VersionsDialog({
  open,
  onOpenChange,
  workspace,
  flowId,
  readOnly,
  pending,
  onRestore,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  flowId: string;
  readOnly: boolean;
  pending: boolean;
  onRestore: (version: number) => void;
}) {
  const versions = useVersions(workspace, flowId, open);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Versions"
        description="Every publish is kept. Restoring copies a version into the draft."
        className="w-[min(94vw,34rem)]"
      >
        {versions.isLoading ? (
          <Skeleton className="h-32" />
        ) : versions.data?.items.length ? (
          <ol className="divide-border max-h-[55vh] divide-y overflow-y-auto">
            {versions.data.items.map((version) => (
              <li key={version.id} className="flex items-start gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-[13.5px] font-medium">
                    Version {version.version}
                    {version.published ? <Badge tone="success">Live</Badge> : null}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {version.created_by_name ?? "Someone"} &middot;{" "}
                    {formatRelative(version.created_at)} &middot; {version.node_count} steps
                  </p>
                  {version.notes ? <p className="mt-1 text-[12.5px]">{version.notes}</p> : null}
                </div>
                {!readOnly ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={pending}
                    onClick={() => onRestore(version.version)}
                  >
                    <RotateCcw /> Restore
                  </Button>
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground text-[13px]">Nothing published yet.</p>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------
// Export to Python
// ---------------------------------------------------------------------------------------

export function ExportDialog({
  open,
  onOpenChange,
  workspace,
  flow,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  flow: Flow;
}) {
  const [version, setVersion] = useState<"draft" | "published">("draft");
  const exported = useQuery({
    queryKey: ["export-python", workspace, flow.id, version],
    queryFn: () => apiFile(`${ws(workspace)}/flows/${flow.id}/export/python?version=${version}`),
    enabled: open,
    staleTime: 0,
    gcTime: 0,
  });
  const script = exported.data
    ? { text: exported.data.text, filename: exported.data.filename ?? `${slugify(flow.name)}.py` }
    : null;
  const error = exported.error?.message ?? null;

  const lines = script?.text.split("\n").length ?? 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Export to Python"
        description="A standalone script that runs the same steps with httpx: same templates, same model calls, same order."
        className="w-[min(96vw,56rem)]"
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="Version to export"
              className="w-auto"
              value={version}
              onChange={(e) => setVersion(e.target.value as "draft" | "published")}
            >
              <option value="draft">Draft</option>
              <option value="published" disabled={!flow.published_version}>
                Published version{flow.published_version ? ` ${flow.published_version}` : ""}
              </option>
            </NativeSelect>
            {script ? (
              <span className="text-muted-foreground text-xs">
                <code className="font-mono">{script.filename}</code> &middot; {lines} lines
              </span>
            ) : null}
            <Button
              className="ml-auto"
              size="sm"
              disabled={!script}
              onClick={() => script && saveText(script.text, script.filename, "text/x-python")}
              data-testid="download-python"
            >
              <Download /> Download
            </Button>
          </div>
          {error ? <ErrorNotice message={error} /> : null}
          {script ? (
            <CopyBlock value={script.text} label="Python script" />
          ) : !error ? (
            <Skeleton className="h-72" />
          ) : null}
          <div className="text-muted-foreground space-y-1 text-[12.5px]">
            <p>Run it anywhere Python 3.10+ runs:</p>
            <CopyBlock
              label="How to run the script"
              value={`pip install httpx jmespath\nexport AGENTSTUDIO_URL=${runtimeEnv().apiUrl}\nexport AGENTSTUDIO_API_KEY=agst_...   # for the offline model and knowledge search\npython ${script?.filename ?? "flow.py"} --input-file inputs.json --approve`}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------
// Triggers: API and webhook
// ---------------------------------------------------------------------------------------

export function TriggersDialog({
  open,
  onOpenChange,
  workspace,
  flow,
  canManage,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  flow: Flow;
  canManage: boolean;
}) {
  const hook = useWebhook(workspace, flow.id);
  const [secret, setSecret] = useState<string | null>(null);
  const [override, setWebhook] = useState<typeof flow.webhook | null>(null);
  const webhook = override ?? flow.webhook;
  const apiUrl = runtimeEnv().apiUrl;
  const start = flow.graph.nodes.find((n) => n.type === "start");
  const sample = JSON.stringify({
    inputs: (start?.config.sample as Record<string, unknown>) ?? {},
    version: "published",
  });
  const curl = `curl -s -X POST "${apiUrl}${ws(workspace)}/flows/${flow.id}/runs?wait=30" \\\n  -H "authorization: Bearer $AGENTSTUDIO_API_KEY" \\\n  -H "content-type: application/json" \\\n  -d '${sample.replace(/'/g, "'\\''")}'`;
  const signing = `import hashlib, hmac, json, time, httpx

body = json.dumps(${JSON.stringify((start?.config.sample as Record<string, unknown>) ?? {})}).encode()
stamp = str(int(time.time()))
signature = hmac.new(SECRET.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
httpx.post("${webhook.url ?? "<webhook url>"}", content=body, headers={
    "content-type": "application/json",
    "${webhook.signature_header}": f"t={stamp},v1={signature}",
})`;

  async function enable() {
    try {
      const result = await hook.enable.mutateAsync();
      setWebhook(result);
      setSecret(result.secret);
      toast.success(webhook.enabled ? "Signing secret rotated" : "Webhook enabled");
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  async function disable() {
    try {
      setWebhook(await hook.disable.mutateAsync());
      setSecret(null);
      toast.success("Webhook disabled");
    } catch (error) {
      toast.error((error as Error).message);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setSecret(null);
      }}
    >
      <DialogContent
        title="Triggers"
        description="Start runs of the published version from your own code or another system."
        className="w-[min(96vw,44rem)]"
      >
        <Tabs defaultValue="api">
          <TabsList>
            <TabsTrigger value="api">
              <KeyRound className="mr-1 inline size-3.5" aria-hidden /> API
            </TabsTrigger>
            <TabsTrigger value="webhook">
              <Webhook className="mr-1 inline size-3.5" aria-hidden /> Webhook
            </TabsTrigger>
          </TabsList>
          <TabsContent value="api" className="space-y-3">
            <p className="text-muted-foreground text-[13px]">
              Call the API with a workspace key. <code className="font-mono">wait</code> holds the
              response until the run finishes or pauses for approval.
            </p>
            <CopyBlock value={curl} label="API request" />
            <p className="text-muted-foreground text-[12.5px]">
              Create keys in{" "}
              <Link
                href={`/w/${workspace}/settings`}
                className="text-primary font-medium hover:underline"
              >
                Settings, API keys
              </Link>
              . Follow a run live at <code className="font-mono">/runs/&#123;id&#125;/events</code>{" "}
              (server-sent events).
            </p>
          </TabsContent>
          <TabsContent value="webhook" className="space-y-3">
            {!flow.published_version ? (
              <p className="bg-warning-soft text-warning rounded-lg px-3 py-2 text-[12.5px]">
                Webhooks run the published version: publish the flow before you rely on one.
              </p>
            ) : null}
            {webhook.enabled && webhook.url ? (
              <>
                <div className="space-y-1.5">
                  <Label>URL</Label>
                  <CopyBlock value={webhook.url} label="Webhook URL" wrap />
                </div>
                {secret ? (
                  <div className="space-y-1.5">
                    <Label>Signing secret (shown once)</Label>
                    <CopyBlock value={secret} label="Signing secret" wrap />
                  </div>
                ) : (
                  <FieldHint>
                    The signing secret was shown when the webhook was enabled. Rotate it to get a
                    new one.
                  </FieldHint>
                )}
                <div className="space-y-1.5">
                  <Label>Sign each delivery</Label>
                  <CopyBlock value={signing} label="Signing example" />
                  <FieldHint>
                    Deliveries older than five minutes and repeated signatures are refused. The JSON
                    body becomes the run&apos;s inputs.
                  </FieldHint>
                </div>
                {canManage ? (
                  <DialogFooter>
                    <Button
                      variant="ghost"
                      disabled={hook.disable.isPending}
                      onClick={() => void disable()}
                    >
                      Disable
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={hook.enable.isPending}
                      onClick={() => void enable()}
                    >
                      Rotate secret
                    </Button>
                  </DialogFooter>
                ) : null}
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-muted-foreground text-[13px]">
                  A signed webhook lets another system start this flow with a POST. Each delivery is
                  checked with an HMAC-SHA256 signature over its timestamp and body.
                </p>
                {canManage ? (
                  <Button
                    disabled={hook.enable.isPending}
                    onClick={() => void enable()}
                    data-testid="enable-webhook"
                  >
                    <Webhook /> Enable webhook
                  </Button>
                ) : (
                  <FieldHint>Editors and owners can enable the webhook.</FieldHint>
                )}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------
// Flow details
// ---------------------------------------------------------------------------------------

export function DetailsDialog({
  open,
  onOpenChange,
  workspace,
  flow,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  flow: Flow;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Flow details">
        <DetailsForm workspace={workspace} flow={flow} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function DetailsForm({
  workspace,
  flow,
  onDone,
}: {
  workspace: string;
  flow: Flow;
  onDone: () => void;
}) {
  const actions = useFlowActions(workspace, flow.id);
  const [name, setName] = useState(flow.name);
  const [description, setDescription] = useState(flow.description);
  const [tags, setTags] = useState(flow.tags.join(", "));
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        await actions.update.mutateAsync({
          name,
          description,
          tags: tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        });
        onDone();
        toast.success("Flow details saved");
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="flow-name">Name</Label>
        <Input id="flow-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="flow-description">Description</Label>
        <Textarea
          id="flow-description"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="flow-tags">Tags</Label>
        <Input
          id="flow-tags"
          value={tags}
          placeholder="support, billing"
          onChange={(e) => setTags(e.target.value)}
        />
        <FieldHint>Comma separated. Used to filter the flow list.</FieldHint>
      </div>
      {actions.update.error ? <ErrorNotice message={actions.update.error.message} /> : null}
      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!name.trim() || actions.update.isPending}>
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}
