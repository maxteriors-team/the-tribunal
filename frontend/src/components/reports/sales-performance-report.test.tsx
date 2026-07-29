import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesPerformanceReport } from "@/components/reports/sales-performance-report";
import type { SalesPerformanceBreakdownRow, SalesPerformanceReport as Report } from "@/types";

const { salesPerformanceMock, useWorkspaceIdMock, canMock } = vi.hoisted(() => ({
  salesPerformanceMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  canMock: vi.fn(),
}));

vi.mock("@/lib/api/reporting", () => ({
  reportingApi: { salesPerformance: salesPerformanceMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ tier: "admin", can: canMock }),
}));

function row(overrides: Partial<SalesPerformanceBreakdownRow> = {}): SalesPerformanceBreakdownRow {
  return {
    key: "user-1",
    label: "Dana Reyes",
    quotes_issued: 20,
    quotes_approved: 8,
    revenue_approved: 34_000,
    avg_job_value: 4_250,
    attach_rate: 0.5,
    close_rate: 0.4,
    ...overrides,
  };
}

function report(overrides: Partial<Report> = {}): Report {
  return {
    date_from: "2026-07-01",
    date_to: "2026-07-31",
    currency: "USD",
    quotes_issued: 30,
    quotes_approved: 12,
    revenue_approved: 51_000,
    avg_job_value: 4_250,
    median_job_value: 4_000,
    attach_rate: 0.5,
    avg_attach_value: 600,
    close_rate: 0.4,
    by_closer: [row()],
    by_lead_source: [row({ key: "google_ads", label: "Google Ads" })],
    by_primary_service: [row({ key: "gutters", label: "Gutter Cleaning" })],
    ...overrides,
  };
}

/** An untouched workspace: no quotes at all, so every rate is null. */
function emptyReport(): Report {
  return report({
    quotes_issued: 0,
    quotes_approved: 0,
    revenue_approved: 0,
    avg_job_value: null,
    median_job_value: null,
    attach_rate: null,
    avg_attach_value: null,
    close_rate: null,
    by_closer: [],
    by_lead_source: [],
    by_primary_service: [],
  });
}

/**
 * Resolve the current window with `current` and every earlier window with
 * `previous`, matching how the component fetches both.
 */
function respondWith(current: Report, previous?: Report) {
  salesPerformanceMock.mockImplementation(
    (_workspaceId: string, params: { date_from: string }) =>
      Promise.resolve(
        params.date_from === current.date_from ? current : (previous ?? current),
      ),
  );
}

function renderReport() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SalesPerformanceReport />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  canMock.mockReturnValue(true);
  vi.setSystemTime(new Date(2026, 6, 15));
});

