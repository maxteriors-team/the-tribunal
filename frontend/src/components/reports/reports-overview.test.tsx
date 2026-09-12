import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsOverview } from "@/components/reports/reports-overview";
import { invoicesApi } from "@/lib/api/invoices";
import { jobsApi } from "@/lib/api/jobs";
import type { JobPnLSummary } from "@/types";

const emptyPnl: JobPnLSummary = {
  date_from: null,
  date_to: null,
  currency: "USD",
  job_count: 0,
  billable_job_count: 0,
  revenue: 0,
  labor_cost: 0,
  expense_cost: 0,
  material_cost: 0,
  total_cost: 0,
  profit: 0,
  margin: null,
  total_hours: 0,
};

function mountReports() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <ReportsOverview />
    </QueryClientProvider>,
  );
}

const { jobPnlMock, cogsMock } = vi.hoisted(() => ({ jobPnlMock: vi.fn(), cogsMock: vi.fn() }));

vi.mock("@/lib/api/reporting", () => ({
  reportingApi: {
    jobPnl: jobPnlMock,
    arAging: vi.fn().mockResolvedValue({
      as_of: "2026-06-30",
      currency: "USD",
      total_outstanding: 0,
      total_invoices: 0,
      buckets: [],
    }),
    cogs: cogsMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-reporting" }));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  const today = new Date().toISOString().slice(0, 10);
  jobPnlMock.mockImplementation(
    async (_workspace: string, params?: { date_from?: string; date_to?: string }) => ({
      ...emptyPnl,
      date_from: params?.date_from?.slice(0, 10) ?? null,
      date_to: params?.date_to?.slice(0, 10) ?? null,
    }),
  );
  cogsMock.mockImplementation(
    async (_workspace: string, params?: { date_from?: string; date_to?: string }) => ({
      date_from: params?.date_from ?? `${today.slice(0, 7)}-01`,
      date_to: params?.date_to ?? today,
      currency: "USD",
      total_cogs: 0,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      group_by: "item",
      breakdown: [],
    }),
  );
});

afterEach(() => vi.restoreAllMocks());

describe("Job profitability reporting", () => {
  it("starts with a shared UTC month-to-date window without loading drilldowns", async () => {
    const invoices = vi.spyOn(invoicesApi, "list");
    const jobs = vi.spyOn(jobsApi, "list");
    mountReports();
    await screen.findByText("Jobs with invoices");
    const today = new Date().toISOString().slice(0, 10);
    const first = `${today.slice(0, 7)}-01`;
    expect(jobPnlMock).toHaveBeenCalledWith("ws-reporting", {
      date_from: `${first}T00:00:00Z`,
      date_to: `${today}T23:59:59.999999Z`,
    });
    expect(cogsMock).toHaveBeenCalledWith("ws-reporting", {
      date_from: first,
      date_to: today,
      group_by: "item",
    });
    expect(screen.getByText(/AR as-of 2026-06-30/)).toHaveTextContent(
      "Unaffected by the reporting window",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(invoices).not.toHaveBeenCalled();
    expect(jobs).not.toHaveBeenCalled();
  });

  it("labels all-time jobs and month-to-date COGS when API defaults are requested", async () => {
    mountReports();
    await screen.findByText("Jobs with invoices");
    fireEvent.click(screen.getByRole("button", { name: "Use report defaults" }));
    await screen.findByText(/Job P&L window: All time \(includes unscheduled jobs\)/);
    expect(jobPnlMock).toHaveBeenLastCalledWith("ws-reporting", undefined);
    expect(cogsMock).toHaveBeenLastCalledWith("ws-reporting", undefined);
    expect(screen.getByText(/Different windows: report defaults/)).toHaveTextContent(
      "all-time jobs and month-to-date COGS",
    );
    expect(screen.getByText(/COGS window:/)).toHaveTextContent(
      new Date().toISOString().slice(0, 10),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use shared window" }));
    await waitFor(() => expect(jobPnlMock.mock.lastCall?.[1]?.date_from).toMatch(/T00:00:00Z$/));
  });

  it("shows returned periods and warns when the API ignores the requested window", async () => {
    jobPnlMock.mockResolvedValue({ ...emptyPnl, date_from: null, date_to: null });
    cogsMock.mockResolvedValue({
      date_from: "2025-01-01",
      date_to: "2025-01-31",
      currency: "USD",
      total_cogs: 0,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      group_by: "item",
      breakdown: [],
    });
    mountReports();
    expect(await screen.findByText(/Job P&L returned a different window/)).toBeInTheDocument();
    expect(screen.getByText(/COGS returned a different window/)).toBeInTheDocument();
    expect(screen.getByText(/Job P&L window: All time/)).toBeInTheDocument();
    expect(screen.getByText(/COGS window: 2025-01-01 to 2025-01-31/)).toBeInTheDocument();
  });

  it("changes both flow windows through the existing picker", async () => {
    mountReports();
    await screen.findByText("Jobs with invoices");
    fireEvent.click(screen.getByRole("button", { name: /Change date range/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Last month" }));
    await waitFor(() => expect(jobPnlMock).toHaveBeenCalledTimes(2));
    const params = cogsMock.mock.lastCall?.[1];
    expect(jobPnlMock).toHaveBeenLastCalledWith("ws-reporting", {
      date_from: `${params.date_from}T00:00:00Z`,
      date_to: `${params.date_to}T23:59:59.999999Z`,
    });
    expect(params.date_from).not.toBe(`${new Date().toISOString().slice(0, 7)}-01`);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains all $600 from six $100 COGS items", async () => {
    cogsMock.mockResolvedValue({
      date_from: "2026-06-01",
      date_to: "2026-06-30",
      currency: "USD",
      total_cogs: 600,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      group_by: "item",
      breakdown: Array.from({ length: 6 }, (_, index) => ({
        key: `item-${index}`,
        label: `Material ${index + 1}`,
        cogs: 100,
        quantity: 1,
      })),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={client}>
        <ReportsOverview />
      </QueryClientProvider>,
    );
    const table = await screen.findByRole("table", { name: "COGS by item" });
    expect(within(table).getByRole("row", { name: /Remaining 1 item/ })).toHaveTextContent(
      "$100.00",
    );
    expect(within(table).getByRole("row", { name: /Total COGS/ })).toHaveTextContent("$600.00");
    fireEvent.click(screen.getByRole("button", { name: /View all 6 items/ }));
    expect(within(table).getAllByRole("button", { name: /Material/ })).toHaveLength(6);
    expect(within(table).getAllByText("$100.00")).toHaveLength(6);
    expect(within(table).queryByRole("row", { name: /Remaining/ })).not.toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /Total COGS/ })).toHaveTextContent("$600.00");
  });

  it("shows a real discrepancy rather than disguising missing rows as a remaining subtotal", async () => {
    const today = new Date().toISOString().slice(0, 10);
    cogsMock.mockResolvedValue({
      date_from: `${today.slice(0, 7)}-01`,
      date_to: today,
      currency: "USD",
      total_cogs: 600,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      group_by: "item",
      breakdown: [{ key: "item-1", label: "Materials", cogs: 500, quantity: 5 }],
    });
    mountReports();
    const table = await screen.findByRole("table", { name: "COGS by item" });
    expect(within(table).getByRole("row", { name: /Difference/ })).toHaveTextContent("$100.00");
    expect(screen.getByRole("alert")).toHaveTextContent("Item rows do not reconcile exactly");
    expect(within(table).queryByRole("row", { name: /Remaining/ })).not.toBeInTheDocument();
  });

  it("keeps every COGS page explained while limiting expanded tables to 50 items", async () => {
    const today = new Date().toISOString().slice(0, 10);
    cogsMock.mockResolvedValue({
      date_from: `${today.slice(0, 7)}-01`,
      date_to: today,
      currency: "USD",
      total_cogs: 5100,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      group_by: "item",
      breakdown: Array.from({ length: 51 }, (_, index) => ({
        key: `item-${index}`,
        label: `Material ${index}`,
        cogs: 100,
        quantity: 1,
      })),
    });
    mountReports();
    const table = await screen.findByRole("table", { name: "COGS by item" });
    fireEvent.click(screen.getByRole("button", { name: "View all 51 items" }));
    expect(within(table).getAllByRole("button", { name: /Material/ })).toHaveLength(50);
    expect(within(table).getByRole("row", { name: /Remaining 1 item/ })).toHaveTextContent(
      "$100.00",
    );
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(within(table).getAllByRole("button", { name: /Material/ })).toHaveLength(1);
    expect(within(table).getByRole("row", { name: /Remaining 50 items/ })).toHaveTextContent(
      "$5,000.00",
    );
    expect(within(table).getByRole("row", { name: /Total COGS/ })).toHaveTextContent("$5,100.00");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    { scenario: "shared issued invoice", currency: "USD", revenue: 1000, displayed: "$1,000.00" },
    { scenario: "shared void invoice", currency: "USD", revenue: 0, displayed: "$0.00" },
    { scenario: "euro invoice", currency: "EUR", revenue: 1000, displayed: "€1,000.00" },
  ])(
    "renders independent job counts and invoice revenue for $scenario",
    async ({ currency, revenue, displayed }) => {
      const summary: JobPnLSummary = {
        date_from: null,
        date_to: null,
        currency,
        job_count: 2,
        billable_job_count: 2,
        revenue,
        labor_cost: 0,
        expense_cost: 0,
        material_cost: 0,
        total_cost: 0,
        profit: revenue,
        margin: revenue ? 1 : null,
        total_hours: 0,
      };
      jobPnlMock.mockResolvedValue(summary);
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });
      render(
        <QueryClientProvider client={queryClient}>
          <ReportsOverview />
        </QueryClientProvider>,
      );

      const countLabel = await screen.findByText("Jobs with invoices");
      expect(countLabel.parentElement).toHaveTextContent("2 of 2");
      expect(screen.getByText("Invoice revenue").parentElement).toHaveTextContent(displayed);
      expect(
        screen.getByText(/Sent, partial, paid, and overdue invoices are counted once each/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/draft and void links; those invoices add no revenue/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Each job counts, even when jobs share an invoice/),
      ).toBeInTheDocument();
      const today = new Date().toISOString().slice(0, 10);
      expect(jobPnlMock).toHaveBeenCalledWith("ws-reporting", {
        date_from: `${today.slice(0, 7)}-01T00:00:00Z`,
        date_to: `${today}T23:59:59.999999Z`,
      });
    },
  );
});
