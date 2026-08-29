import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesPerformanceReport } from "@/components/reports/sales-performance-report";
import type { SalesPerformanceBreakdownRow, SalesPerformanceReport as Report } from "@/types";

const { attributionGapMock, salesPerformanceMock, useWorkspaceIdMock, canMock } = vi.hoisted(
  () => ({
  attributionGapMock: vi.fn(),
  salesPerformanceMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  canMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/reporting", () => ({
  reportingApi: {
    attributionGap: attributionGapMock,
    salesPerformance: salesPerformanceMock,
  },
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
    booked_jobs: 12,
    booked_revenue: 51_000,
    avg_booked_value: 4_250,
    quotes_issued: 30,
    quotes_approved: 12,
    revenue_approved: 51_000,
    avg_job_value: 4_250,
    median_job_value: 4_000,
    attach_rate: 0.5,
    avg_attach_value: 600,
    close_rate: 0.4,
    contacts_created: 25,
    contacts_converted: 5,
    conversion_rate: 0.2,
    appointments_booked: 15,
    appointments_completed: 9,
    appointments_no_show: 3,
    jobs_completed: 7,
    show_up_rate: 0.75,
    by_closer: [row()],
    by_lead_source: [row({ key: "google_ads", label: "Google Ads" })],
    by_primary_service: [row({ key: "gutters", label: "Gutter Cleaning" })],
    ...overrides,
  };
}

/** An untouched workspace: nothing happened, so every rate is null. */
function emptyReport(): Report {
  return report({
    booked_jobs: 0,
    booked_revenue: 0,
    avg_booked_value: null,
    quotes_issued: 0,
    quotes_approved: 0,
    revenue_approved: 0,
    avg_job_value: null,
    median_job_value: null,
    attach_rate: null,
    avg_attach_value: null,
    close_rate: null,
    contacts_created: 0,
    contacts_converted: 0,
    conversion_rate: null,
    appointments_completed: 0,
    appointments_no_show: 0,
    show_up_rate: null,
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
  attributionGapMock.mockResolvedValue({
    date_from: "2026-07-01",
    date_to: "2026-07-31",
    total_contacts: 10,
    unattributed_contacts: 2,
    attributed_contacts: 8,
    gap_rate: 0.2,
  });
  vi.setSystemTime(new Date(2026, 6, 15));
});

describe("SalesPerformanceReport", () => {
  it("surfaces contacts missing structured attribution", async () => {
    respondWith(report());

    renderReport();

    expect(await screen.findByText("Attribution blind spot")).toBeInTheDocument();
    expect(screen.getByText(/of 10 contacts · 20% missing/)).toBeInTheDocument();
    expect(
      screen.getByText(/ROI by lead source excludes these contacts/),
    ).toBeInTheDocument();
  });

  it("renders the five headline KPIs, funnel first then the money", async () => {
    respondWith(report());

    renderReport();

    expect(await screen.findByText("Conversion Rate")).toBeInTheDocument();
    expect(screen.getByText("Show-up Rate")).toBeInTheDocument();
    expect(screen.getByText("Close Rate")).toBeInTheDocument();
    expect(screen.getByText("Average Booked Job")).toBeInTheDocument();
    expect(screen.getByText("Booked Revenue")).toBeInTheDocument();
    expect(screen.getByText("$51,000.00")).toBeInTheDocument();
    // Attach rate is demoted to the breakdown body, not a headline.
    expect(screen.queryByText("Attach Rate")).not.toBeInTheDocument();
  });

  it("shows conversion and show-up rate with the denominators they rest on", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Conversion Rate");
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("25 new contacts")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("12 marked")).toBeInTheDocument();
    expect(screen.getByText("3 no-shows of 12 marked")).toBeInTheDocument();
    // Conversion lags by construction and must say so.
    expect(
      screen.getByText(/A recent window understates it/),
    ).toBeInTheDocument();
  });

  it("dashes out show-up rate until an appointment is actually marked", async () => {
    respondWith(
      report({ appointments_completed: 0, appointments_no_show: 0, show_up_rate: null }),
    );

    renderReport();

    await screen.findByText("Show-up Rate");
    // A workspace that has marked nothing is unknown, not 0% attendance.
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(
      screen.getByText("Mark past appointments attended or no-show and this fills in."),
    ).toBeInTheDocument();
    expect(screen.getByText("0 marked")).toBeInTheDocument();
  });

  it("dashes out conversion when no contact was created in the window", async () => {
    respondWith(
      report({ contacts_created: 0, contacts_converted: 0, conversion_rate: null }),
    );

    renderReport();

    await screen.findByText("Conversion Rate");
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.getByText("0 new contacts")).toBeInTheDocument();
  });

  it("still shows a real zero rate, which is a fact and not a missing value", async () => {
    respondWith(
      report({ contacts_created: 25, contacts_converted: 0, conversion_rate: 0 }),
    );

    renderReport();

    await screen.findByText("Conversion Rate");
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("flags conversion and show-up rates that rest on almost no data", async () => {
    respondWith(
      report({
        contacts_created: 3,
        contacts_converted: 3,
        conversion_rate: 1,
        appointments_completed: 2,
        appointments_no_show: 0,
        show_up_rate: 1,
      }),
    );

    renderReport();

    await screen.findByText("Conversion Rate");
    // 100% off three contacts and two appointments must not read as a win.
    expect(screen.getByText("3 new contacts · low sample")).toBeInTheDocument();
    expect(screen.getByText("2 marked · low sample")).toBeInTheDocument();
  });

  it("defaults the date range to the current calendar month", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Average Booked Job");
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

    await screen.findByText("Average Booked Job");
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
        conversion_rate: 0.15,
        show_up_rate: 0.6,
        avg_job_value: 3_900,
        revenue_approved: 44_000,
        avg_booked_value: 3_900,
        booked_revenue: 44_000,
      }),
    );

    renderReport();

    // Close rate 30% -> 40% is ten points, not "+33%".
    expect(await screen.findByText("+10.0 pts")).toBeInTheDocument();
    expect(screen.getByText("+5.0 pts")).toBeInTheDocument(); // conversion
    expect(screen.getByText("+15.0 pts")).toBeInTheDocument(); // show-up
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
        booked_jobs: 0,
        booked_revenue: 0,
        avg_booked_value: null,
        quotes_issued: 0,
        quotes_approved: 0,
        avg_job_value: null,
        close_rate: null,
        conversion_rate: null,
        show_up_rate: null,
      }),
    );

    renderReport();

    const notices = await screen.findAllByText("No prior-period data to compare");
    // Conversion, show-up, close rate and average booking lack a prior sample;
    // booked revenue can still compare against a real prior-period zero.
    expect(notices.length).toBe(4);
  });

  it("explains an empty workspace instead of rendering NaN or 0%", async () => {
    respondWith(emptyReport());

    renderReport();

    expect(
      await screen.findByText("Nothing to report in this date range"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("still reports the funnel when the window has contacts but no quotes", async () => {
    respondWith(
      report({
        booked_jobs: 0,
        booked_revenue: 0,
        avg_booked_value: null,
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
      }),
    );

    renderReport();

    // Quote metrics dash out, but conversion and show-up still have data.
    expect(await screen.findByText("Conversion Rate")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(
      screen.getByText(/No quotes were created or jobs booked in this range/),
    ).toBeInTheDocument();
  });

  it("dashes out booking averages when nothing was booked", async () => {
    respondWith(
      report({
        booked_jobs: 0,
        booked_revenue: 0,
        avg_booked_value: null,
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

    await screen.findByText("Average Booked Job");
    // A real, decided 0% close rate still shows; the undefined averages do not
    // masquerade as zero.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/No approved quote or legacy unquoted win was booked/),
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

  it("hides a rep's per-service rates until their row is expanded", async () => {
    const user = userEvent.setup();
    respondWith(
      report({
        by_closer: [
          {
            ...row({ label: "Dana Reyes", close_rate: 0.4 }),
            by_service: [
              row({
                key: "gutter_cleaning",
                label: "Gutter Cleaning",
                quotes_issued: 12,
                close_rate: 0.75,
              }),
              row({
                key: "holiday_lighting",
                label: "Holiday Lighting",
                quotes_issued: 8,
                close_rate: 0.12,
              }),
            ],
          },
        ],
      }),
    );

    renderReport();

    const closerCard = (await screen.findByText("By closer")).closest(
      "[data-slot=card]",
    ) as HTMLElement;
    const toggle = within(closerCard).getByRole("button", {
      name: /Dana Reyes/,
    });

    // Collapsed: the rep's overall rate is visible, the split is not.
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      within(closerCard).queryByText("Gutter Cleaning"),
    ).not.toBeInTheDocument();

    await user.click(toggle);

    // Expanded: the averaged 40% resolves into the two rates that produced it.
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(closerCard).getByText("Gutter Cleaning")).toBeInTheDocument();
    expect(within(closerCard).getByText("75%")).toBeInTheDocument();
    expect(within(closerCard).getByText("12%")).toBeInTheDocument();

    await user.click(toggle);
    expect(
      within(closerCard).queryByText("Gutter Cleaning"),
    ).not.toBeInTheDocument();
  });

  it("leaves a breakdown without a drill-down unexpandable", async () => {
    respondWith(report());

    renderReport();

    // Lead source carries no nested split, so its rows must not offer a control
    // that reveals nothing.
    const sourceCard = (await screen.findByText("By lead source")).closest(
      "[data-slot=card]",
    ) as HTMLElement;
    expect(within(sourceCard).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the sample size beside every rate", async () => {
    respondWith(report());

    renderReport();

    await screen.findByText("Dana Reyes");
    // Headline close rate is drawn from the 30 issued quotes; booking value
    // and booked revenue come from the 12 canonical booking events.
    expect(screen.getByText("30 quotes")).toBeInTheDocument();
    expect(screen.getAllByText("12 bookings").length).toBeGreaterThanOrEqual(2);

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