describe("SalesPerformanceReport", () => {
  it("renders the three levers plus approved revenue", async () => {
    respondWith(report());

    renderReport();

    expect(await screen.findByText("Average Job Value")).toBeInTheDocument();
    expect(screen.getByText("Attach Rate")).toBeInTheDocument();
    expect(screen.getByText("Close Rate")).toBeInTheDocument();
    expect(screen.getByText("Revenue Approved")).toBeInTheDocument();
    expect(screen.getByText("$51,000.00")).toBeInTheDocument();
  });

  it("defaults the date range to the current calendar month", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Average Job Value");
    expect(
      salesPerformanceMock.mock.calls.some(
        ([, params]) =>
          params.date_from === "2026-07-01" && params.date_to === "2026-07-31",
      ),
    ).toBe(true);
    expect(screen.getByText("Jul 1 – Jul 31, 2026")).toBeInTheDocument();
  });

  it("also requests the previous equal-length window for the deltas", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Average Job Value");
    await waitFor(() =>
      expect(
        salesPerformanceMock.mock.calls.some(
          ([, params]) =>
            params.date_from === "2026-05-31" && params.date_to === "2026-06-30",
        ),
      ).toBe(true),
    );
  });

  it("shows rate deltas in percentage points and money deltas in currency", async () => {
    respondWith(
      report(),
      report({
        date_from: "2026-05-31",
        date_to: "2026-06-30",
        close_rate: 0.3,
        attach_rate: 0.42,
        avg_job_value: 3_900,
        revenue_approved: 44_000,
      }),
    );

    renderReport();

    // Close rate 30% -> 40% is ten points, not "+33%".
    expect(await screen.findByText("+10.0 pts")).toBeInTheDocument();
    expect(screen.getByText("+8.0 pts")).toBeInTheDocument();
    expect(screen.getByText("+$350.00")).toBeInTheDocument();
    expect(screen.getByText("+$7,000.00")).toBeInTheDocument();
    expect(screen.getByText("vs 30% prior")).toBeInTheDocument();
  });

  it("says so instead of inventing a delta when the prior window is empty", async () => {
    respondWith(
      report(),
      report({
        date_from: "2026-05-31",
        date_to: "2026-06-30",
        quotes_issued: 0,
        quotes_approved: 0,
        avg_job_value: null,
        attach_rate: null,
        close_rate: null,
      }),
    );

    renderReport();

    const notices = await screen.findAllByText("No prior-period data to compare");
    // Average job value, attach rate, and close rate all lack a baseline.
    expect(notices.length).toBe(3);
  });

  it("explains an empty workspace instead of rendering NaN or 0%", async () => {
    respondWith(emptyReport());

    renderReport();

    expect(
      await screen.findByText("No quotes in this date range"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("dashes out averages that have no approvals to average", async () => {
    respondWith(
      report({
        quotes_issued: 9,
        quotes_approved: 0,
        revenue_approved: 0,
        avg_job_value: null,
        attach_rate: null,
        close_rate: 0,
        by_closer: [
          row({ quotes_approved: 0, revenue_approved: 0, avg_job_value: null, close_rate: 0 }),
        ],
        by_lead_source: [],
        by_primary_service: [],
      }),
    );

    renderReport();

    await screen.findByText("Average Job Value");
    // A real, decided 0% close rate still shows; the undefined averages do not
    // masquerade as zero.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/have nothing to average and show a dash rather than a zero/),
    ).toBeInTheDocument();
  });

  it("marks a flattering rate that rests on almost no quotes", async () => {
    respondWith(
      report({
        by_closer: [
          row({
            key: "user-2",
            label: "Sam Okafor",
            quotes_issued: 2,
            quotes_approved: 2,
            revenue_approved: 5_000,
            close_rate: 1,
          }),
        ],
      }),
    );

    renderReport();

    await screen.findByText("Sam Okafor");
    // 100% close rate on two quotes must not read as a win.
    const closerCard = screen
      .getByText("By closer")
      .closest("[data-slot=card]") as HTMLElement;
    expect(within(closerCard).getByText("100%")).toBeInTheDocument();
    expect(within(closerCard).getByText("2 quotes · low sample")).toBeInTheDocument();
  });

  it("shows the sample size beside every rate", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Dana Reyes");
    // Headline close rate is drawn from the 30 issued quotes; average job value
    // and attach rate from the 12 approved ones.
    expect(screen.getByText("30 quotes")).toBeInTheDocument();
    expect(screen.getAllByText("12 approved").length).toBeGreaterThanOrEqual(2);

    // Each breakdown row carries its own denominator too.
    const closerCard = (await screen.findByText("By closer")).closest(
      "[data-slot=card]",
    ) as HTMLElement;
    expect(within(closerCard).getByText("20 quotes")).toBeInTheDocument();
    expect(within(closerCard).getByText("8 approved")).toBeInTheDocument();
  });

  it("ranks breakdown rows by approved revenue descending", async () => {
    respondWith(
      report({
        by_lead_source: [
          row({ key: "organic", label: "Organic", revenue_approved: 9_000 }),
          row({ key: "google_ads", label: "Google Ads", revenue_approved: 40_000 }),
          row({ key: null, label: "Unattributed", revenue_approved: 21_000 }),
        ],
      }),
    );

    renderReport();

    const table = within(
      (await screen.findByText("By lead source")).closest("[data-slot=card]") as HTMLElement,
    ).getByRole("table");
    const names = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent);

    expect(names).toEqual(["Google Ads", "Unattributed", "Organic"]);
  });

  it("breaks average job value and attach rate down by service", async () => {
    respondWith(report());

    renderReport();

    expect(await screen.findByText("By primary service")).toBeInTheDocument();
    const card = (await screen.findByText("By primary service")).closest(
      "[data-slot=card]",
    ) as HTMLElement;
    expect(within(card).getByText("Gutter Cleaning")).toBeInTheDocument();
    expect(within(card).getByText("Avg job value")).toBeInTheDocument();
    expect(within(card).getByText("Attach rate")).toBeInTheDocument();
  });

  it("keeps the report behind the reports:view capability", () => {
    canMock.mockReturnValue(false);

    renderReport();

    expect(screen.getByText("No access to reports")).toBeInTheDocument();
    expect(salesPerformanceMock).not.toHaveBeenCalled();
  });

  it("offers a retry when the report fails to load", async () => {
    salesPerformanceMock.mockRejectedValue(new Error("boom"));

    renderReport();

    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
