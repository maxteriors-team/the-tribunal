"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { inventoryApi } from "@/lib/api/inventory";
import { invoicesApi } from "@/lib/api/invoices";
import { jobsApi, type Job } from "@/lib/api/jobs";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { COGSReport } from "@/types/inventory";
import type { Invoice } from "@/types/invoice";
import type { ARAgingReport, JobPnLSummary } from "@/types/reporting";

import {
  issuedInvoiceRevenue,
  jobWindowParams,
  outstandingBalance,
  sumMoney,
  windowLabel,
} from "./report-reconciliation";

/** Mount queries only when opened; closing releases the detail observers. */
export function ReportDisclosure({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="space-y-3">
      <Button
        variant="outline"
        size="sm"
        className="h-auto max-w-full whitespace-normal py-2"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {label}
      </Button>
      <div id={id}>{open && children}</div>
    </div>
  );
}

export function ReportPages({
  page,
  pages,
  onChange,
}: {
  page: number;
  pages: number;
  onChange: (page: number) => void;
}) {
  if (page > Math.max(pages, 1))
    return (
      <Button variant="outline" size="sm" onClick={() => onChange(1)}>
        Records changed — return to first page
      </Button>
    );
  if (pages <= 1) return null;
  return (
    <nav aria-label="Detail pages" className="flex flex-wrap items-center gap-3 py-2">
      <Button variant="outline" size="sm" disabled={page === 1} onClick={() => onChange(page - 1)}>
        Previous page
      </Button>
      <span className="text-sm">
        Page {page} of {pages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        Next page
      </Button>
    </nav>
  );
}

function Reconciliation({
  label,
  shown,
  total,
  complete,
  currency,
}: {
  label: string;
  shown: number;
  total: number;
  complete: boolean;
  currency: string;
}) {
  const difference = sumMoney([total, -shown], currency);
  return (
    <div role="group" className="space-y-1 text-sm" aria-label={`${label} reconciliation`}>
      <p>
        This page: {formatCurrency(shown, currency)} · {label}: {formatCurrency(total, currency)}
      </p>
      {!complete ? (
        <p className="text-muted-foreground">
          Outside this page / not yet verified: {formatCurrency(difference, currency)}. Browse every
          page to check all records.
        </p>
      ) : difference !== 0 ? (
        <p role="alert" className="text-destructive">
          Difference: {formatCurrency(difference, currency)}. Rounding or records changed since the
          report; refresh before relying on these totals.
        </p>
      ) : (
        <p>All detail rows reconcile to {label.toLowerCase()}.</p>
      )}
    </div>
  );
}

function agingBucket(invoice: Invoice, asOf: string): string {
  const days = invoice.due_date
    ? (Date.parse(asOf) - Date.parse(invoice.due_date)) / 86_400_000
    : 0;
  return days <= 0
    ? "Current"
    : days <= 30
      ? "1-30"
      : days <= 60
        ? "31-60"
        : days <= 90
          ? "61-90"
          : "90+";
}

export function ARInvoiceDrilldown({
  workspaceId,
  report,
}: {
  workspaceId: string;
  report: ARAgingReport;
}) {
  const [page, setPage] = useState(1);
  const params = { page, page_size: 50 };
  const query = useQuery({
    queryKey: queryKeys.reports.arInvoices(workspaceId, report.as_of, params),
    queryFn: () => invoicesApi.list(workspaceId, params),
  });
  if (query.isPending) return <PageLoadingState message="Loading invoice details..." />;
  if (query.isError)
    return (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Could not load invoice details")}
        onRetry={() => void query.refetch()}
      />
    );
  const rows = query.data.items.filter((invoice) => outstandingBalance(invoice) > 0);
  if (rows.some((invoice) => invoice.currency !== report.currency)) {
    return (
      <PageErrorState message="Invoice currencies changed. Refresh the AR report before reconciling." />
    );
  }
  return (
    <section className="space-y-3" aria-label="Outstanding invoice details">
      <p className="text-xs text-muted-foreground">
        AR as-of {report.as_of} (UTC). Current balances, not a historical snapshot. Only sent,
        partial, or overdue invoices with positive balances count. Pages scan all invoices; settled,
        draft, and void invoices are excluded below.
      </p>
      <Table aria-label="Outstanding invoices">
        <TableHeader>
          <TableRow>
            <TableHead>Invoice / customer</TableHead>
            <TableHead>Due / age</TableHead>
            <TableHead>Total</TableHead>
            <TableHead>Paid</TableHead>
            <TableHead>Outstanding</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((invoice) => (
            <TableRow key={invoice.id}>
              <TableCell>
                {invoice.number}
                <div className="text-xs text-muted-foreground">
                  {invoice.contact_name ?? "No customer"} · {invoice.status}
                </div>
              </TableCell>
              <TableCell>
                {invoice.due_date ?? "Undated"}
                <div className="text-xs">{agingBucket(invoice, report.as_of)}</div>
              </TableCell>
              <TableCell>{formatCurrency(invoice.total, report.currency)}</TableCell>
              <TableCell>{formatCurrency(invoice.amount_paid, report.currency)}</TableCell>
              <TableCell>{formatCurrency(outstandingBalance(invoice), report.currency)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && <p className="text-sm">No outstanding invoices on this page.</p>}
      <p className="text-sm">
        {rows.length} outstanding invoices on this page · {report.total_invoices} in report.
      </p>
      {query.data.pages <= 1 && rows.length !== report.total_invoices && (
        <p role="alert">Invoice counts changed. Refresh the report before reconciling.</p>
      )}
      <Reconciliation
        label="AR outstanding"
        shown={sumMoney(rows.map(outstandingBalance), report.currency)}
        total={report.total_outstanding}
        complete={query.data.pages <= 1}
        currency={report.currency}
      />
      <ReportPages page={page} pages={query.data.pages} onChange={setPage} />
    </section>
  );
}

// simplification: the jobs API has no bulk costing endpoint. Five-job pages
// bound fan-out to ten reads; replace with server-side report details at scale.
const JOB_PAGE_SIZE = 5;

function JobDetailPage({
  workspaceId,
  jobs,
  allJobs,
  report,
}: {
  workspaceId: string;
  jobs: Job[];
  allJobs: Job[];
  report: JobPnLSummary;
}) {
  const query = useQuery({
    queryKey: queryKeys.reports.jobPnlDetails(workspaceId, {
      ...jobWindowParams(report),
      jobs: jobs.map((job) => [job.id, job.invoice_id, job.updated_at]),
    }),
    queryFn: async () => {
      const invoices = new Map<string, Promise<Invoice>>();
      return Promise.all(
        jobs.map(async (job) => {
          if (job.invoice_id && !invoices.has(job.invoice_id))
            invoices.set(job.invoice_id, invoicesApi.get(workspaceId, job.invoice_id));
          const [costs, invoice] = await Promise.all([
            jobsApi.profitability(workspaceId, job.id),
            job.invoice_id ? invoices.get(job.invoice_id) : null,
          ]);
          return { job, costs, invoice: invoice ?? null };
        }),
      );
    },
  });
  if (query.isPending) return <PageLoadingState message="Loading job and invoice details..." />;
  if (query.isError)
    return (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Could not load job details")}
        onRetry={() => void query.refetch()}
      />
    );
  if (query.data.some(({ invoice }) => invoice && invoice.currency !== report.currency)) {
    return (
      <PageErrorState message="Invoice currencies changed. Refresh the job report before reconciling." />
    );
  }
  // An invoice belongs to the first job in the whole scoped list, not the first
  // job on this page. Shared invoices therefore cannot recur across pages.
  const invoiceOwners = new Map<string, string>();
  for (const job of allJobs)
    if (job.invoice_id && !invoiceOwners.has(job.invoice_id))
      invoiceOwners.set(job.invoice_id, job.id);
  const rows = query.data.map((row) => {
    const revenue =
      row.invoice && invoiceOwners.get(row.invoice.id) === row.job.id
        ? issuedInvoiceRevenue(row.invoice)
        : 0;
    return { ...row, revenue, profit: revenue - row.costs.total_cost };
  });
  const metrics = [
    { label: "Invoice revenue", values: rows.map((row) => row.revenue), total: report.revenue },
    { label: "Labor", values: rows.map((row) => row.costs.labor_cost), total: report.labor_cost },
    {
      label: "Expenses",
      values: rows.map((row) => row.costs.expense_cost),
      total: report.expense_cost,
    },
    {
      label: "Materials",
      values: rows.map((row) => row.costs.material_cost),
      total: report.material_cost,
    },
    {
      label: "Total costs",
      values: rows.map((row) => row.costs.total_cost),
      total: report.total_cost,
    },
    { label: "Profit", values: rows.map((row) => row.profit), total: report.profit },
  ];
  return (
    <div className="space-y-3">
      <Table aria-label="Job P&L details">
        <TableHeader>
          <TableRow>
            <TableHead>Job / scheduled (UTC)</TableHead>
            <TableHead>Invoice</TableHead>
            {metrics.map(({ label }) => (
              <TableHead key={label}>{label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ job, costs, invoice, revenue, profit }) => (
            <TableRow key={job.id}>
              <TableCell>
                {job.title}
                <div className="text-xs text-muted-foreground">
                  {job.scheduled_start
                    ? new Date(job.scheduled_start).toISOString().slice(0, 10)
                    : "Unscheduled"}{" "}
                  · {job.status} · {costs.total_hours}h
                </div>
              </TableCell>
              <TableCell>
                {invoice ? (
                  <>
                    {invoice.number}
                    <div className="text-xs text-muted-foreground">
                      {invoice.status} · {invoice.contact_name ?? "No customer"}
                    </div>
                    {invoiceOwners.get(invoice.id) !== job.id && (
                      <div className="text-xs">
                        Shared invoice; revenue counted on its first listed job.
                      </div>
                    )}
                  </>
                ) : (
                  "No invoice"
                )}
              </TableCell>
              {[
                revenue,
                costs.labor_cost,
                costs.expense_cost,
                costs.material_cost,
                costs.total_cost,
                profit,
              ].map((value, index) => (
                <TableCell key={metrics[index].label} className="tabular-nums">
                  {formatCurrency(value, report.currency)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-sm">
        Labor hours: {sumMoney(rows.map((row) => row.costs.total_hours))} on this page ·{" "}
        {report.total_hours} in report.
      </p>
      <p className="text-xs text-muted-foreground">
        Revenue is a report contribution, not an allocation of a shared invoice to individual jobs.
        Draft/void invoices contribute zero; all job costs still count.
      </p>
      {metrics.map(({ label, values, total }) => (
        <Reconciliation
          key={label}
          label={label}
          shown={sumMoney(values, report.currency)}
          total={total}
          complete={jobs.length === allJobs.length}
          currency={report.currency}
        />
      ))}
    </div>
  );
}

export function JobPnLDrilldown({
  workspaceId,
  report,
}: {
  workspaceId: string;
  report: JobPnLSummary;
}) {
  const [page, setPage] = useState(1);
  const bounds = jobWindowParams(report);
  const query = useQuery({
    queryKey: queryKeys.reports.jobPnlJobs(workspaceId, bounds),
    queryFn: () => jobsApi.list(workspaceId, bounds),
  });
  if (query.isPending) return <PageLoadingState message="Loading jobs in report window..." />;
  if (query.isError)
    return (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Could not load report jobs")}
        onRetry={() => void query.refetch()}
      />
    );
  const jobs = query.data.items;
  const pages = Math.max(1, Math.ceil(jobs.length / JOB_PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  return (
    <section className="space-y-3" aria-label="Job profitability details">
      <p className="text-xs text-muted-foreground">
        Job P&L window: {windowLabel(report)}. Scoped by scheduled start; costs are lifetime costs
        of those jobs, not costs posted within the window.
      </p>
      <p className="text-sm">
        {jobs.length} jobs in details · {report.job_count} in report · {report.billable_job_count}{" "}
        with invoices.
      </p>
      {jobs.length !== report.job_count && (
        <p role="alert">Job counts changed. Refresh the report before reconciling.</p>
      )}
      {jobs.length === 0 ? (
        <PageEmptyState title="No jobs in this window" />
      ) : (
        <JobDetailPage
          key={page}
          workspaceId={workspaceId}
          jobs={jobs.slice((currentPage - 1) * JOB_PAGE_SIZE, currentPage * JOB_PAGE_SIZE)}
          allJobs={jobs}
          report={report}
        />
      )}
      <ReportPages page={currentPage} pages={pages} onChange={setPage} />
    </section>
  );
}

export function COGSItemDrilldown({
  workspaceId,
  report,
  item,
}: {
  workspaceId: string;
  report: COGSReport;
  item: COGSReport["breakdown"][number];
}) {
  const [page, setPage] = useState(1);
  const params = { page, page_size: 50 };
  const query = useQuery({
    queryKey: queryKeys.reports.cogsLedger(workspaceId, item.key ?? "", {
      date_from: report.date_from,
      date_to: report.date_to,
      ...params,
    }),
    queryFn: () => inventoryApi.listLedger(workspaceId, item.key ?? "", params),
    enabled: Boolean(item.key),
  });
  if (!item.key) return <PageEmptyState title="No item record linked to this cost" />;
  if (query.isPending) return <PageLoadingState message="Loading item cost entries..." />;
  if (query.isError)
    return (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Could not load item entries")}
        onRetry={() => void query.refetch()}
      />
    );
  const start = Date.parse(`${report.date_from}T00:00:00Z`);
  const end = Date.parse(`${report.date_to}T00:00:00Z`) + 86_400_000;
  const rows = query.data.items.filter(
    (entry) =>
      ["job_usage", "sale"].includes(entry.reason) &&
      Date.parse(entry.created_at) >= start &&
      Date.parse(entry.created_at) < end,
  );
  return (
    <section className="space-y-3" aria-label={`${item.label} cost entries`}>
      <h4 className="font-medium">
        {item.label} · {formatCurrency(item.cogs, report.currency)}
      </h4>
      <p className="text-xs text-muted-foreground">
        COGS window: {windowLabel(report)}. Posted job usage and sales only, at their recorded cost.
        Returns and shrinkage are excluded. Pages scan the item’s full ledger; only matching entries
        appear below.
      </p>
      <Table aria-label="Item cost entries">
        <TableHeader>
          <TableRow>
            <TableHead>Posted (UTC)</TableHead>
            <TableHead>Reason / reference</TableHead>
            <TableHead>Used</TableHead>
            <TableHead>Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell>
                {new Date(entry.created_at).toISOString().replace("T", " ").slice(0, 19)}
              </TableCell>
              <TableCell>
                {entry.reason === "job_usage" ? "Job usage" : "Sale"}
                <div className="text-xs text-muted-foreground">
                  {entry.note ?? entry.reference_id ?? "No reference"}
                </div>
              </TableCell>
              <TableCell>{-entry.quantity_delta}</TableCell>
              <TableCell>{formatCurrency(-entry.value_delta, report.currency)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length === 0 && (
        <p className="text-sm">No COGS entries in this window on this ledger page.</p>
      )}
      <Reconciliation
        label="Item COGS"
        shown={sumMoney(
          rows.map((entry) => -entry.value_delta),
          report.currency,
        )}
        total={item.cogs}
        complete={query.data.pages <= 1}
        currency={report.currency}
      />
      <ReportPages page={page} pages={query.data.pages} onChange={setPage} />
    </section>
  );
}
