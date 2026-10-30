"use client";

import { History } from "lucide-react";

import { Card } from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { formatRelative } from "@/lib/format";
import { useAudit } from "@/lib/queries";
import type { AuditEvent } from "@/lib/types";

const name = (e: AuditEvent, key = "name", fallback = "") => String(e.details[key] ?? fallback);

const LABELS: Record<string, (e: AuditEvent) => string> = {
  "workspace.created": () => "created the workspace",
  "workspace.updated": () => "updated workspace settings",
  "member.added": (e) => `added ${name(e, "email", "a member")} as ${name(e, "role", "member")}`,
  "member.role_changed": (e) => `changed a member's role to ${name(e, "role")}`,
  "member.removed": () => "removed a member",
  "flow.created": (e) => `created the flow ${name(e)}`,
  "flow.imported": (e) => `imported the flow ${name(e)}`,
  "flow.updated": (e) => `updated the flow ${name(e)}`,
  "flow.published": (e) => `published ${name(e)} version ${name(e, "version")}`,
  "flow.restored": (e) => `restored version ${name(e, "version")} into a draft`,
  "flow.duplicated": (e) => `duplicated a flow as ${name(e)}`,
  "flow.deleted": (e) => `deleted the flow ${name(e)}`,
  "webhook.enabled": () => "enabled a flow's webhook",
  "webhook.rotated": () => "rotated a webhook signing secret",
  "webhook.disabled": () => "disabled a flow's webhook",
  "run.cancelled": () => "cancelled a run",
  "approval.decided": (e) =>
    e.details.title
      ? `${name(e, "decision", "decided")} "${name(e, "title")}"`
      : `${name(e, "decision", "decided")} a review`,
  "approval.expired": (e) =>
    e.details.title ? `let "${name(e, "title")}" expire` : "let a review expire",
  "knowledge_base.created": (e) => `created the knowledge base ${name(e)}`,
  "knowledge_base.updated": (e) => `updated the knowledge base ${name(e)}`,
  "knowledge_base.deleted": (e) => `deleted the knowledge base ${name(e)}`,
  "knowledge_document.uploaded": (e) => `uploaded ${name(e, "title", "a document")}`,
  "knowledge_document.deleted": (e) => `deleted ${name(e, "title", "a document")}`,
  "secret.created": (e) => `stored the secret ${name(e)}`,
  "secret.updated": (e) => `updated the secret ${name(e)}`,
  "secret.deleted": (e) => `deleted the secret ${name(e)}`,
  "api_key.created": (e) => `created the API key ${name(e)}`,
  "api_key.revoked": (e) => `revoked the API key ${name(e)}`,
};

export function ActivityPanel({ workspace }: { workspace: string }) {
  const audit = useAudit(workspace);
  if (audit.isLoading) return <Skeleton className="h-40" />;
  const events = audit.data?.items ?? [];
  return (
    <Card>
      {events.length ? (
        <ol className="divide-border divide-y">
          {events.map((event) => (
            <li
              key={event.id}
              className="flex items-start justify-between gap-4 px-5 py-3 text-[13px]"
            >
              <p>
                <span className="font-medium">{event.actor_name ?? "An API key"}</span>{" "}
                <span className="text-muted-foreground">
                  {(LABELS[event.action] ?? (() => event.action))(event)}
                </span>
              </p>
              <time dateTime={event.created_at} className="text-subtle shrink-0 text-xs">
                {formatRelative(event.created_at)}
              </time>
            </li>
          ))}
        </ol>
      ) : (
        <EmptyState icon={<History />} title="No activity yet" />
      )}
    </Card>
  );
}
