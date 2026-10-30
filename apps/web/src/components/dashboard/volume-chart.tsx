"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatNumber } from "@/lib/format";
import type { DashboardDay } from "@/lib/types";

const axis = { fontSize: 11, fill: "var(--subtle)" };

type TooltipEntry = { name?: string; value?: number; color?: string };

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((sum, entry) => sum + (entry.value ?? 0), 0);
  return (
    <div className="border-border bg-card rounded-lg border px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">
        {label}{" "}
        <span className="text-muted-foreground font-normal">({formatNumber(total)} runs)</span>
      </p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-muted-foreground flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: entry.color }} />
          {entry.name}:{" "}
          <span className="text-foreground font-medium">{formatNumber(entry.value ?? 0)}</span>
        </p>
      ))}
    </div>
  );
}

const label = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** Runs per day, stacked by outcome. */
export function VolumeChart({ days }: { days: DashboardDay[] }) {
  const data = days.map((day) => ({ ...day, label: label(day.date) }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis allowDecimals={false} tick={axis} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--muted)" }} />
        <Bar dataKey="succeeded" name="Succeeded" stackId="v" fill="var(--chart-success)" />
        <Bar dataKey="failed" name="Failed" stackId="v" fill="var(--chart-failed)" />
        <Bar
          dataKey="other"
          name="Waiting or cancelled"
          stackId="v"
          fill="var(--chart-other)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
