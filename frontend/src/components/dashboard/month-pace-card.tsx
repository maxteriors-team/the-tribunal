"use client";

/**
 * Dashboard → Month Pace: are we going to hit this month's revenue goal?
 *
 * The dashboard has always reported trailing revenue with nothing to measure it
 * against. This card supplies the denominator: the month's goal, what has sold
 * so far, and the linear projection of where that pace lands by month end.
 *
 * Colour is scored against the **required pace**, never against last month. A
 * business can be up 20% on last February and still miss February's goal by
 * half, so "better than before" is the wrong question. Status is also spelled
 * out in words and carried by an icon, so the reading never depends on colour
 * alone.
 *
 * A month with no stored target reports `has_target: false` with its actuals
 * still populated, so this prompts for a goal instead of rendering a wall of
 * zeros that looks like a catastrophic month.
 */

import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Gauge, Target, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
import {
  revenueTargetsApi,
  type PaceStage,
  type RevenuePace,
} from "@/lib/api/revenue-targets";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import { formatNumber, formatWholeCurrency } from "@/lib/utils/number";

/** Where the settings tab that sets a goal lives. */
const SALES_TARGETS_HREF = "/settings?tab=sales-targets";

/** Projection may fall this far short of the goal before it reads as behind. */
const AT_RISK_SHARE = 0.9;

export type PaceStatus = "on-track" | "at-risk" | "behind" | "unknown";

/**
 * Score a month against the pace required to hit its goal.
 *
 * Green once the projection clears the goal, amber while it is within 10% of
 * it, red below that. `unknown` covers a month that cannot be projected yet
 * (no elapsed days) or has no usable goal.
 */
export function paceStatus(
  projected: number | null,
  goal: number | null,
): PaceStatus {
  if (goal === null || !Number.isFinite(goal) || goal <= 0) return "unknown";
  if (projected === null || !Number.isFinite(projected)) return "unknown";
  if (projected >= goal) return "on-track";
  if (projected >= goal * AT_RISK_SHARE) return "at-risk";
  return "behind";
}

const STATUS_COPY: Record<PaceStatus, { label: string; className: string }> = {
  "on-track": {
    label: "On pace to hit the goal",
    className: "text-success",
  },
  "at-risk": {
    label: "Within 10% of the goal at this pace",
    className: "text-warning",
  },
  behind: {
    label: "Behind the pace needed",
    className: "text-destructive",
  },
  unknown: {
    label: "Not enough of the month has elapsed to project",
    className: "text-muted-foreground",
  },
};

const STAGE_LABELS: Record<PaceStage["stage"], string> = {
  leads: "Leads",
  estimates: "Estimates",
  sold: "Sold jobs",
};

/** Score one funnel stage against the count required by today. */
function stageClassName(actual: number, requiredToDate: number | null): string {
  if (requiredToDate === null || requiredToDate <= 0) return "text-foreground";
  if (actual >= requiredToDate) return "text-success";
  if (actual >= requiredToDate * AT_RISK_SHARE) return "text-warning";
  return "text-destructive";
}

function formatCount(value: number | null): string {
  return value === null ? "—" : formatNumber(Math.ceil(value));
}

