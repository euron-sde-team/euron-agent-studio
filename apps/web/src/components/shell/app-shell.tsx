"use client";

import {
  History,
  Inbox,
  LayoutDashboard,
  LayoutTemplate,
  Library,
  Menu,
  Plus,
  Settings,
  Workflow,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Wordmark } from "@/components/brand";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { Button } from "@/components/ui/button";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { Tooltip } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { canEdit, useMe, usePendingApprovals, useSystemInfo } from "@/lib/queries";
import { runtimeEnv } from "@/lib/runtime-env";
import { LAST_WORKSPACE_KEY, writeLocal } from "@/lib/storage";
import type { Me, WorkspaceSummary } from "@/lib/types";

const NAV = [
  { segment: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { segment: "flows", label: "Flows", icon: Workflow },
  { segment: "runs", label: "Runs", icon: History },
  { segment: "approvals", label: "Approvals", icon: Inbox },
  { segment: "knowledge", label: "Knowledge", icon: Library },
  { segment: "templates", label: "Templates", icon: LayoutTemplate },
  { segment: "settings", label: "Settings", icon: Settings },
] as const;

function Sidebar({
  me,
  current,
  onNavigate,
}: {
  me: Me;
  current: WorkspaceSummary;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const base = `/w/${current.slug}`;
  const pending = usePendingApprovals(current.slug);
  const system = useSystemInfo();
  const waiting = pending.data?.total ?? 0;
  return (
    <div className="border-sidebar-border bg-sidebar flex h-full w-64 flex-col border-r">
      <div className="px-3 pt-3 pb-2">
        <WorkspaceSwitcher current={current} all={me.workspaces} />
      </div>
      {canEdit(current.role) ? (
        <div className="px-3">
          <Button asChild variant="secondary" className="w-full justify-start">
            <Link href={`${base}/flows?new=1`} onClick={onNavigate}>
              <Plus /> New flow
            </Link>
          </Button>
        </div>
      ) : null}
      <nav className="mt-3 space-y-0.5 px-3" aria-label="Workspace">
        {NAV.map(({ segment, label, icon: Icon }) => {
          const href = `${base}/${segment}`;
          const active = pathname.startsWith(href);
          return (
            <Link
              key={segment}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors [&_svg]:size-4",
                active
                  ? "bg-card text-foreground ring-border font-medium shadow-sm ring-1"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className={active ? "text-primary" : ""} />
              <span className="flex-1">{label}</span>
              {segment === "approvals" && waiting > 0 ? (
                <span
                  className="bg-warning-soft text-warning rounded-full px-1.5 text-[11px] font-semibold tabular-nums"
                  aria-label={`${waiting} pending`}
                >
                  {waiting}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto space-y-2 p-3">
        {system.data?.offline_only ? (
          <Tooltip content="Every model call is answered by the built-in deterministic model: no API key, no network, the same answer every time.">
            <p className="border-border text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-2.5 py-1.5 text-[12px]">
              <span className="bg-success inline-block size-1.5 rounded-full" aria-hidden />
              Offline model (deterministic)
            </p>
          </Tooltip>
        ) : null}
        <div className="border-sidebar-border border-t pt-3">
          <UserMenu user={me.user} />
        </div>
      </div>
    </div>
  );
}

export function AppShell({ workspace, children }: { workspace: string; children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();
  const [drawer, setDrawer] = useState(false);
  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  const current = me.data?.workspaces.find((w) => w.slug === workspace || w.id === workspace);

  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, pathname, router]);

  useEffect(() => {
    if (current) writeLocal(LAST_WORKSPACE_KEY, current.slug);
  }, [current]);

  if (me.isLoading || unauthorized) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  if (me.error || !me.data) {
    return (
      <EmptyState
        className="h-dvh"
        title="AgentStudio is unreachable"
        description={me.error?.message ?? "Try again shortly."}
      />
    );
  }
  if (!current) {
    return (
      <EmptyState
        className="h-dvh"
        title="Workspace not found"
        description="It does not exist, or you are not a member."
        action={
          <Button asChild variant="secondary">
            <Link href="/">Go to my workspaces</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden lg:block">
        <Sidebar me={me.data} current={current} />
      </aside>
      {drawer ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawer(false)}
          />
          <div className="animate-fade-in relative h-full w-64">
            <Sidebar me={me.data} current={current} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-border flex h-12 shrink-0 items-center justify-between border-b px-3 lg:hidden">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Open menu"
            onClick={() => setDrawer(true)}
          >
            {drawer ? <X /> : <Menu />}
          </Button>
          <Wordmark name={runtimeEnv().productName} className="[&_svg]:size-6" />
          <span className="size-8" />
        </header>
        <main className="scroll-quiet min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
