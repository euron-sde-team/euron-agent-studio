"use client";

import { Activity, Coins, Gauge, Inbox, Timer, Workflow as WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { VolumeChart } from "@/components/dashboard/volume-chart";
import { StatusBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { PageBody, PageHeader } from "@/components/ui/page";
import { cn } from "@/lib/cn";
import {
  formatCompact,
  formatCost,
  formatDuration,
  formatNumber,
  formatPercent,
  formatRelative,
} from "@/lib/format";
import { useDashboard } from "@/lib/queries";

function Kpi({
  icon,
  label,
  value,
  detail,
  href,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: ReactNode;
  href?: string;
  tone?: "warning";
}) {
  const body = (
    <Card className={cn("h-full px-5 py-4", href && "hover:border-input transition-colors")}>
      <div className="text-muted-foreground [&_svg]:text-primary flex items-center gap-2 text-[12.5px] font-medium [&_svg]:size-4">
        {icon}
        {label}
      </div>
      <p
        className={cn(
          "mt-2 text-[26px] font-semibold tracking-tight tabular-nums",
          tone === "warning" && "text-warning",
        )}
      >
        {value}
      </p>
      <p className="text-muted-foreground mt-0.5 text-xs">{detail}</p>
    </Card>
  );
  return href ? (
    <Link href={href} className="block rounded-xl">
      {body}
    </Link>
  ) : (
    body
  );
}

export default function DashboardPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const dashboard = useDashboard(workspace);
  const data = dashboard.data;
  const base = `/w/${workspace}`;

  return (
    <PageBody>
      <PageHeader
        title="Dashboard"
        description={`What your flows did over the last ${data?.period_days ?? 14} days.`}
      />
      {dashboard.error ? <ErrorNotice message={dashboard.error.message} /> : null}
      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : data.runs === 0 ? (
        <Card>
          <EmptyState
            icon={<Activity />}
            title="No runs yet"
            description="Open a flow and press Run, or install a template: each comes with a sample to try."
          />
        </Card>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              icon={<Activity />}
              label="Runs"
              value={formatNumber(data.runs)}
              detail={`${formatNumber(data.succeeded)} succeeded, ${formatNumber(data.failed)} failed`}
              href={`${base}/runs`}
            />
            <Kpi
              icon={<Gauge />}
              label="Success rate"
              value={data.success_rate === null ? "-" : formatPercent(data.success_rate, 1)}
              detail="Of runs that finished"
            />
            <Kpi
              icon={<Timer />}
              label="Typical duration"
              value={formatDuration(data.p50_ms)}
              detail={`95th percentile ${formatDuration(data.p95_ms)}, waits included`}
            />
            <Kpi
              icon={<Coins />}
              label="Model cost"
              value={formatCost(data.cost_usd)}
              detail={`${formatCompact(data.prompt_tokens + data.completion_tokens)} tokens`}
            />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Runs per day</CardTitle>
                  <CardDescription>By outcome, in your time zone</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-2">
                <VolumeChart days={data.daily} />
              </CardContent>
            </Card>
            <div className="grid gap-4">
              <Kpi
                icon={<Inbox />}
                label="Waiting for approval"
                value={formatNumber(data.pending_approvals)}
                detail={
                  data.pending_approvals ? "Runs paused until someone decides" : "Nothing waiting"
                }
                href={`${base}/approvals`}
                tone={data.pending_approvals ? "warning" : undefined}
              />
              <Kpi
                icon={<WorkflowIcon />}
                label="Flows"
                value={formatNumber(data.flows)}
                detail={`${formatNumber(data.published_flows)} published`}
                href={`${base}/flows`}
              />
            </div>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Busiest flows</CardTitle>
              </CardHeader>
              <CardContent className="pt-2">
                <table className="w-full text-[13px]">
                  <thead className="text-subtle text-left text-[11.5px] tracking-wide uppercase">
                    <tr>
                      <th className="pb-2 font-medium">Flow</th>
                      <th className="pb-2 text-right font-medium">Runs</th>
                      <th className="pb-2 text-right font-medium">Success</th>
                      <th className="pb-2 text-right font-medium">Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-border divide-y">
                    {data.top_flows.map((flow) => (
                      <tr key={flow.flow_id}>
                        <td className="py-2">
                          <Link
                            href={`${base}/flows/${flow.flow_id}`}
                            className="hover:text-primary font-medium"
                          >
                            {flow.name}
                          </Link>
                        </td>
                        <td className="py-2 text-right tabular-nums">{formatNumber(flow.runs)}</td>
                        <td className="py-2 text-right tabular-nums">
                          {formatPercent(flow.success_rate)}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {formatCost(flow.cost_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Recent runs</CardTitle>
                <Link
                  href={`${base}/runs`}
                  className="text-primary text-[12.5px] font-medium hover:underline"
                >
                  All runs
                </Link>
              </CardHeader>
              <CardContent className="pt-2">
                <ul className="divide-border divide-y">
                  {data.recent_runs.map((run) => (
                    <li key={run.id}>
                      <Link
                        href={`${base}/runs/${run.id}`}
                        className="hover:bg-muted/50 -mx-2 flex items-center gap-3 rounded-md px-2 py-2"
                      >
                        <StatusBadge status={run.status} short />
                        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                          {run.flow_name}
                        </span>
                        <Badge tone="outline">{run.version_label}</Badge>
                        <span className="text-muted-foreground w-24 shrink-0 text-right text-[12px]">
                          {formatRelative(run.created_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </PageBody>
  );
}
