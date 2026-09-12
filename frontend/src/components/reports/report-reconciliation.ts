import type { Invoice } from "@/types/invoice";

export type ReportWindow = { date_from?: string | null; date_to?: string | null };

export function windowLabel(window: ReportWindow): string {
  if (!window.date_from && !window.date_to) return "All time (includes unscheduled jobs)";
  return `${window.date_from ?? "Beginning"} to ${window.date_to ?? "Present"} (UTC, inclusive)`;
}

/** Both reports use UTC. P&L accepts timestamps; COGS accepts inclusive dates. */
export function jobWindowParams(window: ReportWindow) {
  return {
    date_from: window.date_from ? `${window.date_from}T00:00:00Z` : undefined,
    date_to: window.date_to ? `${window.date_to}T23:59:59.999999Z` : undefined,
  };
}

export function sameWindow(left: ReportWindow, right: ReportWindow): boolean {
  return (
    (left.date_from ?? null) === (right.date_from ?? null) &&
    (left.date_to ?? null) === (right.date_to ?? null)
  );
}

// Presentation projections of reporting_service.py (f3a85a4b), not a second
// costing engine. In particular, per-job profitability.revenue includes drafts
// and voids; it must NOT be summed to reproduce the issued-invoice report.
export function issuedInvoiceRevenue(invoice: Invoice | null): number {
  return invoice && ["sent", "partial", "paid", "overdue"].includes(invoice.status)
    ? invoice.total
    : 0;
}

export function outstandingBalance(invoice: Invoice): number {
  return ["sent", "partial", "overdue"].includes(invoice.status)
    ? Math.max(0, invoice.total - invoice.amount_paid)
    : 0;
}

/** Sum displayed amounts, using the same Intl rounding as formatCurrency. */
export function sumMoney(amounts: number[], currency = "USD"): number {
  const digits =
    new Intl.NumberFormat("en-US", { style: "currency", currency }).resolvedOptions()
      .maximumFractionDigits ?? 2;
  const formatter = new Intl.NumberFormat("en-US", {
    useGrouping: false,
    maximumFractionDigits: digits,
  });
  const scale = 10 ** digits;
  return (
    amounts.reduce(
      (total, amount) => total + Math.round(Number(formatter.format(amount)) * scale),
      0,
    ) / scale
  );
}
