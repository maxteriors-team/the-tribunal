"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reportingApi } from "@/lib/api/reporting";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";

function ARAgingCard() {
  const workspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: queryKeys.reports.arAging(workspaceId ?? ""),
    queryFn: () => reportingApi.arAging(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Accounts Receivable Aging</CardTitle>
        <CardDescription>
          Outstanding invoice balances by how overdue they are
          {query.data ? ` · as of ${query.data.as_of}` : ""}.
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
                {formatCurrency(
                  query.data?.total_outstanding ?? 0,
                  query.data?.currency
                )}
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
                        <Badge variant="destructive">{b.label} days</Badge>
                      ) : (
                        <Badge variant="outline">{b.label} days</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {b.count}
                    </TableCell>
                    <TableCell className="text-right font-medium">
                      {formatCurrency(b.amount, query.data?.currency)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
      ? "text-emerald-500"
      : tone === "negative"
        ? "text-red-500"
        : "";
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}

function JobPnLCard() {
  const workspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: queryKeys.reports.jobPnl(workspaceId ?? ""),
    queryFn: () => reportingApi.jobPnl(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const data = query.data;
  const profit = data?.profit ?? 0;
  const marginPct =
    data?.margin === null || data?.margin === undefined
      ? "—"
      : `${(data.margin * 100).toFixed(1)}%`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Job Profitability</CardTitle>
        <CardDescription>
          Revenue from linked invoices minus tracked labor and expenses
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
                  profit >= 0 ? "text-emerald-500" : "text-red-500"
                }`}
              >
                {formatCurrency(profit, data?.currency)}
              </div>
              <div className="text-xs text-muted-foreground">
                profit · {marginPct} margin
              </div>
            </div>
            <div className="divide-y">
              <StatRow
                label="Revenue"
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
                label="Billable jobs"
                value={`${data?.billable_job_count ?? 0} of ${data?.job_count ?? 0}`}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ReportsOverview() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <ARAgingCard />
      <JobPnLCard />
    </div>
  );
}
