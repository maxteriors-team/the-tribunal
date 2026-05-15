"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Users, Megaphone, CalendarCheck } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { appointmentsApi } from "@/lib/api/appointments";
import { queryKeys } from "@/lib/query-keys";
import type {
  AppointmentAgentStat,
  AppointmentCampaignStat,
  AppointmentStatsResponse,
} from "@/lib/api/appointments";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function rateColor(rate: number): string {
  if (rate >= 70) return "text-success";
  if (rate >= 50) return "text-warning";
  return "text-destructive";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function HeadlineRate({ rate }: { rate: number }) {
  return (
    <div className="flex flex-col items-center justify-center py-4">
      <div className={`text-5xl font-bold ${rateColor(rate)}`}>
        {rate.toFixed(1)}%
      </div>
      <p className="mt-1 text-sm text-muted-foreground">Overall show-up rate</p>
    </div>
  );
}

function OverallPills({ stats }: { stats: AppointmentStatsResponse["overall"] }) {
  const pills: { label: string; value: number; cls: string }[] = [
    { label: "Total", value: stats.total, cls: "text-foreground" },
    { label: "Scheduled", value: stats.scheduled, cls: "text-info" },
    { label: "Completed", value: stats.completed, cls: "text-success" },
    { label: "No-show", value: stats.no_show, cls: "text-destructive" },
    { label: "Cancelled", value: stats.cancelled, cls: "text-muted-foreground" },
  ];

  return (
    <div className="grid grid-cols-5 gap-2 text-center text-sm">
      {pills.map(({ label, value, cls }) => (
        <div key={label}>
          <div className={`font-semibold text-lg ${cls}`}>{value}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      ))}
    </div>
  );
}

function AgentTable({ rows }: { rows: AppointmentAgentStat[] }) {
  if (rows.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        No agent-linked appointments yet.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead className="text-right">Showed Up</TableHead>
          <TableHead className="text-right">No-Show</TableHead>
          <TableHead className="text-right">Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.agent_id}>
            <TableCell className="font-medium">{row.agent_name}</TableCell>
            <TableCell className="text-right">{row.total}</TableCell>
            <TableCell className="text-right text-success">{row.completed}</TableCell>
            <TableCell className="text-right text-destructive">{row.no_show}</TableCell>
            <TableCell className={`text-right font-semibold ${rateColor(row.show_up_rate)}`}>
              {row.show_up_rate.toFixed(1)}%
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function CampaignTable({ rows }: { rows: AppointmentCampaignStat[] }) {
  if (rows.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">
        No campaign-linked appointments yet.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Campaign</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead className="text-right">Showed Up</TableHead>
          <TableHead className="text-right">No-Show</TableHead>
          <TableHead className="text-right">Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.campaign_id}>
            <TableCell className="font-medium">{row.campaign_name}</TableCell>
            <TableCell className="text-right">{row.total}</TableCell>
            <TableCell className="text-right text-success">{row.completed}</TableCell>
            <TableCell className="text-right text-destructive">{row.no_show}</TableCell>
            <TableCell className={`text-right font-semibold ${rateColor(row.show_up_rate)}`}>
              {row.show_up_rate.toFixed(1)}%
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex justify-center py-4">
        <Skeleton className="h-14 w-32" />
      </div>
      <div className="grid grid-cols-5 gap-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="space-y-1 text-center">
            <Skeleton className="mx-auto h-6 w-8" />
            <Skeleton className="mx-auto h-3 w-12" />
          </div>
        ))}
      </div>
      <Skeleton className="h-4 w-32" />
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface AppointmentPerformanceCardProps {
  workspaceId: string;
}

export function AppointmentPerformanceCard({
  workspaceId,
}: AppointmentPerformanceCardProps) {
  const { data, isPending, isError } = useQuery<AppointmentStatsResponse>({
    queryKey: queryKeys.appointments.stats(workspaceId ?? ""),
    queryFn: () => appointmentsApi.getStats(workspaceId),
    enabled: !!workspaceId,
    // Refresh every 2 minutes — stats don't change that fast
    refetchInterval: 120_000,
    placeholderData: (prev) => prev,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarCheck className="size-5" />
          Appointment Performance
        </CardTitle>
        <CardDescription>Show-up rate breakdown by agent and campaign</CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {isPending && <LoadingSkeleton />}

        {isError && (
          <p className="py-4 text-center text-sm text-destructive">
            Failed to load appointment stats. Please try again.
          </p>
        )}

        {data && (
          <>
            {/* Headline: overall show-up rate */}
            <HeadlineRate rate={data.overall.show_up_rate} />

            {/* Status breakdown pills */}
            <OverallPills stats={data.overall} />

            {/* By Agent */}
            <div className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Users className="size-4 text-muted-foreground" />
                By Agent
              </h3>
              <AgentTable rows={data.by_agent} />
            </div>

            {/* By Campaign */}
            <div className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Megaphone className="size-4 text-muted-foreground" />
                By Campaign
              </h3>
              <CampaignTable rows={data.by_campaign} />
            </div>
          </>
        )}

        {!isPending && !isError && !data && (
          <div className="flex flex-col items-center gap-1 py-8 text-center text-muted-foreground">
            <TrendingUp className="size-8 opacity-40" />
            <p className="text-sm">No appointment data yet.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
