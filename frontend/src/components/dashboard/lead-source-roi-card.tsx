"use client";

import { Trophy } from "lucide-react";

import { sourceTypeLabel } from "@/components/lead-sources/source-pickers";
import { Badge } from "@/components/ui/badge";
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
import type {
  AttributionConfidenceLevel,
  LeadSourceRoiStats,
} from "@/lib/api/dashboard";
import { formatCurrency } from "@/lib/utils/number";

const CONFIDENCE_LABELS: Record<AttributionConfidenceLevel, string> = {
  exact: "Exact",
  high: "High",
  medium: "Medium",
  low: "Low",
  unknown: "Unknown",
};

function formatRoi(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}×`;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 w-full" />
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    </div>
  );
}

interface LeadSourceRoiCardProps {
  stats: LeadSourceRoiStats | undefined;
  isPending: boolean;
}

/**
 * Ranks the winning acquisition channel by ad spend + closed-won jobs and
 * renders the per-source ROI table for the dashboard.
 */
export function LeadSourceRoiCard({ stats, isPending }: LeadSourceRoiCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 gradient-heading">
          <Trophy className="size-5" />
          Winning Lead Source
        </CardTitle>
        <CardDescription>
          Ranked by ad spend and closed-won jobs across your channels
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {isPending && !stats && <LoadingSkeleton />}

        {stats && (
          <>
            {stats.winner.has_winner ? (
              <div className="rounded-lg border border-success/40 bg-success/5 p-4">
                <div className="flex items-center gap-2">
                  <Trophy className="size-4 text-success" />
                  <span className="text-sm font-medium text-muted-foreground">
                    Winning lead source
                  </span>
                </div>
                <p className="mt-1 text-xl font-bold">
                  {stats.winner.source_name ??
                    (stats.winner.source_type
                      ? sourceTypeLabel(stats.winner.source_type)
                      : "—")}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <WinnerMetric
                    label="ROI"
                    value={formatRoi(stats.winner.roi_multiple)}
                    cls="text-success"
                  />
                  <WinnerMetric
                    label="Spend"
                    value={formatCurrency(stats.winner.spend, stats.winner.currency)}
                  />
                  <WinnerMetric
                    label="Closed-won jobs"
                    value={String(stats.winner.closed_won_jobs)}
                  />
                  <WinnerMetric
                    label="Revenue"
                    value={formatCurrency(
                      stats.winner.closed_won_revenue,
                      stats.winner.currency,
                    )}
                    cls="text-success"
                  />
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  Attribution confidence:{" "}
                  <span className="font-medium text-foreground">
                    {CONFIDENCE_LABELS[stats.winner.attribution_confidence.level]}
                  </span>{" "}
                  {`(${stats.winner.attribution_confidence.attributed_closed_won_jobs}/${stats.winner.attribution_confidence.total_closed_won_jobs} jobs attributed)`}
                </p>
              </div>
            ) : (
              <div className="rounded-lg border bg-muted/30 p-4 text-center">
                <p className="text-sm font-medium">No winning source yet</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {stats.winner.reason}
                </p>
              </div>
            )}

            {stats.rows.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                No attributed closed-won jobs yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">#</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Spend</TableHead>
                    <TableHead className="text-right">Jobs</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">Cost / job</TableHead>
                    <TableHead className="text-right">ROI</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.rows.map((row) => (
                    <TableRow
                      key={`${row.source_type}-${row.lead_source_id ?? row.rank}`}
                      className={row.is_winner ? "bg-success/5" : undefined}
                    >
                      <TableCell className="text-muted-foreground">
                        {row.rank}
                      </TableCell>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {row.source_name}
                          {row.is_winner && (
                            <Badge className="bg-success text-success-foreground text-xs">
                              Winner
                            </Badge>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {sourceTypeLabel(row.source_type)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {formatCurrency(row.spend, row.currency)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.closed_won_jobs}
                      </TableCell>
                      <TableCell className="text-right text-success">
                        {formatCurrency(row.closed_won_revenue, row.currency)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.cost_per_closed_won_job === null
                          ? "—"
                          : formatCurrency(
                              row.cost_per_closed_won_job,
                              row.currency,
                            )}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {formatRoi(row.roi_multiple)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function WinnerMetric({
  label,
  value,
  cls = "text-foreground",
}: {
  label: string;
  value: string;
  cls?: string;
}) {
  return (
    <div className="rounded-md border bg-card/50 p-2 text-center">
      <div className={`text-lg font-bold ${cls}`}>{value}</div>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
