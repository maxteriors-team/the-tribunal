import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScorecardPage } from "@/components/scorecard/scorecard-page";
import type { ReceptionistScorecard } from "@/lib/api/scorecard";

const { getScorecardMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  getScorecardMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/scorecard", () => ({
  scorecardApi: { get: getScorecardMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function sampleScorecard(
  overrides: Partial<ReceptionistScorecard> = {},
): ReceptionistScorecard {
  return {
    start_date: "2026-01-01",
    end_date: "2026-01-31",
    calls_total: 40,
    calls_answered: 34,
    answer_rate: 85,
    missed_calls: 6,
    missed_calls_textback_sent: 6,
    missed_calls_recovered: 4,
    recovery_rate: 66.7,
    appointments_booked: 12,
    revenue_booked: 18000,
    deposits_booked: 4000,
    currency: "USD",
    after_hours_calls: 9,
    after_hours_answered: 7,
    after_hours_coverage_rate: 77.8,
    avg_handle_time_seconds: 154,
    top_call_reasons: [
      { reason: "pricing", count: 11 },
      { reason: "booking", count: 7 },
    ],
    new_leads_total: 6,
    new_leads_by_day: [
      { date: "2026-01-01", count: 4 },
      { date: "2026-01-02", count: 0 },
      { date: "2026-01-03", count: 2 },
    ],
    avg_new_leads_per_day: 2,
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ScorecardPage />
    </QueryClientProvider>,
  );
}

describe("ScorecardPage", () => {
  it("renders the receptionist scorecard metrics", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard());

    renderPage();

    expect(
      await screen.findByText("Receptionist Scorecard"),
    ).toBeInTheDocument();
    // Answered calls metric (answered / total).
    expect(await screen.findByText("34 / 40")).toBeInTheDocument();
    expect(screen.getByText("85.0% answer rate")).toBeInTheDocument();
    // Recovery + top reasons.
    expect(screen.getByText("66.7% recovery rate")).toBeInTheDocument();
    expect(screen.getByText("pricing")).toBeInTheDocument();
    expect(screen.getByText("booking")).toBeInTheDocument();
  });

  it("shows an empty state for top reasons when none exist", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(
      sampleScorecard({ top_call_reasons: [] }),
    );

    renderPage();

    expect(
      await screen.findByText("No call reasons yet"),
    ).toBeInTheDocument();
  });

  it("shows the setup empty state when there are no calls and no leads", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(
      sampleScorecard({
        calls_total: 0,
        calls_answered: 0,
        answer_rate: null,
        top_call_reasons: [],
        new_leads_total: 0,
        new_leads_by_day: [],
        avg_new_leads_per_day: null,
        appointments_booked: 0,
        revenue_booked: 0,
        deposits_booked: 0,
      }),
    );

    renderPage();

    expect(
      await screen.findByText("No receptionist calls yet"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Connect a phone number" }),
    ).toHaveAttribute("href", "/phone-numbers");
    // The metric grid is hidden until there is something to show.
    expect(screen.queryByText("Calls answered")).not.toBeInTheDocument();
  });

  it("still shows the scorecard when leads exist but no calls do", async () => {
    // Lead capture runs through forms and imports too, so zero calls must not
    // hide lead intake behind the "connect a phone number" setup prompt.
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(
      sampleScorecard({
        calls_total: 0,
        calls_answered: 0,
        answer_rate: null,
        top_call_reasons: [],
      }),
    );

    renderPage();

    expect(await screen.findByText("New leads")).toBeInTheDocument();
    expect(
      screen.queryByText("No receptionist calls yet"),
    ).not.toBeInTheDocument();
  });

  it("reports new leads per day", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard());

    renderPage();

    // Stat card: total plus the per-day average.
    expect(await screen.findByText("New leads")).toBeInTheDocument();
    expect(screen.getByText("2/day average")).toBeInTheDocument();

    // Chart: one bar per day in the range, including the zero day, each
    // labelled with its own count.
    expect(screen.getByTitle("Jan 1: 4 leads")).toBeInTheDocument();
    expect(screen.getByTitle("Jan 2: 0 leads")).toBeInTheDocument();
    expect(screen.getByTitle("Jan 3: 2 leads")).toBeInTheDocument();
  });

  it("shows an empty chart state when no leads landed in the range", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(
      sampleScorecard({
        new_leads_total: 0,
        new_leads_by_day: [
          { date: "2026-01-01", count: 0 },
          { date: "2026-01-02", count: 0 },
        ],
        avg_new_leads_per_day: 0,
      }),
    );

    renderPage();

    expect(
      await screen.findByText("No new leads in this range"),
    ).toBeInTheDocument();
  });

  it("requests data for the selected workspace", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-42");
    getScorecardMock.mockResolvedValue(sampleScorecard());

    renderPage();

    await waitFor(() => {
      expect(getScorecardMock).toHaveBeenCalledWith(
        "ws-42",
        expect.objectContaining({
          start_date: expect.any(String),
          end_date: expect.any(String),
        }),
      );
    });
  });
});
