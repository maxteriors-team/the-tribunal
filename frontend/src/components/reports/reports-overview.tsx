"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reportingApi } from "@/lib/api/reporting";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";

import { ReportDateRangePicker } from "./report-date-range-picker";
import {
  ARInvoiceDrilldown,
  COGSItemDrilldown,
  JobPnLDrilldown,
  ReportDisclosure,
  ReportPages,
} from "./report-drilldowns";
import { jobWindowParams, sameWindow, sumMoney, windowLabel } from "./report-reconciliation";
import type { DateRange } from "./sales-performance-metrics";

type PeriodProps = { window: { date_from: string; date_to: string }; useDefaults: boolean };

function monthToDate(): DateRange {
  const today = new Date().toISOString().slice(0, 10);
  return { from: `${today.slice(0, 7)}-01`, to: today };
}

function ARAgingCard() {
  const workspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: queryKeys.reports.arAging(workspaceId ?? ""),
    queryFn: () => reportingApi.arAging(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Accounts Receivable Aging</CardTitle>
        <CardDescription>
          AR as-of {query.data?.as_of ?? "loading"} (UTC). Current outstanding balances; the date
          ages invoices, not a historical balance snapshot. Unaffected by the reporting window.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!workspaceId || query.isLoading ? (
          <PageLoadingState message="Loading AR aging..." />
        ) : query.isError ? (
          <PageErrorState
            message={getApiErrorMessage(query.error, "Failed to load AR aging")}
            onRetry={() => void query.refetch()}
          />
        ) : (
          <div className="space-y-4">
            <div>
              <div className="text-2xl font-semibold">
                {formatCurrency(query.data?.total_outstanding ?? 0, query.data?.currency)}
              </div>
              <div className="text-xs text-muted-foreground">
                {query.data?.total_invoices ?? 0} open invoice
                {(query.data?.total_invoices ?? 0) === 1 ? "" : "s"} outstanding
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Age</TableHead>
                  <TableHead className="text-right">Invoices</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data?.buckets ?? []).map((b) => (
                  <TableRow key={b.label}>
                    <TableCell>
                      {b.label === "Current" ? (
                        <Badge variant="secondary">Current</Badge>
                      ) : b.label === "90+" ? (
                        <Badge className="bg-red-700 text-white dark:bg-red-600">
                          {b.label} days
                        </Badge>
                      ) : (
                        <Badge variant="outline">{b.label} days</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">{b.count}</TableCell>
                    <TableCell className="text-right font-medium">
                      {formatCurrency(b.amount, query.data?.currency)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {query.data && (
              <ReportDisclosure label="View outstanding invoices">
                <ARInvoiceDrilldown workspaceId={workspaceId} report={query.data} />
              </ReportDisclosure>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative";
}) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "negative"
        ? "text-red-700 dark:text-red-400"
        : "";
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}

/**
 * Cost of goods sold, recognized when stock is consumed and valued at the cost
 * it carried at that moment.
 *
 * Shrinkage gets its own line rather than being folded into the total: waste
 * hidden inside gross margin is waste nobody goes and fixes.
 */
function COGSCard({ window, useDefaults }: PeriodProps) {
  const workspaceId = useWorkspaceId();
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState(1);
  const [itemKey, setItemKey] = useState<string | null>(null);
  const detailId = useId();
  const params = useDefaults ? undefined : { ...window, group_by: "item" as const };
  const query = useQuery({
    queryKey: queryKeys.reports.cogs(workspaceId ?? "", params),
    queryFn: () => reportingApi.cogs(workspaceId ?? "", params),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  const data = query.data;
  const marginPct =
    data?.gross_margin === null || data?.gross_margin === undefined
      ? "—"
      : `${(data.gross_margin * 100).toFixed(1)}%`;
  const allRows = [...(data?.breakdown ?? [])].sort(
    (a, b) => b.cogs - a.cogs || a.label.localeCompare(b.label),
  );
  const item = allRows.find((row) => row.key === itemKey);
  const pageSize = expanded ? 50 : 5;
  const pages = Math.max(1, Math.ceil(allRows.length / pageSize));
  const currentPage = Math.min(page, pages);
  const breakdown = allRows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const allCost = sumMoney(
    allRows.map((row) => row.cogs),
    data?.currency,
  );
  const remainingCost = sumMoney(
    [
      allCost,
      -sumMoney(
        breakdown.map((row) => row.cogs),
        data?.currency,
      ),
    ],
    data?.currency,
  );
  const difference = sumMoney([data?.total_cogs ?? 0, -allCost], data?.currency);
  const defaultRange = monthToDate();
  const expected = useDefaults
    ? { date_from: defaultRange.from, date_to: defaultRange.to }
    : window;

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Cost of Goods Sold</CardTitle>
        <CardDescription>
          COGS window: {data ? windowLabel(data) : "loading"}. Costs posted for job usage and sales
          in this window, not lifetime job costs. Gross margin uses invoices issued in this window.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!workspaceId || query.isLoading ? (
          <PageLoadingState message="Loading COGS..." />
        ) : query.isError ? (
          <PageErrorState
            message={getApiErrorMessage(query.error, "Failed to load COGS")}
            onRetry={() => void query.refetch()}
          />
        ) : (
          <div className="space-y-3">
            <div>
              <div className="text-2xl font-semibold">
                {formatCurrency(data?.total_cogs ?? 0, data?.currency)}
              </div>
              <div className="text-xs text-muted-foreground">
                cost of goods sold · {marginPct} gross margin
              </div>
            </div>
            <div className="divide-y">
              <StatRow
                label="Shrinkage (waste, not sold)"
                value={`${formatCurrency(data?.shrinkage_cost ?? 0, data?.currency)}`}
                tone={data?.shrinkage_cost ? "negative" : undefined}
              />
              <StatRow
                label="Inventory on hand (current, not period-end)"
                value={formatCurrency(data?.ending_inventory_value ?? 0, data?.currency)}
              />
            </div>
            {data && !sameWindow(data, expected) && (
              <p role="alert" className="text-sm text-destructive">
                COGS returned a different window than requested. Use the dates shown above; refresh
                before comparing reports.
              </p>
            )}
            {!expanded && allRows.length > 5 && (
              <p className="text-sm">
                Top 5 of {allRows.length} items by COGS; remaining items are totaled below.
              </p>
            )}
            <Table aria-label="COGS by item">
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Used</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {breakdown.map((row) => (
                  <TableRow key={row.key ?? row.label}>
                    <TableCell>
                      {row.key ? (
                        <Button
                          variant="link"
                          className="h-auto whitespace-normal p-0 text-left"
                          aria-expanded={itemKey === row.key}
                          aria-controls={detailId}
                          onClick={() => setItemKey(itemKey === row.key ? null : (row.key ?? null))}
                        >
                          {row.label}
                        </Button>
                      ) : (
                        row.label
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{row.quantity}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(row.cogs, data?.currency)}
                    </TableCell>
                  </TableRow>
                ))}
                {allRows.length > breakdown.length && (
                  <TableRow>
                    <TableCell colSpan={2}>
                      Remaining {allRows.length - breakdown.length} item
                      {allRows.length - breakdown.length === 1 ? "" : "s"}
                      {expanded ? " (other pages)" : ""}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(remainingCost, data?.currency)}
                    </TableCell>
                  </TableRow>
                )}
                {difference !== 0 && (
                  <TableRow>
                    <TableCell colSpan={2}>Difference (rounding or missing detail)</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(difference, data?.currency)}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={2}>Total COGS</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCurrency(data?.total_cogs ?? 0, data?.currency)}
                  </TableCell>
                </TableRow>
              </TableFooter>
            </Table>
            {difference !== 0 && (
              <p role="alert" className="text-sm text-destructive">
                Item rows do not reconcile exactly. Refresh the report before relying on the
                breakdown.
              </p>
            )}
            {allRows.length > 5 && (
              <Button
                variant="outline"
                size="sm"
                aria-expanded={expanded}
                onClick={() => {
                  setExpanded(!expanded);
                  setPage(1);
                }}
              >
                {expanded ? "Show top 5 items" : `View all ${allRows.length} items`}
              </Button>
            )}
            {expanded && <ReportPages page={currentPage} pages={pages} onChange={setPage} />}
            <div id={detailId}>
              {item && data && (
                <COGSItemDrilldown
                  key={item.key}
                  workspaceId={workspaceId}
                  report={data}
                  item={item}
                />
              )}
            </div>
            {itemKey && data && !item && (
              <p role="status" className="text-sm">
                The selected item is no longer in this report.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function JobPnLCard({ window, useDefaults }: PeriodProps) {
  const workspaceId = useWorkspaceId();
  const params = useDefaults ? undefined : jobWindowParams(window);
  const query = useQuery({
    queryKey: queryKeys.reports.jobPnl(workspaceId ?? "", params),
    queryFn: () => reportingApi.jobPnl(workspaceId ?? "", params),
    enabled: Boolean(workspaceId),
    ...REALTIME,
  });

  const data = query.data;
  const profit = data?.profit ?? 0;
  const marginPct =
    data?.margin === null || data?.margin === undefined
      ? "—"
      : `${(data.margin * 100).toFixed(1)}%`;

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Job Profitability</CardTitle>
        <CardDescription>
          Job P&L window: {data ? windowLabel(data) : "loading"}. Jobs are selected by scheduled
          start; their lifetime labor, expenses, and materials count regardless of posting date.
          Sent, partial, paid, and overdue invoices are counted once each
          {data ? ` · ${data.job_count} jobs` : ""}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!workspaceId || query.isLoading ? (
          <PageLoadingState message="Loading job P&L..." />
        ) : query.isError ? (
          <PageErrorState
            message={getApiErrorMessage(query.error, "Failed to load job P&L")}
            onRetry={() => void query.refetch()}
          />
        ) : (
          <div className="space-y-3">
            <div>
              <div
                className={`text-2xl font-semibold ${
                  profit >= 0
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-red-700 dark:text-red-400"
                }`}
              >
                {formatCurrency(profit, data?.currency)}
              </div>
              <div className="text-xs text-muted-foreground">profit · {marginPct} margin</div>
            </div>
            <div className="divide-y">
              <StatRow
                label="Invoice revenue"
                value={formatCurrency(data?.revenue ?? 0, data?.currency)}
                tone="positive"
              />
              <StatRow
                label={`Labor · ${data?.total_hours ?? 0}h`}
                value={`−${formatCurrency(data?.labor_cost ?? 0, data?.currency)}`}
                tone="negative"
              />
              <StatRow
                label="Expenses"
                value={`−${formatCurrency(data?.expense_cost ?? 0, data?.currency)}`}
                tone="negative"
              />
              <StatRow
                label="Materials"
                value={`−${formatCurrency(data?.material_cost ?? 0, data?.currency)}`}
                tone="negative"
              />
              <StatRow
                label="Jobs with invoices"
                value={`${data?.billable_job_count ?? 0} of ${data?.job_count ?? 0}`}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Jobs with invoices includes draft and void links; those invoices add no revenue. Each
              job counts, even when jobs share an invoice. Job materials and period COGS overlap; do
              not subtract COGS again from job profit. COGS excludes returns; job materials are net
              of returns.
            </p>
            {data && !sameWindow(data, useDefaults ? {} : window) && (
              <p role="alert" className="text-sm text-destructive">
                Job P&L returned a different window than requested. Use the dates shown above;
                refresh before comparing reports.
              </p>
            )}
            {data && (
              <ReportDisclosure label="View jobs and invoice contributions">
                <JobPnLDrilldown workspaceId={workspaceId} report={data} />
              </ReportDisclosure>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ReportsOverview() {
  const { can } = useCapabilities();
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [range, setRange] = useState<DateRange>(monthToDate);
  const [useDefaults, setUseDefaults] = useState(false);
  const window = { date_from: range.from, date_to: range.to };
  const periodKey = `${workspaceId}-${useDefaults}-${range.from}-${range.to}`;

  // Reports are admin-only (reports:view). Render a friendly no-access state
  // rather than firing requests that the backend would reject with 403.
  if (!can("reports:view")) {
    return (
      <PageEmptyState
        title="No access to reports"
        description="Reporting is available to workspace admins. Ask an admin for access."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {!useDefaults && (
            <div
              role="group"
              aria-label="Reporting window (UTC)"
              className="flex flex-wrap items-center gap-2"
            >
              <span className="text-sm">Reporting window (UTC)</span>
              <ReportDateRangePicker value={range} onChange={setRange} />
            </div>
          )}
          <Button variant="outline" size="sm" onClick={() => setUseDefaults(!useDefaults)}>
            {useDefaults ? "Use shared window" : "Use report defaults"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!workspaceId}
            onClick={() =>
              void queryClient.invalidateQueries({
                queryKey: queryKeys.reports.all(workspaceId ?? ""),
              })
            }
          >
            Refresh reports and details
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          {useDefaults
            ? "Different windows: report defaults use all-time jobs and month-to-date COGS. AR remains a current balance. All-time COGS requires an explicit start date."
            : "Shared UTC window for scheduled jobs and posted COGS, not identical accounting bases. AR remains a current balance, independent of this window."}
        </p>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <ARAgingCard key={workspaceId} />
        <JobPnLCard key={`jobs-${periodKey}`} window={window} useDefaults={useDefaults} />
        <COGSCard key={`cogs-${periodKey}`} window={window} useDefaults={useDefaults} />
      </div>
    </div>
  );
}
