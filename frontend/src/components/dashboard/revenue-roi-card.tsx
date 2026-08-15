"use client";

import { Bot, DollarSign, FileText, Megaphone, TrendingUp } from "lucide-react";

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
import type { RevenueAttributionStat, RevenueStats } from "@/lib/api/dashboard";
import { formatCurrency } from "@/lib/utils/number";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function HeadlineMetric({
  label,
  value,
  cls = "text-foreground",
}: {
  label: string;
  value: string;
  cls?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border bg-card/50 p-4 text-center">
      <div className={`text-2xl font-bold ${cls}`}>{value}</div>
      <p className="mt-1 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function AttributionTable({
  rows,
  currency,
  emptyLabel,
}: {
  rows: RevenueAttributionStat[];
  currency: string;
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">{emptyLabel}</p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead className="text-right">Booked</TableHead>
          <TableHead className="text-right">Bookings</TableHead>
          <TableHead className="text-right">Pipeline</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id}>
            <TableCell className="font-medium">{row.name}</TableCell>
            <TableCell className="text-right text-success">
              {formatCurrency(row.won_value, currency)}
            </TableCell>
            <TableCell className="text-right">{row.won_count}</TableCell>
            <TableCell className="text-right text-info">
              {formatCurrency(row.pipeline_value, currency)}
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
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-20 w-full" />
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

interface RevenueRoiCardProps {
  revenueStats: RevenueStats | undefined;
  isPending: boolean;
}

export function RevenueRoiCard({ revenueStats, isPending }: RevenueRoiCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 gradient-heading">
          <DollarSign className="size-5" />
          Revenue &amp; ROI
        </CardTitle>
        <CardDescription>
          Booked revenue traced back to the AI work that produced it
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {isPending && !revenueStats && <LoadingSkeleton />}

        {revenueStats && (
          <>
            {/* Headline money metrics */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <HeadlineMetric
                label="Booked this month"
                value={formatCurrency(
                  revenueStats.won_value_this_month,
                  revenueStats.currency,
                )}
                cls="text-success"
              />
              <HeadlineMetric
                label="Open pipeline"
                value={formatCurrency(
                  revenueStats.pipeline_value,
                  revenueStats.currency,
                )}
                cls="text-info"
              />
              <HeadlineMetric
                label="Est. AI cost (mo)"
                value={formatCurrency(
                  revenueStats.estimated_ai_cost_this_month,
                  revenueStats.currency,
                )}
                cls="text-muted-foreground"
              />
              <HeadlineMetric
                label="ROI multiple"
                value={
                  revenueStats.roi_multiple === null
                    ? "—"
                    : `${revenueStats.roi_multiple.toFixed(1)}×`
                }
                cls="text-foreground"
              />
            </div>

            {/* ROI summary line */}
            <p className="text-center text-sm text-muted-foreground">
              AI booked{" "}
              <span className="font-semibold text-foreground">
                {revenueStats.appointments_booked_this_month}
              </span>{" "}
              appts this month →{" "}
              <span className="font-semibold text-success">
                {formatCurrency(
                  revenueStats.ai_attributed_won_value_this_month,
                  revenueStats.currency,
                )}
              </span>{" "}
              AI-attributed booked revenue on{" "}
              <span className="font-semibold text-foreground">
                {formatCurrency(
                  revenueStats.estimated_ai_cost_this_month,
                  revenueStats.currency,
                )}
              </span>{" "}
              cost
              {revenueStats.roi_multiple !== null && (
                <>
                  {" "}
                  ={" "}
                  <span className="font-semibold text-success">
                    {revenueStats.roi_multiple.toFixed(1)}× ROI
                  </span>
                </>
              )}
            </p>

            {/* All-time booked total */}
            <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
              <TrendingUp className="size-4" />
              All-time booked:{" "}
              <span className="font-semibold text-foreground">
                {formatCurrency(revenueStats.won_value, revenueStats.currency)}
              </span>{" "}
              across {revenueStats.won_count} bookings
            </div>

            {/* By Agent */}
            <div className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Bot className="size-4 text-muted-foreground" />
                Revenue by Agent
              </h3>
              <AttributionTable
                rows={revenueStats.by_agent}
                currency={revenueStats.currency}
                emptyLabel="No agent-attributed revenue yet."
              />
            </div>

            {/* By Campaign */}
            <div className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Megaphone className="size-4 text-muted-foreground" />
                Revenue by Campaign
              </h3>
              <AttributionTable
                rows={revenueStats.by_campaign}
                currency={revenueStats.currency}
                emptyLabel="No campaign-attributed revenue yet."
              />
            </div>

            {/* By Prompt Version */}
            <div className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <FileText className="size-4 text-muted-foreground" />
                Revenue by Prompt Version
              </h3>
              <AttributionTable
                rows={revenueStats.by_prompt_version}
                currency={revenueStats.currency}
                emptyLabel="No prompt-attributed revenue yet."
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
