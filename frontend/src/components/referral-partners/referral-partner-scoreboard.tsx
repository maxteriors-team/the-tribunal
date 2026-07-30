"use client";

import { PhoneOutgoing } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ReferralPartnerScoreboardRow } from "@/lib/api/referral-partners";
import { cn } from "@/lib/utils";

import {
  describePartnerContext,
  describeReferralSample,
  describeSilence,
  formatMoney,
  formatRate,
  isLowSample,
  NO_VALUE,
} from "./partner-metrics";

/**
 * A rate plus the sample it was computed from.
 *
 * The rate itself is never tinted green: a 100% close rate on one referral is
 * noise, and colouring it as a success is exactly the misread this table exists
 * to prevent (same treatment as the sales-performance breakdown). Thin samples
 * are called out on the denominator line, where the doubt belongs.
 */
function RateCell({
  value,
  sampleSize,
}: {
  value: string;
  sampleSize: number;
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
        {describeReferralSample(sampleSize)}
        {low ? " · low sample" : ""}
      </span>
    </div>
  );
}

export interface ReferralPartnerScoreboardProps {
  rows: ReferralPartnerScoreboardRow[];
  currency: string;
  /** Window the server applied, so the caption states the real threshold. */
  quietAfterDays: number;
  /**
   * Call-list mode. Leads with how long each partner has been silent and drops
   * the redundant quiet badge, because every row in this view is quiet.
   */
  callList?: boolean;
}

export function ReferralPartnerScoreboard({
  rows,
  currency,
  quietAfterDays,
  callList = false,
}: ReferralPartnerScoreboardProps) {
  return (
    <Table>
      {/* `<caption>` is only valid as the table's first child; the table's
          `caption-bottom` still renders it underneath. */}
      <TableCaption className="px-2 text-left text-xs">
        Revenue and jobs count closed-won work only. Close rate is the share of a
        partner&apos;s referred leads that produced at least one closed job, so a
        repeat customer cannot push it past 100%; average job value divides that
        revenue by jobs. A partner counts as quiet after {quietAfterDays} days
        with no new referral.
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Partner</TableHead>
          <TableHead className="text-right">Revenue</TableHead>
          <TableHead className="text-right">Close rate</TableHead>
          <TableHead className="text-right">Jobs closed</TableHead>
          <TableHead className="text-right">Avg job value</TableHead>
          <TableHead className="text-right">Last referral</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const silence = describeSilence(row);
          return (
            <TableRow
              key={row.partner_id}
              className={row.is_active ? undefined : "opacity-60"}
            >
              <TableCell className="max-w-[16rem]">
                <Link
                  href={`/referral-partners/${row.partner_id}`}
                  className="truncate font-medium underline-offset-4 hover:underline"
                  title={row.name}
                >
                  {row.name}
                </Link>
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <span className="truncate text-xs text-muted-foreground">
                    {describePartnerContext(row)}
                  </span>
                  {!callList && row.is_gone_quiet ? (
                    <Badge variant="outline" className="gap-1">
                      <PhoneOutgoing className="size-3" aria-hidden />
                      Quiet
                    </Badge>
                  ) : null}
                  {row.is_active ? null : (
                    <Badge variant="outline">Inactive</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-right font-medium tabular-nums">
                {formatMoney(row.total_revenue, currency)}
              </TableCell>
              <TableCell className="text-right">
                <RateCell
                  value={formatRate(row.close_rate)}
                  sampleSize={row.referrals_sent}
                />
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.jobs_closed}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatMoney(row.average_job_value, currency)}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex flex-col items-end gap-0.5">
                  <span
                    className={cn(
                      "tabular-nums",
                      callList ? "font-medium" : undefined,
                    )}
                  >
                    {silence.headline}
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {silence.detail ?? NO_VALUE}
                  </span>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
