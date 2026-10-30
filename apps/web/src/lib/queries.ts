"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ws } from "@/lib/api";
import type {
  ApiKey,
  ApiKeyCreated,
  Approval,
  ApprovalStatus,
  AuditEvent,
  Dashboard,
  DraftSaved,
  Flow,
  FlowDocument,
  FlowSummary,
  GraphDocument,
  Issue,
  KnowledgeBase,
  KnowledgeDocument,
  Me,
  Member,
  Model,
  Page,
  Role,
  Run,
  RunDetail,
  RunStatus,
  RunTrigger,
  SearchResult,
  Secret,
  SystemInfo,
  Template,
  User,
  Version,
  VersionDetail,
  Webhook,
  Workspace,
  WorkspaceSettings,
} from "@/lib/types";

export type FlowFilters = { q?: string; tag?: string; published?: "true" | "false" };
export type RunFilters = { flow_id?: string; status?: RunStatus; trigger?: RunTrigger };

export const qk = {
  system: ["system"] as const,
  me: ["me"] as const,
  models: ["models"] as const,
  templates: ["templates"] as const,
  workspace: (w: string) => ["workspace", w] as const,
  dashboard: (w: string) => ["dashboard", w] as const,
  flows: (w: string, filters: FlowFilters) => ["flows", w, filters] as const,
  flowsAll: (w: string) => ["flows", w] as const,
  tags: (w: string) => ["tags", w] as const,
  flow: (w: string, id: string) => ["flow", w, id] as const,
  versions: (w: string, id: string) => ["versions", w, id] as const,
  runs: (w: string, filters: RunFilters, offset: number) => ["runs", w, filters, offset] as const,
  runsAll: (w: string) => ["runs", w] as const,
  run: (w: string, id: string) => ["run", w, id] as const,
  approvals: (w: string, status: string) => ["approvals", w, status] as const,
  approvalsAll: (w: string) => ["approvals", w] as const,
  knowledgeBases: (w: string) => ["knowledge-bases", w] as const,
  knowledgeBase: (w: string, id: string) => ["knowledge-base", w, id] as const,
  documents: (w: string, id: string) => ["documents", w, id] as const,
  secrets: (w: string) => ["secrets", w] as const,
  members: (w: string) => ["members", w] as const,
  apiKeys: (w: string) => ["api-keys", w] as const,
  audit: (w: string) => ["audit", w] as const,
};

const ACTIVE: RunStatus[] = ["queued", "running"];

// ---------------------------------------------------------------------------------------
// Session and deployment
// ---------------------------------------------------------------------------------------

export function useSystemInfo() {
  return useQuery({
    queryKey: qk.system,
    queryFn: () => api<SystemInfo>("/api/v1/system/info"),
    staleTime: 300_000,
  });
}

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api<Me>("/api/v1/auth/me"), retry: false });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<{ user: User }>("/api/v1/auth/login", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useSignup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name: string; password: string }) =>
      api<{ user: User }>("/api/v1/auth/signup", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api<{ user: User }>("/api/v1/auth/password", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
    onSettled: () => client.clear(),
  });
}

export function useModels() {
  return useQuery({
    queryKey: qk.models,
    queryFn: () => api<Model[]>("/api/v1/models"),
    staleTime: 300_000,
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: qk.templates,
    queryFn: () => api<Template[]>("/api/v1/templates"),
    staleTime: 300_000,
  });
}

// ---------------------------------------------------------------------------------------
// Workspaces
// ---------------------------------------------------------------------------------------

export function useWorkspace(workspace: string) {
  return useQuery({
    queryKey: qk.workspace(workspace),
    queryFn: () => api<Workspace>(ws(workspace)),
  });
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      api<Workspace>("/api/v1/workspaces", { method: "POST", json: body }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.me }),
  });
}

