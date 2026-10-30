"use client";

import { useParams } from "next/navigation";

import { ActivityPanel } from "@/components/settings/activity-panel";
import { ApiKeysPanel } from "@/components/settings/api-keys-panel";
import { GeneralPanel } from "@/components/settings/general-panel";
import { MembersPanel } from "@/components/settings/members-panel";
import { SecretsPanel } from "@/components/settings/secrets-panel";
import { ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWorkspace } from "@/lib/queries";

export default function SettingsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const query = useWorkspace(workspace);
  const data = query.data;
  const owner = data?.role === "owner";
  const viewer = data?.role === "viewer";

  return (
    <PageBody className="max-w-4xl">
      <PageHeader
        title="Settings"
        description="Workspace details, people, secrets and programmatic access."
      />
      {query.error ? <ErrorNotice message={query.error.message} /> : null}
      {!data ? (
        <Skeleton className="h-64" />
      ) : (
        <Tabs defaultValue="general">
          <TabsList className="overflow-x-auto">
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="members">Members</TabsTrigger>
            {!viewer ? <TabsTrigger value="secrets">Secrets</TabsTrigger> : null}
            {owner ? <TabsTrigger value="api-keys">API keys</TabsTrigger> : null}
            {owner ? <TabsTrigger value="activity">Activity</TabsTrigger> : null}
          </TabsList>
          <TabsContent value="general">
            <GeneralPanel
              key={data.name + data.settings.default_model}
              workspace={data}
              editable={owner}
            />
          </TabsContent>
          <TabsContent value="members">
            <MembersPanel workspace={data.slug} isOwner={owner} />
          </TabsContent>
          {!viewer ? (
            <TabsContent value="secrets">
              <SecretsPanel workspace={data.slug} isOwner={owner} />
            </TabsContent>
          ) : null}
          {owner ? (
            <TabsContent value="api-keys">
              <ApiKeysPanel workspace={data.slug} />
            </TabsContent>
          ) : null}
          {owner ? (
            <TabsContent value="activity">
              <ActivityPanel workspace={data.slug} />
            </TabsContent>
          ) : null}
        </Tabs>
      )}
    </PageBody>
  );
}
