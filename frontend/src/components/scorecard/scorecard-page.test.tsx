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
