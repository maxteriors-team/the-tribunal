import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { inventoryApi } from "@/lib/api/inventory";
import { invoicesApi } from "@/lib/api/invoices";
import { jobsApi, type Job, type JobProfitability } from "@/lib/api/jobs";
import type { InventoryLedgerEntry, COGSReport } from "@/types/inventory";
import type { Invoice } from "@/types/invoice";
import type { ARAgingReport, JobPnLSummary } from "@/types/reporting";

import { ARInvoiceDrilldown, COGSItemDrilldown, JobPnLDrilldown } from "./report-drilldowns";
import { jobWindowParams, sameWindow, sumMoney, windowLabel } from "./report-reconciliation";

const workspaceId = "ws-reporting";
const timestamp = "2026-06-15T12:00:00Z";

function mount(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function invoice(id: string, overrides: Partial<Invoice> = {}): Invoice {
  return {
    id,
    workspace_id: workspaceId,
    number: `INV-${id}`,
    status: "sent",
    currency: "USD",
    contact_id: 1,
    contact_name: "Test Customer",
    opportunity_id: null,
    subtotal: 150,
    discount_amount: 0,
    tax_amount: 0,
    total: 150,
    amount_paid: 50,
    issue_date: "2026-06-01",
    due_date: "2026-06-30",
    receipt_delivery: { status: "skipped" },
    created_at: timestamp,
    updated_at: timestamp,
    ...overrides,
  };
}

function job(id: string, invoiceId: string | null = null): Job {
  return {
    id,
    title: `Job ${id}`,
    invoice_id: invoiceId,
    status: "scheduled",
    contact_id: 1,
    workspace_id: workspaceId,
    business_location_id: null,
    crew_id: null,
    description: null,
    external_id: null,
    external_source: null,
    scheduled_start: timestamp,
    scheduled_end: timestamp,
    service_location_id: null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

const costs: JobProfitability = {
  job_id: "job",
  currency: "USD",
  revenue: 9999,
  labor_cost: 50,
  expense_cost: 30,
  material_cost: 20,
  total_cost: 100,
  profit: 9899,
  margin: 0.9899,
  total_hours: 1,
  open_timer: false,
};
const pnl: JobPnLSummary = {
  date_from: "2026-06-01",
  date_to: "2026-06-30",
  currency: "USD",
  job_count: 3,
  billable_job_count: 3,
  revenue: 500,
  labor_cost: 150,
  expense_cost: 90,
  material_cost: 60,
  total_cost: 300,
  profit: 200,
  margin: 0.4,
  total_hours: 3,
};
const ar: ARAgingReport = {
  as_of: "2026-06-30",
  currency: "USD",
  total_outstanding: 600,
  total_invoices: 6,
  buckets: [],
};
const cogs: COGSReport = {
  date_from: "2026-06-01",
  date_to: "2026-06-30",
  currency: "USD",
  total_cogs: 600,
  shrinkage_cost: 40,
  ending_inventory_value: 0,
  gross_margin: null,
  group_by: "item",
  breakdown: [{ key: "item-1", label: "Materials", quantity: 6, cogs: 600 }],
};

function entry(id: string, overrides: Partial<InventoryLedgerEntry> = {}): InventoryLedgerEntry {
  return {
    id,
    item_id: "item-1",
    location_id: "location-1",
    created_at: timestamp,
    occurred_at: "2026-05-01T00:00:00Z",
    quantity_delta: -1,
    value_delta: -100,
    quantity_after: 0,
    unit_cost: 100,
    unit_cost_after: 100,
    value_after: 0,
    reason: "job_usage",
    ...overrides,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("Report drilldown reconciliation", () => {
  it("explains six outstanding $100 balances and excludes draft, void, paid, and overpaid invoices", async () => {
    const rows = Array.from({ length: 6 }, (_, index) => invoice(String(index)));
    rows.push(
      invoice("draft", { status: "draft" }),
      invoice("void", { status: "void" }),
      invoice("paid", { status: "paid" }),
      invoice("credit", { amount_paid: 200 }),
    );
    const list = vi
      .spyOn(invoicesApi, "list")
      .mockResolvedValue({ items: rows, page: 1, page_size: 50, pages: 1, total: rows.length });
    mount(<ARInvoiceDrilldown workspaceId={workspaceId} report={ar} />);
    const table = await screen.findByRole("table", { name: "Outstanding invoices" });
    expect(within(table).getAllByRole("row")).toHaveLength(7);
    expect(within(table).getAllByText("$100.00")).toHaveLength(6);
    expect(screen.getByLabelText("AR outstanding reconciliation")).toHaveTextContent(
      "This page: $600.00 · AR outstanding: $600.00",
    );
    expect(screen.getByText(/All detail rows reconcile to ar outstanding/)).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith(workspaceId, { page: 1, page_size: 50 });
  });

  it("labels unverified off-page balances rather than pretending the first invoice page is complete", async () => {
    const list = vi.spyOn(invoicesApi, "list").mockImplementation(async (_workspace, params) => ({
      items: [invoice(String(params?.page))],
      page: Number(params?.page ?? 1),
      page_size: 50,
      pages: 2,
      total: 51,
    }));
    mount(<ARInvoiceDrilldown workspaceId={workspaceId} report={ar} />);
    expect(
      await screen.findByText(/Outside this page \/ not yet verified: \$500.00/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/All detail rows reconcile/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("INV-2");
    expect(list).toHaveBeenLastCalledWith(workspaceId, { page: 2, page_size: 50 });
  });

  it("surfaces changed detail totals and foreign currencies without presenting zero as success", async () => {
    const list = vi
      .spyOn(invoicesApi, "list")
      .mockResolvedValue({ items: [invoice("1")], page: 1, page_size: 50, pages: 1, total: 1 });
    const view = mount(<ARInvoiceDrilldown workspaceId={workspaceId} report={ar} />);
    expect(await screen.findByText(/Difference: \$500.00/)).toBeInTheDocument();
    expect(screen.getByText(/Invoice counts changed/)).toBeInTheDocument();
    view.unmount();
    list.mockResolvedValue({
      items: [invoice("1", { currency: "EUR" })],
      page: 1,
      page_size: 50,
      pages: 1,
      total: 1,
    });
    mount(<ARInvoiceDrilldown workspaceId={workspaceId} report={ar} />);
    expect(await screen.findByText(/Invoice currencies changed/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each(["draft", "void"] as const)(
    "reconciles shared invoices and %s costs using the corrected reporting revenue policy",
    async (status) => {
      const jobs = [job("1", "shared"), job("2", "shared"), job("3", "excluded")];
      const list = vi.spyOn(jobsApi, "list").mockResolvedValue({ items: jobs, total: jobs.length });
      vi.spyOn(jobsApi, "profitability").mockResolvedValue(costs);
      const get = vi
        .spyOn(invoicesApi, "get")
        .mockImplementation(async (_workspace, id) =>
          invoice(String(id), { total: 500, status: id === "shared" ? "sent" : status }),
        );
      mount(<JobPnLDrilldown workspaceId={workspaceId} report={pnl} />);
      const table = await screen.findByRole("table", { name: "Job P&L details" });
      expect(within(table).getAllByText("$500.00")).toHaveLength(1);
      expect(within(table).getByRole("row", { name: /Job 2/ })).toHaveTextContent(
        "Shared invoice; revenue counted on its first listed job.",
      );
      expect(within(table).queryByText("$9,999.00")).not.toBeInTheDocument();
      expect(screen.getAllByText(/All detail rows reconcile/)).toHaveLength(6);
      expect(screen.getByLabelText("Profit reconciliation")).toHaveTextContent(
        "This page: $200.00 · Profit: $200.00",
      );
      expect(get).toHaveBeenCalledTimes(2);
      expect(list).toHaveBeenCalledWith(workspaceId, {
        date_from: "2026-06-01T00:00:00Z",
        date_to: "2026-06-30T23:59:59.999999Z",
      });
    },
  );

  it("includes unscheduled jobs for all time, with no artificial date lower bound", async () => {
    const unscheduled = { ...job("unscheduled"), scheduled_start: null };
    const list = vi.spyOn(jobsApi, "list").mockResolvedValue({ items: [unscheduled], total: 1 });
    vi.spyOn(jobsApi, "profitability").mockResolvedValue(costs);
    mount(
      <JobPnLDrilldown
        workspaceId={workspaceId}
        report={{
          ...pnl,
          date_from: null,
          date_to: null,
          job_count: 1,
          billable_job_count: 0,
          revenue: 0,
          labor_cost: 50,
          expense_cost: 30,
          material_cost: 20,
          total_cost: 100,
          profit: -100,
        }}
      />,
    );
    expect(await screen.findByText(/Unscheduled · scheduled/)).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith(workspaceId, { date_from: undefined, date_to: undefined });
    expect(screen.getByLabelText("Profit reconciliation")).toHaveTextContent(
      "This page: -$100.00 · Profit: -$100.00",
    );
  });

  it("bounds costing reads per page and counts a shared invoice only once across pages", async () => {
    const jobs = Array.from({ length: 6 }, (_, index) => job(String(index + 1), "shared"));
    vi.spyOn(jobsApi, "list").mockResolvedValue({ items: jobs, total: 6 });
    const profitability = vi.spyOn(jobsApi, "profitability").mockResolvedValue(costs);
    vi.spyOn(invoicesApi, "get").mockResolvedValue(invoice("shared", { total: 500 }));
    mount(
      <JobPnLDrilldown
        workspaceId={workspaceId}
        report={{ ...pnl, job_count: 6, billable_job_count: 6 }}
      />,
    );
    await screen.findByRole("table", { name: "Job P&L details" });
    expect(profitability).toHaveBeenCalledTimes(5);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    const row = await screen.findByRole("row", { name: /Job 6/ });
    expect(within(row).getAllByRole("cell")[2]).toHaveTextContent("$0.00");
    expect(profitability).toHaveBeenCalledTimes(6);
  });

  it("uses posted date and recorded value for six $100 COGS movements, excluding returns and shrinkage", async () => {
    const entries = Array.from({ length: 6 }, (_, index) => entry(String(index)));
    entries[0] = entry("start", {
      created_at: "2026-06-01T00:00:00Z",
      reason: "sale",
      unit_cost: 999,
    });
    entries[5] = entry("end", { created_at: "2026-06-30T23:59:59.999999Z" });
    entries.push(
      entry("return", { reason: "return_to_stock", value_delta: 50 }),
      entry("shrink", { reason: "shrinkage", value_delta: -40 }),
      entry("old", { created_at: "2026-05-31T23:59:59Z", occurred_at: timestamp }),
      entry("future", { created_at: "2026-07-01T00:00:00Z" }),
    );
    const ledger = vi.spyOn(inventoryApi, "listLedger").mockResolvedValue({
      items: entries,
      page: 1,
      page_size: 50,
      pages: 1,
      total: entries.length,
    });
    mount(<COGSItemDrilldown workspaceId={workspaceId} report={cogs} item={cogs.breakdown[0]} />);
    const table = await screen.findByRole("table", { name: "Item cost entries" });
    expect(within(table).getAllByRole("row")).toHaveLength(7);
    expect(within(table).getAllByText("$100.00")).toHaveLength(6);
    expect(screen.getByLabelText("Item COGS reconciliation")).toHaveTextContent(
      "This page: $600.00 · Item COGS: $600.00",
    );
    expect(screen.getByText(/All detail rows reconcile to item cogs/)).toBeInTheDocument();
    expect(ledger).toHaveBeenCalledWith(workspaceId, "item-1", { page: 1, page_size: 50 });
  });

  it("does not replace failed detail requests with empty reconciled totals", async () => {
    vi.spyOn(inventoryApi, "listLedger").mockRejectedValue(new Error("Ledger unavailable"));
    mount(<COGSItemDrilldown workspaceId={workspaceId} report={cogs} item={cogs.breakdown[0]} />);
    await waitFor(() =>
      expect(screen.queryByText("Loading item cost entries...")).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/Ledger unavailable|Could not load item entries/)).toBeInTheDocument();
    expect(screen.queryByText(/All detail rows reconcile/)).not.toBeInTheDocument();
  });
});

describe("Report window compatibility", () => {
  it("does not equate an omitted/all-time window with a default month", () => {
    expect(sameWindow({}, { date_from: null, date_to: null })).toBe(true);
    expect(sameWindow({}, cogs)).toBe(false);
    expect(sameWindow(pnl, cogs)).toBe(true);
    expect(sameWindow(pnl, { ...cogs, date_to: "2026-06-29" })).toBe(false);
    expect(windowLabel({})).toBe("All time (includes unscheduled jobs)");
    expect(windowLabel({ date_to: "2026-06-30" })).toBe("Beginning to 2026-06-30 (UTC, inclusive)");
    expect(jobWindowParams({ date_to: "2026-06-30" })).toEqual({
      date_from: undefined,
      date_to: "2026-06-30T23:59:59.999999Z",
    });
  });

  it("sums displayed amounts with currency-aware rounding, retaining negative costs", () => {
    expect(sumMoney([0.1, 0.2, -0.05])).toBe(0.25);
    expect(sumMoney([1.005])).toBe(1.01);
    expect(sumMoney([-1.005])).toBe(-1.01);
    expect(sumMoney([50.5, 50.5], "JPY")).toBe(102);
    expect(sumMoney([0.0005, 0.0005], "KWD")).toBe(0.002);
  });
});
