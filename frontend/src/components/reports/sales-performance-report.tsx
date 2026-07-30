"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Banknote,
  DollarSign,
  FileText,
  Minus,
  PackagePlus,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useState, type ComponentType } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useIsMounted } from "@/hooks/useMounted";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reportingApi } from "@/lib/api/reporting";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S, STATIC } from "@/lib/query-options";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type {
  AttributionGapReport as AttributionGapReportData,
  SalesPerformanceReport as SalesPerformanceReportData,
} from "@/types";

import { ReportDateRangePicker } from "./report-date-range-picker";
import {
  SalesPerformanceBreakdownTable,
  type BreakdownMetric,
} from "./sales-performance-breakdown-table";
import {
  APPROVED_SAMPLE,
  currentMonthRange,
  describeDelta,
  describeSample,
  formatMoney,
  formatRate,
  isLowSample,
  previousRange,
  QUOTED_SAMPLE,
  type DateRange,
  type MetricDelta,
  type SampleNoun,
} from "./sales-performance-metrics";

const DELTA_TONE: Record<MetricDelta["direction"], string> = {
  up: "text-success",
  down: "text-destructive",
  flat: "text-muted-foreground",
};

const DELTA_ICON: Record<
  MetricDelta["direction"],
  ComponentType<{ className?: string }>
> = {
  up: TrendingUp,
  down: TrendingDown,
  flat: Minus,
};

function DeltaLine({ delta }: { delta: MetricDelta | null }) {
  if (!delta) {
    return (
      <p className="text-xs text-muted-foreground">
        No prior-period data to compare
      </p>
    );
  }

  const Icon = DELTA_ICON[delta.direction];

  return (
    <p className="flex flex-wrap items-center gap-1 text-xs">
      <Icon className={cn("size-3.5", DELTA_TONE[delta.direction])} />
      <span className={cn("font-medium tabular-nums", DELTA_TONE[delta.direction])}>
        {delta.label}
      </span>
      <span className="text-muted-foreground">vs {delta.previousLabel} prior</span>
    </p>
  );
}

interface HeadlineCardProps {
  label: string;
  icon: ComponentType<{ className?: string }>;
  value: string;
  delta: MetricDelta | null;
  sampleSize: number;
  sampleNoun: SampleNoun;
}

function HeadlineCard({
  label,
  icon: Icon,
  value,
  delta,
  sampleSize,
  sampleNoun,
}: HeadlineCardProps) {
  const low = isLowSample(sampleSize);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
        <Icon className="size-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="space-y-1">
        <div className="text-2xl font-bold tabular-nums">{value}</div>
        <DeltaLine delta={delta} />
        <p
          className={cn(
            "text-xs tabular-nums",
            low ? "text-warning" : "text-muted-foreground",
          )}
        >
          {describeSample(sampleSize, sampleNoun)}
          {low ? " · low sample" : ""}
        </p>
      </CardContent>
    </Card>
  );
}

interface BreakdownCardProps {
  title: string;
  description: string;
  rows: SalesPerformanceReportData["by_closer"];
  currency: string;
  groupLabel: string;
  metrics: BreakdownMetric[];
  emptyTitle: string;
  emptyDescription: string;
}

function BreakdownCard({
  title,
  description,
  rows,
  currency,
  groupLabel,
  metrics,
  emptyTitle,
  emptyDescription,
}: BreakdownCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <PageEmptyState title={emptyTitle} description={emptyDescription} />
        ) : (
          <SalesPerformanceBreakdownTable
            rows={rows}
            currency={currency}
            groupLabel={groupLabel}
            metrics={metrics}
          />
        )}
      </CardContent>
    </Card>
  );
}

