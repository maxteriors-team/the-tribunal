import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsOverview } from "@/components/reports/reports-overview";
import type { JobPnLSummary } from "@/types";

const { jobPnlMock } = vi.hoisted(() => ({ jobPnlMock: vi.fn() }));

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
    cogs: vi.fn().mockResolvedValue({
      date_from: "2026-06-01",
      date_to: "2026-06-30",
      currency: "USD",
      total_cogs: 0,
      shrinkage_cost: 0,
      ending_inventory_value: 0,
      gross_margin: null,
      breakdown: [],
    }),
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-reporting" }));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Job profitability reporting", () => {
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
        screen.getByText(/Sent, partial, paid, and overdue invoices, counted once each/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/draft and void links; those invoices add no revenue/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Each job counts, even when jobs share an invoice/),
      ).toBeInTheDocument();
      expect(jobPnlMock).toHaveBeenCalledWith("ws-reporting");
    },
  );
});