export function useUpdateWorkspace(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string; settings?: WorkspaceSettings }) =>
      api<Workspace>(ws(workspace), { method: "PATCH", json: body }),
    onSuccess: (updated) => {
      client.setQueryData(qk.workspace(workspace), updated);
      void client.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export function useDashboard(workspace: string) {
  return useQuery({
    queryKey: qk.dashboard(workspace),
    queryFn: () => api<Dashboard>(`${ws(workspace)}/dashboard`),
    refetchInterval: (query) =>
      (query.state.data?.running ?? 0) > 0 ||
      query.state.data?.recent_runs.some((r) => ACTIVE.includes(r.status))
        ? 3000
        : false,
  });
}

// ---------------------------------------------------------------------------------------
// Flows
// ---------------------------------------------------------------------------------------

export function useFlows(workspace: string, filters: FlowFilters) {
  const params = new URLSearchParams({ limit: "100" });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  return useQuery({
    queryKey: qk.flows(workspace, filters),
    queryFn: () => api<Page<FlowSummary>>(`${ws(workspace)}/flows?${params}`),
  });
}

export function useTags(workspace: string) {
  return useQuery({
    queryKey: qk.tags(workspace),
    queryFn: () => api<string[]>(`${ws(workspace)}/flows/tags`),
  });
}

export function useFlow(workspace: string, id: string) {
  return useQuery({
    queryKey: qk.flow(workspace, id),
    queryFn: () => api<Flow>(`${ws(workspace)}/flows/${id}`),
    // The editor owns the draft once it is open: never refetch it underneath the canvas.
    staleTime: Infinity,
  });
}

export function useCreateFlow(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      description?: string;
      tags?: string[];
      template?: string;
    }) => api<Flow>(`${ws(workspace)}/flows`, { method: "POST", json: body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.flowsAll(workspace) });
      void client.invalidateQueries({ queryKey: qk.me });
      void client.invalidateQueries({ queryKey: qk.knowledgeBases(workspace) });
    },
  });
}

export function useImportFlow(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (document: FlowDocument) =>
      api<Flow>(`${ws(workspace)}/flows/import`, { method: "POST", json: document }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.flowsAll(workspace) }),
  });
}

export function useSaveDraft(workspace: string, flowId: string) {
  return useMutation({
    mutationFn: (body: { graph: GraphDocument; base_revision: number }) =>
      api<DraftSaved>(`${ws(workspace)}/flows/${flowId}/draft`, { method: "PUT", json: body }),
  });
}

export function useFlowActions(workspace: string, flowId: string) {
  const client = useQueryClient();
  const base = `${ws(workspace)}/flows/${flowId}`;
  const refreshList = () => client.invalidateQueries({ queryKey: qk.flowsAll(workspace) });
  return {
    update: useMutation({
      mutationFn: (body: { name?: string; description?: string; tags?: string[] }) =>
        api<Flow>(base, { method: "PATCH", json: body }),
      onSuccess: (flow) => {
        client.setQueryData(qk.flow(workspace, flowId), flow);
        void refreshList();
        void client.invalidateQueries({ queryKey: qk.tags(workspace) });
      },
    }),
    validate: useMutation({
      mutationFn: (graph: GraphDocument) =>
        api<{ valid: boolean; issues: Issue[] }>(`${base}/validate`, {
          method: "POST",
          json: { graph },
        }),
    }),
    publish: useMutation({
      mutationFn: (notes: string) =>
        api<Version>(`${base}/publish`, { method: "POST", json: { notes } }),
      onSuccess: () => {
        void client.invalidateQueries({ queryKey: qk.versions(workspace, flowId) });
        void refreshList();
      },
    }),
    restore: useMutation({
      mutationFn: (version: number) =>
        api<Flow>(`${base}/versions/${version}/restore`, { method: "POST" }),
    }),
    duplicate: useMutation({
      mutationFn: () => api<Flow>(`${base}/duplicate`, { method: "POST" }),
      onSuccess: refreshList,
    }),
    remove: useMutation({
      mutationFn: () => api<void>(base, { method: "DELETE" }),
      onSuccess: () => {
        void refreshList();
        void client.invalidateQueries({ queryKey: qk.me });
      },
    }),
    run: useMutation({
      mutationFn: (body: { inputs: Record<string, unknown>; version: "draft" | "published" }) =>
        api<Run>(`${base}/runs`, { method: "POST", json: body }),
      onSuccess: () => client.invalidateQueries({ queryKey: qk.runsAll(workspace) }),
    }),
  };
}

export function useVersions(workspace: string, flowId: string, enabled = true) {
  return useQuery({
    queryKey: qk.versions(workspace, flowId),
    queryFn: () => api<Page<Version>>(`${ws(workspace)}/flows/${flowId}/versions?limit=100`),
    enabled,
  });
}

export function fetchVersion(workspace: string, flowId: string, version: number) {
  return api<VersionDetail>(`${ws(workspace)}/flows/${flowId}/versions/${version}`);
}