function AttributionGapCard({ data }: { data: AttributionGapReportData }) {
  const hasGap = data.unattributed_contacts > 0;
  const rate = data.gap_rate == null ? "—" : formatRate(data.gap_rate);

  return (
    <Card className={cn(hasGap && "border-warning/50 bg-warning/5")}>
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-2">
        <div className="space-y-1">
          <CardTitle className="text-base">Attribution blind spot</CardTitle>
          <CardDescription>
            Contacts created in this range without a structured first-touch source.
          </CardDescription>
        </div>
        <AlertTriangle
          className={cn(
            "size-5 shrink-0",
            hasGap ? "text-warning" : "text-muted-foreground",
          )}
          aria-hidden
        />
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold tabular-nums">
          {data.unattributed_contacts}
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            of {data.total_contacts} contacts · {rate} missing
          </span>
        </p>
        {hasGap && (
          <p className="mt-2 text-sm text-muted-foreground">
            ROI by lead source excludes these contacts until attribution is corrected.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SalesPerformanceBody({
  data,
  previous,
}: {
  data: SalesPerformanceReportData;
  previous: SalesPerformanceReportData | undefined;
}) {
  const { currency } = data;

  if (data.quotes_issued === 0) {
    return (
      <PageEmptyState
        icon={<FileText className="size-8" />}
        title="No quotes in this date range"
        description="Average job value, attach rate, and close rate are all computed from quotes you have sent. Send your first quote, or widen the date range, and this report will fill in."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <HeadlineCard
          label="Average Job Value"
          icon={DollarSign}
          value={formatMoney(data.avg_job_value, currency)}
          delta={describeDelta(
            data.avg_job_value,
            previous?.avg_job_value,
            "currency",
            currency,
          )}
          sampleSize={data.quotes_approved}
          sampleNoun={APPROVED_SAMPLE}
        />
        <HeadlineCard
          label="Attach Rate"
          icon={PackagePlus}
          value={formatRate(data.attach_rate)}
          delta={describeDelta(
            data.attach_rate,
            previous?.attach_rate,
            "ratio",
            currency,
          )}
          sampleSize={data.quotes_approved}
          sampleNoun={APPROVED_SAMPLE}
        />
        <HeadlineCard
          label="Close Rate"
          icon={Target}
          value={formatRate(data.close_rate)}
          delta={describeDelta(
            data.close_rate,
            previous?.close_rate,
            "ratio",
            currency,
          )}
          sampleSize={data.quotes_issued}
          sampleNoun={QUOTED_SAMPLE}
        />
        <HeadlineCard
          label="Revenue Approved"
          icon={Banknote}
          value={formatMoney(data.revenue_approved, currency)}
          delta={describeDelta(
            data.revenue_approved,
            previous?.revenue_approved,
            "currency",
            currency,
          )}
          sampleSize={data.quotes_approved}
          sampleNoun={APPROVED_SAMPLE}
        />
      </div>

      {data.quotes_approved === 0 ? (
        <Card>
          {/* `Card` already supplies py-6; no extra top padding needed. */}
          <CardContent>
            <p className="text-sm text-muted-foreground">
              None of the {data.quotes_issued} quotes in this range have been
              approved yet, so average job value and attach rate have nothing to
              average and show a dash rather than a zero. Close rate still counts
              every quote the customer has decided on.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <BreakdownCard
          title="By closer"
          description="Who is winning the work, and at what size. Ranked by approved revenue."
          rows={data.by_closer}
          currency={currency}
          groupLabel="Closer"
          metrics={["closeRate", "avgJobValue"]}
          emptyTitle="No quotes attributed to a closer"
          emptyDescription="Quotes created in this range have no owner recorded."
        />
        <BreakdownCard
          title="By lead source"
          description="Which channels send work worth quoting. Ranked by approved revenue."
          rows={data.by_lead_source}
          currency={currency}
          groupLabel="Lead source"
          metrics={["closeRate", "avgJobValue"]}
          emptyTitle="No lead-source attribution yet"
          emptyDescription="Quotes in this range are not linked to an opportunity with a lead source."
        />
      </div>

      <BreakdownCard
        title="By primary service"
        description="Where job size and add-on selling actually come from. Ranked by approved revenue."
        rows={data.by_primary_service}
        currency={currency}
        groupLabel="Service"
        metrics={["avgJobValue", "attachRate"]}
        emptyTitle="No service categories yet"
        emptyDescription="Quotes in this range have no primary service recorded."
      />
    </div>
  );
}

export function SalesPerformanceReport() {
  const { can } = useCapabilities();

  // Reports are admin-only (`reports:view`). Render a friendly no-access state
  // rather than firing requests the backend would reject with 403.
  if (!can("reports:view")) {
    return (
      <PageEmptyState
        title="No access to reports"
        description="Reporting is available to workspace admins. Ask an admin for access."
      />
    );
  }

  return <SalesPerformanceReportContent />;
}

function SalesPerformanceReportContent() {
  const workspaceId = useWorkspaceId();
  // The default window depends on today's date, which the server (UTC) and the
  // browser (local) can disagree about. Waiting for mount keeps the rendered
  // range identical on both sides instead of hydrating a different month.
  const mounted = useIsMounted();
  const [range, setRange] = useState<DateRange>(() => currentMonthRange());
  const comparisonRange = previousRange(range);

  const attributionGapQuery = useQuery({
    queryKey: queryKeys.reports.attributionGap(workspaceId ?? "", range),
    queryFn: () =>
      reportingApi.attributionGap(workspaceId ?? "", {
        date_from: range.from,
        date_to: range.to,
      }),
    enabled: Boolean(workspaceId) && mounted,
    ...POLL_60S,
    placeholderData: (previous) => previous,
  });

  const currentQuery = useQuery({
    queryKey: queryKeys.reports.salesPerformance(workspaceId ?? "", range),
    queryFn: () =>
      reportingApi.salesPerformance(workspaceId ?? "", {
        date_from: range.from,
        date_to: range.to,
      }),
    enabled: Boolean(workspaceId) && mounted,
    ...POLL_60S,
    placeholderData: (prev) => prev,
  });

  // The comparison window is historical, so it does not need the 60s poll the
  // live window gets.
  const previousQuery = useQuery({
    queryKey: queryKeys.reports.salesPerformance(
      workspaceId ?? "",
      comparisonRange,
    ),
    queryFn: () =>
      reportingApi.salesPerformance(workspaceId ?? "", {
        date_from: comparisonRange.from,
        date_to: comparisonRange.to,
      }),
    enabled: Boolean(workspaceId) && mounted,
    ...STATIC,
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Every change is measured against the equal-length window immediately
          before this one.
        </p>
        {mounted ? (
          <ReportDateRangePicker value={range} onChange={setRange} />
        ) : null}
      </div>

      {attributionGapQuery.data ? (
        <AttributionGapCard data={attributionGapQuery.data} />
      ) : null}

      {!mounted || !workspaceId || currentQuery.isPending ? (
        <PageLoadingState message="Loading sales performance…" />
      ) : currentQuery.isError || !currentQuery.data ? (
        <PageErrorState
          message={getApiErrorMessage(
            currentQuery.error,
            "Failed to load sales performance",
          )}
          onRetry={() => void currentQuery.refetch()}
        />
      ) : (
        <SalesPerformanceBody
          data={currentQuery.data}
          previous={previousQuery.data}
        />
      )}
    </div>
  );
}
