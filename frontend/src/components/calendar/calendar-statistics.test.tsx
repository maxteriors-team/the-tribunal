import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalendarStatistics } from "@/components/calendar/calendar-statistics";
import { reportingApi } from "@/lib/api/reporting";

vi.mock("@/lib/api/reporting", () => ({
  reportingApi: { salesPerformance: vi.fn() },
}));

vi.mock("@/components/reports/report-date-range-picker", () => ({
  ReportDateRangePicker: ({
    onChange,
  }: {
    onChange: (range: { from: string; to: string }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          from: "2026-07-01",
          to: "2026-07-31",
        })
      }
    >
      Change range
    </button>
  ),
}));

const report = {
  appointments_booked: 12,
  quotes_issued: 8,
  jobs_completed: 5,
};

describe("CalendarStatistics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(reportingApi.salesPerformance).mockResolvedValue(report as never);
  });

  it("shows calendar KPIs and reloads them for a selected date range", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <CalendarStatistics workspaceId="workspace-1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("Booked discovery calls: 12")).toBeInTheDocument();
    expect(screen.getByLabelText("Quotes sent: 8")).toBeInTheDocument();
    expect(screen.getByLabelText("Jobs completed: 5")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Change range" }));

    await waitFor(() => {
      expect(reportingApi.salesPerformance).toHaveBeenLastCalledWith("workspace-1", {
        date_from: "2026-07-01",
        date_to: "2026-07-31",
      });
    });
  });
});