function monthLabel(periodMonth: string): string {
  // `period_month` is a plain date string; parse the parts rather than letting
  // `new Date("2026-06-01")` shift the month across a timezone boundary.
  const [year, month] = periodMonth.split("-").map(Number);
  if (!year || !month) return periodMonth;
  return new Date(year, month - 1, 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Metric({
  label,
  value,
  className = "text-foreground",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border bg-card/50 p-4 text-center">
      <div className={`text-2xl font-bold ${className}`}>{value}</div>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

/**
 * Sold-so-far against the goal, with a tick marking where the month should be
 * today. The gap between the fill and the tick is the pace problem, made
 * visible without arithmetic.
 */
function PaceBar({ pace }: { pace: RevenuePace }) {
  const goal = pace.revenue_goal ?? null;
  if (goal === null || goal <= 0) return null;

  const soldShare = Math.min(100, Math.max(0, (pace.revenue_sold_to_date / goal) * 100));
  const requiredShare =
    pace.days_in_month > 0
      ? Math.min(100, (pace.days_elapsed / pace.days_in_month) * 100)
      : 0;
  const status = paceStatus(pace.projected_month_end ?? null, goal);
  const fill =
    status === "on-track"
      ? "bg-success"
      : status === "at-risk"
        ? "bg-warning"
        : status === "behind"
          ? "bg-destructive"
          : "bg-muted-foreground";

  return (
    <div className="space-y-2">
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${fill}`}
          style={{ width: `${soldShare}%` }}
        />
        <div
          className="absolute inset-y-0 w-0.5 bg-foreground"
          style={{ left: `${requiredShare}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {formatWholeCurrency(pace.revenue_sold_to_date, pace.currency)} of{" "}
        {formatWholeCurrency(goal, pace.currency)} sold. The marker is where the
        month should be on day {pace.days_elapsed} of {pace.days_in_month}.
      </p>
    </div>
  );
}

function StageTable({ stages }: { stages: PaceStage[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Stage</TableHead>
          <TableHead className="text-right">Actual</TableHead>
          <TableHead className="text-right">Required by today</TableHead>
          <TableHead className="text-right">Required this month</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {stages.map((stage) => (
          <TableRow key={stage.stage}>
            <TableCell className="font-medium">
              {STAGE_LABELS[stage.stage]}
            </TableCell>
            <TableCell
              className={`text-right font-semibold ${stageClassName(
                stage.actual,
                stage.required_to_date ?? null,
              )}`}
            >
              {formatNumber(stage.actual)}
            </TableCell>
            <TableCell className="text-right text-muted-foreground">
              {formatCount(stage.required_to_date ?? null)}
            </TableCell>
            <TableCell className="text-right">
              {formatCount(stage.required ?? null)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function NoTargetPrompt({ periodMonth }: { periodMonth: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <Target className="size-8 text-muted-foreground" />
      <div className="space-y-1">
        <p className="text-sm font-semibold">
          No revenue goal set for {monthLabel(periodMonth)}
        </p>
        <p className="max-w-md text-sm text-muted-foreground">
          Set a monthly goal and your funnel assumptions, and this card will show
          whether the month is on pace and how many leads, estimates and jobs it
          still needs.
        </p>
      </div>
      <Button asChild>
        <Link href={SALES_TARGETS_HREF}>Set a revenue goal</Link>
      </Button>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-5 w-56" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
      <Skeleton className="h-3 w-full" />
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

interface MonthPaceCardProps {
  workspaceId: string;
}

export function MonthPaceCard({ workspaceId }: MonthPaceCardProps) {
  const { data, isPending, isError } = useQuery<RevenuePace>({
    queryKey: queryKeys.revenueTargets.pace(workspaceId),
    queryFn: () => revenueTargetsApi.getPace(workspaceId),
    enabled: !!workspaceId,
    ...REALTIME,
    placeholderData: (prev) => prev,
  });

  // Every nullable money field is optional in the spec, so normalize `undefined`
  // to `null` once here rather than at each read site.
  const projectedMonthEnd = data?.projected_month_end ?? null;
  const gapToGoal = data?.gap_to_goal ?? null;
  const overCapacity = data?.estimates_over_capacity ?? null;

  const status = paceStatus(projectedMonthEnd, data?.revenue_goal ?? null);
  const statusCopy = STATUS_COPY[status];
  const StatusIcon =
    status === "on-track" ? TrendingUp : status === "unknown" ? Gauge : TrendingDown;
  const daysRemaining = data ? Math.max(0, data.days_in_month - data.days_elapsed) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="size-5" />
          Month Pace
        </CardTitle>
        <CardDescription>
          {data
            ? `${monthLabel(data.period_month)} sold against the pace needed to hit the goal`
            : "This month sold against the pace needed to hit the goal"}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {isPending && !data && <LoadingSkeleton />}

        {isError && !data && (
          <p className="py-4 text-center text-sm text-destructive">
            Failed to load month pace. Please try again.
          </p>
        )}

        {data && !data.has_target && (
          <NoTargetPrompt periodMonth={data.period_month} />
        )}

        {data && data.has_target && (
          <>
            <p className={`flex items-center gap-2 text-sm font-semibold ${statusCopy.className}`}>
              <StatusIcon className="size-4" />
              {statusCopy.label}
            </p>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric
                label="Sold this month"
                value={formatWholeCurrency(data.revenue_sold_to_date, data.currency)}
                className="text-success"
              />
              <Metric
                label={`Days remaining of ${data.days_in_month}`}
                value={formatNumber(daysRemaining)}
              />
              <Metric
                label="Projected at this pace"
                value={
                  projectedMonthEnd === null
                    ? "—"
                    : formatWholeCurrency(projectedMonthEnd, data.currency)
                }
                className={statusCopy.className}
              />
              <Metric
                label="Still to sell"
                value={
                  gapToGoal === null
                    ? "—"
                    : formatWholeCurrency(Math.max(0, gapToGoal), data.currency)
                }
                className={
                  gapToGoal !== null && gapToGoal <= 0
                    ? "text-success"
                    : "text-foreground"
                }
              />
            </div>

            <PaceBar pace={data} />

            {overCapacity !== null && overCapacity > 0 && (
              <Alert>
                <CircleAlert className="size-4 text-warning" />
                <AlertDescription>
                  This goal needs {formatCount(overCapacity)} more estimates than
                  your stated capacity of{" "}
                  {formatNumber(data.estimate_capacity_per_month ?? 0)} a month.
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Funnel: actual vs required</h3>
              <StageTable stages={data.stages} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
