"use client";

import { Gauge, Timer, Trophy, Zap } from "lucide-react";
import { memo } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { SpeedToLeadStats } from "@/lib/api/dashboard";

interface SpeedToLeadCardProps {
  speedToLeadStats: SpeedToLeadStats | undefined;
  isPending: boolean;
}

/** Format a duration in seconds as a compact human string (e.g. "1m 5s"). */
function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hours}h ${remMins}m` : `${hours}h`;
}

export const SpeedToLeadCard = memo(function SpeedToLeadCard({
  speedToLeadStats,
  isPending,
}: SpeedToLeadCardProps) {
  const pct = speedToLeadStats?.pct_within_sla ?? null;
  const slaSeconds = speedToLeadStats?.sla_seconds ?? 0;

  const pctColor =
    pct === null
      ? "text-muted-foreground"
      : pct >= 80
        ? "text-success"
        : pct >= 50
          ? "text-warning"
          : "text-destructive";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 gradient-heading">
          <Zap className="size-5" />
          Speed to Lead
        </CardTitle>
        <CardDescription>
          First-response SLA over the last {speedToLeadStats?.window_days ?? 0} days
          {slaSeconds > 0 ? ` · target ${formatDuration(slaSeconds)}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {isPending && !speedToLeadStats ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1 text-center">
                  <Skeleton className="mx-auto h-8 w-12" />
                  <Skeleton className="mx-auto h-3 w-16" />
                  <Skeleton className="mx-auto h-3 w-20" />
                </div>
              ))}
            </>
          ) : (
            <>
              <div className="space-y-1 text-center">
                <div className={`flex items-center justify-center gap-1 ${pctColor}`}>
                  <Gauge className="size-4" />
                  <span className="text-2xl font-bold">
                    {pct !== null ? `${pct}%` : "—"}
                  </span>
                </div>
                <p className="text-xs font-medium">Within SLA</p>
                <p className="text-xs text-muted-foreground">
                  {speedToLeadStats?.within_sla ?? 0}/
                  {speedToLeadStats?.leads_measured ?? 0} leads
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-info">
                  <Timer className="size-4" />
                  <span className="text-2xl font-bold">
                    {formatDuration(speedToLeadStats?.avg_response_seconds ?? null)}
                  </span>
                </div>
                <p className="text-xs font-medium">Avg Response</p>
                <p className="text-xs text-muted-foreground">First reply</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-primary">
                  <Timer className="size-4" />
                  <span className="text-2xl font-bold">
                    {formatDuration(speedToLeadStats?.median_response_seconds ?? null)}
                  </span>
                </div>
                <p className="text-xs font-medium">Median</p>
                <p className="text-xs text-muted-foreground">Typical reply</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-success">
                  <Trophy className="size-4" />
                  <span className="text-2xl font-bold">
                    {formatDuration(speedToLeadStats?.fastest_response_seconds ?? null)}
                  </span>
                </div>
                <p className="text-xs font-medium">Fastest</p>
                <p className="text-xs text-muted-foreground">Best reply</p>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
