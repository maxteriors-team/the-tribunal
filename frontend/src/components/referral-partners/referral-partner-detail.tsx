"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Mail, Pencil, Phone, PhoneOutgoing, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Separator } from "@/components/ui/separator";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { referralPartnersApi } from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";

import {
  describeReferralSample,
  describeSilence,
  formatMoney,
  formatRate,
  isLowSample,
  NO_VALUE,
  partnerTypeLabel,
} from "./partner-metrics";
import { ReferralPartnerDialog } from "./referral-partner-dialog";

const QUIET_AFTER_DAYS = 60;

/**
 * One production figure.
 *
 * `sample` carries the denominator a rate was computed from; without it a rate
 * is not a fact. Values are never colour-coded as good or bad — a 100% close
 * rate on one referral would be the loudest lie on the page.
 */
function Stat({
  label,
  value,
  sample,
  emphasis = false,
}: {
  label: string;
  value: string;
  sample?: string;
  emphasis?: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={
          emphasis
            ? "text-2xl font-semibold tabular-nums"
            : "text-lg font-medium tabular-nums"
        }
      >
        {value}
      </dd>
      {sample ? (
        <p className="text-xs text-muted-foreground tabular-nums">{sample}</p>
      ) : null}
    </div>
  );
}

export function ReferralPartnerDetail({ partnerId }: { partnerId: string }) {
  const workspaceId = useWorkspaceId();
  const [editOpen, setEditOpen] = useState(false);
  // Mirrors the manager-and-up gate on the write routes; the API still enforces it.
  const { can } = useCapabilities();
  const canManage = can("crm:write");

  const partnerQuery = useQuery({
    queryKey: queryKeys.referralPartners.detail(workspaceId ?? "", partnerId),
    queryFn: () => referralPartnersApi.get(workspaceId ?? "", partnerId),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  // The scoreboard is the only source of a partner's production, so the detail
  // view reads the same numbers the ranked table shows rather than recomputing
  // them here and risking a second, disagreeing answer.
  const scoreboardParams = { quiet_after_days: QUIET_AFTER_DAYS };
  const scoreboardQuery = useQuery({
    queryKey: queryKeys.referralPartners.scoreboard(
      workspaceId ?? "",
      scoreboardParams,
    ),
    queryFn: () => referralPartnersApi.scoreboard(workspaceId ?? "", scoreboardParams),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  const backLink = (
    <Button variant="ghost" size="sm" asChild>
      <Link href="/referral-partners">
        <ArrowLeft className="mr-1.5 size-4" aria-hidden />
        All partners
      </Link>
    </Button>
  );

  if (!workspaceId || partnerQuery.isPending) {
    return <PageLoadingState message="Loading partner..." />;
  }

  if (partnerQuery.isError || !partnerQuery.data) {
    return (
      <div className="space-y-4">
        {backLink}
        <PageErrorState
          message={getApiErrorMessage(partnerQuery.error, "Partner not found")}
          onRetry={() => void partnerQuery.refetch()}
        />
      </div>
    );
  }

  const partner = partnerQuery.data;
  const row = scoreboardQuery.data?.items.find(
    (item) => item.partner_id === partnerId,
  );
  const currency = scoreboardQuery.data?.currency ?? "USD";
  const silence = row ? describeSilence(row) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          {backLink}
          <h1 className="text-2xl font-semibold tracking-tight">{partner.name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            {partner.company ? (
              <span className="text-sm text-muted-foreground">
                {partner.company}
              </span>
            ) : null}
            <Badge variant="outline">
              {partnerTypeLabel(partner.partner_type)}
            </Badge>
            {partner.is_active ? null : <Badge variant="outline">Inactive</Badge>}
            {row?.is_gone_quiet ? (
              <Badge variant="outline" className="gap-1">
                <PhoneOutgoing className="size-3" aria-hidden />
                Quiet {QUIET_AFTER_DAYS}+ days
              </Badge>
            ) : null}
          </div>
        </div>
        {canManage ? (
          <Button size="sm" variant="outline" onClick={() => setEditOpen(true)}>
            <Pencil className="mr-1.5 size-4" aria-hidden />
            Edit partner
          </Button>
        ) : null}
      </div>

      <section aria-labelledby="partner-production-heading" className="space-y-3">
        <h2 id="partner-production-heading" className="text-sm font-medium">
          Production
        </h2>
        {scoreboardQuery.isPending ? (
          <PageLoadingState message="Loading production..." className="min-h-[120px]" />
        ) : scoreboardQuery.isError ? (
          <PageErrorState
            className="min-h-[120px]"
            message={getApiErrorMessage(
              scoreboardQuery.error,
              "Failed to load production",
            )}
            onRetry={() => void scoreboardQuery.refetch()}
          />
        ) : (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5 rounded-lg border p-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat
              label="Booked revenue"
              value={formatMoney(row?.total_revenue ?? 0, currency)}
              emphasis
            />
            <Stat
              label="Referrals sent"
              value={formatNumber(row?.referrals_sent ?? 0)}
            />
            <Stat
              label="Close rate"
              value={formatRate(row?.close_rate)}
              sample={
                row && row.referrals_sent > 0
                  ? `${describeReferralSample(row.referrals_sent)}${
                      isLowSample(row.referrals_sent) ? " · low sample" : ""
                    }`
                  : undefined
              }
            />
            <Stat
              label="Booked jobs"
              value={formatNumber(row?.jobs_closed ?? 0)}
              sample={
                row?.average_job_value !== null && row?.average_job_value !== undefined
                  ? `${formatMoney(row.average_job_value, currency)} avg booked`
                  : undefined
              }
            />
            <Stat
              label="Last referral"
              value={silence?.headline ?? NO_VALUE}
              sample={silence?.detail ?? undefined}
            />
          </dl>
        )}
      </section>

      <section aria-labelledby="partner-details-heading" className="space-y-3">
        <h2 id="partner-details-heading" className="text-sm font-medium">
          Details
        </h2>
        <div className="space-y-3 rounded-lg border p-4 text-sm">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <span className="flex items-center gap-2">
              <Phone className="size-4 text-muted-foreground" aria-hidden />
              {partner.phone ? (
                <a
                  href={`tel:${partner.phone}`}
                  className="underline-offset-4 hover:underline"
                >
                  {partner.phone}
                </a>
              ) : (
                <span className="text-muted-foreground">No phone recorded</span>
              )}
            </span>
            <span className="flex items-center gap-2">
              <Mail className="size-4 text-muted-foreground" aria-hidden />
              {partner.email ? (
                <a
                  href={`mailto:${partner.email}`}
                  className="underline-offset-4 hover:underline"
                >
                  {partner.email}
                </a>
              ) : (
                <span className="text-muted-foreground">No email recorded</span>
              )}
            </span>
            {partner.contact_id ? (
              <span className="flex items-center gap-2">
                <User className="size-4 text-muted-foreground" aria-hidden />
                <Link
                  href={`/contacts/${partner.contact_id}`}
                  className="underline-offset-4 hover:underline"
                >
                  Also a contact in your CRM
                </Link>
              </span>
            ) : null}
          </div>
          {partner.notes ? (
            <>
              <Separator />
              <p className="whitespace-pre-wrap text-muted-foreground">
                {partner.notes}
              </p>
            </>
          ) : null}
        </div>
      </section>

      <ReferralPartnerDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        partner={partner}
      />
    </div>
  );
}
