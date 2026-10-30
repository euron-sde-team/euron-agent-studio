"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { FlowEditor } from "@/components/editor/editor";
import { Button } from "@/components/ui/button";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { useCurrentWorkspace, useFlow } from "@/lib/queries";

export default function FlowEditorPage() {
  const { workspace, flowId } = useParams<{ workspace: string; flowId: string }>();
  const current = useCurrentWorkspace(workspace);
  const flow = useFlow(workspace, flowId);

  if (flow.error) {
    return (
      <EmptyState
        className="h-full"
        title="Flow not found"
        description={flow.error.message}
        action={
          <Button asChild variant="secondary">
            <Link href={`/w/${workspace}/flows`}>Back to flows</Link>
          </Button>
        }
      />
    );
  }
  if (!flow.data || !current) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  return <FlowEditor workspace={workspace} flow={flow.data} role={current.role} />;
}
