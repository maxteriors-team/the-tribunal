"use client";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { SalesPerformanceBreakdownRow } from "@/types";

import {
  APPROVED_SAMPLE,
  describeSample,
  formatMoney,
  formatRate,
  isLowSample,
  QUOTED_SAMPLE,
  type SampleNoun,
} from "./sales-performance-metrics";

/** Metric columns a breakdown can show, beyond revenue and volume. */
export type BreakdownMetric = "closeRate" | "attachRate" | "avgJobValue";

/**
 * A rate plus the sample it was computed from.
 *
 * The rate itself is never tinted green: a 100% close rate on two quotes is
 * noise, and colouring it as a success is exactly the misread this report
 * exists to prevent. Thin samples are called out on the denominator line
 * instead, which is where the doubt actually belongs.
 */
function RateCell({
  value,
  sampleSize,
  sampleNoun,
}: {
  value: string;
  sampleSize: number;
  sampleNoun: SampleNoun;
}) {
  const low = isLowSample(sampleSize);

  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="font-medium tabular-nums">{value}</span>
      <span
        className={cn(
          "text-xs tabular-nums",
          low ? "text-warning" : "text-muted-foreground",
        )}
      >
        {describeSample(sampleSize, sampleNoun)}
        {low ? " · low sample" : ""}
      </span>
    </div>
  );
}

export interface SalesPerformanceBreakdownTableProps {
  rows: SalesPerformanceBreakdownRow[];
  currency: string;
  /** Header for the grouping column, e.g. "Closer" or "Lead source". */
  groupLabel: string;
  /**
   * Which metric columns to include. Membership only: columns always render in
   * a fixed order (close rate, attach rate, average job value) so a metric sits
   * in the same relative position in every breakdown on the page.
   */
  metrics: BreakdownMetric[];
}

export function SalesPerformanceBreakdownTable({
  rows,
  currency,
  groupLabel,
  metrics,
}: SalesPerformanceBreakdownTableProps) {
  // The API already ranks by approved revenue; re-sorting here keeps the
  // guarantee local and stable if a caller ever passes a filtered subset.
  const ranked = [...rows].sort(
    (a, b) => b.revenue_approved - a.revenue_approved,
  );

  const shows = (metric: BreakdownMetric) => metrics.includes(metric);

  return (
    <Table>
      {/* `<caption>` is only valid as the table's first child; the table's
          `caption-bottom` still renders it underneath. */}
      <TableCaption className="px-2 text-left text-xs">
        Revenue and averages count approved quotes only.
        {shows("closeRate")
          ? " Close rate is approved out of decided quotes; quotes still awaiting a customer answer are excluded rather than counted as losses."
          : ""}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>{groupLabel}</TableHead>
          <TableHead className="text-right">Revenue</TableHead>
          {/* No standalone volume column: every rate below carries the exact
              denominator it was computed from, so a separate quote count would
              just repeat one of them. */}
          {shows("closeRate") ? (
            <TableHead className="text-right">Close rate</TableHead>
          ) : null}
          {shows("attachRate") ? (
            <TableHead className="text-right">Attach rate</TableHead>
          ) : null}
          {shows("avgJobValue") ? (
            <TableHead className="text-right">Avg job value</TableHead>
          ) : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {ranked.map((row) => (
          <TableRow key={row.key ?? `unattributed-${row.label}`}>
            <TableCell
              className="max-w-[14rem] truncate font-medium"
              title={row.label}
            >
              {row.label}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMoney(row.revenue_approved, currency)}
            </TableCell>
            {shows("closeRate") ? (
              <TableCell className="text-right">
                <RateCell
                  value={formatRate(row.close_rate)}
                  sampleSize={row.quotes_issued}
                  sampleNoun={QUOTED_SAMPLE}
                />
              </TableCell>
            ) : null}
            {shows("attachRate") ? (
              <TableCell className="text-right">
                <RateCell
                  value={formatRate(row.attach_rate)}
                  sampleSize={row.quotes_approved}
                  sampleNoun={APPROVED_SAMPLE}
                />
              </TableCell>
            ) : null}
            {shows("avgJobValue") ? (
              <TableCell className="text-right">
                <RateCell
                  value={formatMoney(row.avg_job_value, currency)}
                  sampleSize={row.quotes_approved}
                  sampleNoun={APPROVED_SAMPLE}
                />
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