export function useWebhook(workspace: string, flowId: string) {
  const client = useQueryClient();
  const url = `${ws(workspace)}/flows/${flowId}/webhook`;
  const refresh = () => client.invalidateQueries({ queryKey: qk.flow(workspace, flowId) });
  return {
    enable: useMutation({
      mutationFn: () => api<Webhook>(url, { method: "PUT" }),
      onSuccess: refresh,
    }),
    disable: useMutation({
      mutationFn: () => api<Webhook>(url, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

// ---------------------------------------------------------------------------------------
// Runs and approvals
// ---------------------------------------------------------------------------------------

export function useRuns(workspace: string, filters: RunFilters, offset = 0, limit = 25) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  return useQuery({
    queryKey: qk.runs(workspace, filters, offset),
    queryFn: () => api<Page<Run>>(`${ws(workspace)}/runs?${params}`),
    // Keep the list fresh while anything on it is still moving.
    refetchInterval: (query) =>
      query.state.data?.items.some((r) => ACTIVE.includes(r.status)) ? 2500 : false,
  });
}

export function useRun(workspace: string, id: string | null) {
  return useQuery({
    queryKey: qk.run(workspace, id ?? "none"),
    queryFn: () => api<RunDetail>(`${ws(workspace)}/runs/${id}`),
    enabled: Boolean(id),
  });
}

export function useRunActions(workspace: string) {
  const client = useQueryClient();
  const refresh = (run: Run) => {
    void client.invalidateQueries({ queryKey: qk.runsAll(workspace) });
    void client.invalidateQueries({ queryKey: qk.run(workspace, run.id) });
    void client.invalidateQueries({ queryKey: qk.approvalsAll(workspace) });
  };
  return {
    cancel: useMutation({
      mutationFn: (id: string) =>
        api<Run>(`${ws(workspace)}/runs/${id}/cancel`, { method: "POST" }),
      onSuccess: refresh,
    }),
    rerun: useMutation({
      mutationFn: (id: string) => api<Run>(`${ws(workspace)}/runs/${id}/rerun`, { method: "POST" }),
      onSuccess: refresh,
    }),
  };
}

export function useApprovals(workspace: string, status: ApprovalStatus | "all") {
  const params = new URLSearchParams({ limit: "100" });
  if (status !== "all") params.set("status", status);
  return useQuery({
    queryKey: qk.approvals(workspace, status),
    queryFn: () => api<Page<Approval>>(`${ws(workspace)}/approvals?${params}`),
    refetchInterval: 15_000,
  });
}

export function usePendingApprovals(workspace: string) {
  return useApprovals(workspace, "pending");
}

export function useDecide(workspace: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { id: string; decision: "approve" | "reject"; comment: string }) =>
      api<Approval>(`${ws(workspace)}/approvals/${body.id}/decision`, {
        method: "POST",
        json: { decision: body.decision, comment: body.comment },
      }),
    onSuccess: (approval) => {
      void client.invalidateQueries({ queryKey: qk.approvalsAll(workspace) });
      void client.invalidateQueries({ queryKey: qk.run(workspace, approval.run_id) });
      void client.invalidateQueries({ queryKey: qk.runsAll(workspace) });
      void client.invalidateQueries({ queryKey: qk.dashboard(workspace) });
    },
  });
}

// ---------------------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------------------

export function useKnowledgeBases(workspace: string) {
  return useQuery({
    queryKey: qk.knowledgeBases(workspace),
    queryFn: () => api<Page<KnowledgeBase>>(`${ws(workspace)}/knowledge-bases?limit=100`),
  });
}

export function useKnowledgeBase(workspace: string, id: string) {
  return useQuery({
    queryKey: qk.knowledgeBase(workspace, id),
    queryFn: () => api<KnowledgeBase>(`${ws(workspace)}/knowledge-bases/${id}`),
  });
}

export function useDocuments(workspace: string, id: string) {
  return useQuery({
    queryKey: qk.documents(workspace, id),
    queryFn: () =>
      api<Page<KnowledgeDocument>>(`${ws(workspace)}/knowledge-bases/${id}/documents?limit=100`),
  });
}

export function useKnowledgeActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.knowledgeBases(workspace) });
  return {
    create: useMutation({
      mutationFn: (body: { name: string; description: string }) =>
        api<KnowledgeBase>(`${ws(workspace)}/knowledge-bases`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string }) =>
        api<KnowledgeBase>(`${ws(workspace)}/knowledge-bases/${id}`, {
          method: "PATCH",
          json: body,
        }),
      onSuccess: (kb) => {
        client.setQueryData(qk.knowledgeBase(workspace, kb.id), kb);
        void refresh();
      },
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        api<void>(`${ws(workspace)}/knowledge-bases/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useDocumentActions(workspace: string, kbId: string) {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: qk.documents(workspace, kbId) });
    void client.invalidateQueries({ queryKey: qk.knowledgeBase(workspace, kbId) });
    void client.invalidateQueries({ queryKey: qk.knowledgeBases(workspace) });
  };
  return {
    upload: useMutation({
      mutationFn: (files: File[]) => {
        const form = new FormData();
        for (const file of files) form.append("files", file, file.name);
        return api<KnowledgeDocument[]>(`${ws(workspace)}/knowledge-bases/${kbId}/documents`, {
          method: "POST",
          body: form,
        });
      },
      onSettled: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) =>
        api<void>(`${ws(workspace)}/knowledge-bases/${kbId}/documents/${id}`, {
          method: "DELETE",
        }),
      onSuccess: refresh,
    }),
    search: useMutation({
      mutationFn: (body: { query: string; top_k: number }) =>
        api<SearchResult>(`${ws(workspace)}/knowledge-bases/${kbId}/search`, {
          method: "POST",
          json: body,
        }),
    }),
  };
}

// ---------------------------------------------------------------------------------------
// Settings: secrets, members, API keys, audit
// ---------------------------------------------------------------------------------------

export function useSecrets(workspace: string, enabled = true) {
  return useQuery({
    queryKey: qk.secrets(workspace),
    queryFn: () => api<Page<Secret>>(`${ws(workspace)}/secrets?limit=100`),
    enabled,
  });
}

export function useSecretActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.secrets(workspace) });
  return {
    create: useMutation({
      mutationFn: (body: { name: string; value: string; description: string }) =>
        api<Secret>(`${ws(workspace)}/secrets`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ name, ...body }: { name: string; value?: string; description?: string }) =>
        api<Secret>(`${ws(workspace)}/secrets/${name}`, { method: "PATCH", json: body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (name: string) =>
        api<void>(`${ws(workspace)}/secrets/${name}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useMembers(workspace: string) {
  return useQuery({
    queryKey: qk.members(workspace),
    queryFn: () => api<Page<Member>>(`${ws(workspace)}/members?limit=100`),
  });
}

export function useMemberActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.members(workspace) });
  return {
    add: useMutation({
      mutationFn: (body: { email: string; name?: string; role: Role }) =>
        api<{ member: Member; temporary_password: string | null }>(`${ws(workspace)}/members`, {
          method: "POST",
          json: body,
        }),
      onSuccess: refresh,
    }),
    changeRole: useMutation({
      mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
        api<Member>(`${ws(workspace)}/members/${userId}`, { method: "PATCH", json: { role } }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (userId: string) =>
        api<void>(`${ws(workspace)}/members/${userId}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useApiKeys(workspace: string, enabled = true) {
  return useQuery({
    queryKey: qk.apiKeys(workspace),
    queryFn: () => api<Page<ApiKey>>(`${ws(workspace)}/api-keys?limit=100`),
    enabled,
  });
}

export function useApiKeyActions(workspace: string) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: qk.apiKeys(workspace) });
  return {
    create: useMutation({
      mutationFn: (body: {
        name: string;
        role: "viewer" | "editor";
        expires_in_days: number | null;
      }) => api<ApiKeyCreated>(`${ws(workspace)}/api-keys`, { method: "POST", json: body }),
      onSuccess: refresh,
    }),
    revoke: useMutation({
      mutationFn: (id: string) =>
        api<void>(`${ws(workspace)}/api-keys/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useAudit(workspace: string, enabled = true) {
  return useQuery({
    queryKey: qk.audit(workspace),
    queryFn: () => api<Page<AuditEvent>>(`${ws(workspace)}/audit?limit=100`),
    enabled,
  });
}

/** The signed-in user's summary of a workspace (including their role), from the session cache. */
export function useCurrentWorkspace(workspace: string) {
  const me = useMe();
  return me.data?.workspaces.find((w) => w.slug === workspace || w.id === workspace);
}

export function canEdit(role: Role | undefined): boolean {
  return role === "owner" || role === "editor";
}
