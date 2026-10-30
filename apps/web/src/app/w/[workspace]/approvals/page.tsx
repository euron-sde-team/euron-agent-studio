"use client";

import { Inbox } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ApprovalCard } from "@/components/runs/approval-card";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { canEdit, useApprovals, useCurrentWorkspace } from "@/lib/queries";
import type { ApprovalStatus } from "@/lib/types";

export default function ApprovalsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const current = useCurrentWorkspace(workspace);
  const [tab, setTab] = useState<ApprovalStatus | "all">("pending");
  const approvals = useApprovals(workspace, tab);
  const pending = useApprovals(workspace, "pending");
  const items = approvals.data?.items;

  return (
    <PageBody className="max-w-4xl">
      <PageHeader
        title="Approvals"
        description="Runs paused at a Human approval step wait here until someone decides."
      />
      <Tabs value={tab} onValueChange={(value) => setTab(value as ApprovalStatus | "all")}>
        <TabsList className="mb-5">
          <TabsTrigger value="pending">
            Waiting{pending.data?.total ? ` (${pending.data.total})` : ""}
          </TabsTrigger>
          <TabsTrigger value="approved">Approved</TabsTrigger>
          <TabsTrigger value="rejected">Rejected</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
        </TabsList>
        {(["pending", "approved", "rejected", "all"] as const).map((value) => (
          <TabsContent key={value} value={value} className="pt-0">
            {approvals.error ? <ErrorNotice message={approvals.error.message} /> : null}
            {!items ? (
              <Skeleton className="h-64" />
            ) : items.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<Inbox />}
                  title={value === "pending" ? "Nothing is waiting for you" : "No approvals here"}
                  description="Add a Human approval step to a flow to have people check its work before it acts."
                />
              </Card>
            ) : (
              <div className="space-y-3">
                {items.map((approval) => (
                  <ApprovalCard
                    key={approval.id}
                    workspace={workspace}
                    approval={approval}
                    canDecide={canEdit(current?.role)}
                  />
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </PageBody>
  );
}
