import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScorecardPage } from "@/components/scorecard/scorecard-page";
import type {
  OfficeRepScorecardRow,
  ReceptionistScorecard,
  TechnicianActivityScorecardRow,
} from "@/lib/api/scorecard";

const { getScorecardMock, getTechniciansMock, getOfficeRepsMock, useWorkspaceIdMock, canMock } =
  vi.hoisted(() => ({
    getScorecardMock: vi.fn(),
    getTechniciansMock: vi.fn(),
    getOfficeRepsMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    canMock: vi.fn(() => true),
  }));

vi.mock("@/lib/api/scorecard", () => ({
  scorecardApi: {
    get: getScorecardMock,
    getTechnicians: getTechniciansMock,
    getOfficeReps: getOfficeRepsMock,
  },
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: canMock }),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function sampleScorecard(overrides: Partial<ReceptionistScorecard> = {}): ReceptionistScorecard {
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

function sampleTechnicians(): TechnicianActivityScorecardRow[] {
  return [
    {
      id: "tech-1",
      name: "Taylor Tech",
      active: true,
      assigned_jobs: 7,
      completed_job_time_entries: 5,
      job_logged_seconds: 18_000,
      attendance_worked_seconds: 25_200,
      attendance_paused_seconds: 1_800,
    },
  ];
}

function sampleOfficeReps(): OfficeRepScorecardRow[] {
  return [
    {
      user_id: 7,
      name: "Casey Admin",
      role: "admin",
      avatar_url: null,
      attendance_days: 18,
      attendance_worked_seconds: 432_000,
      booked_jobs: 12,
      cancelled_jobs: 1,
      cancellation_rate: 8.3,
      responses_measured: 9,
      avg_response_time_seconds: 92,
    },
  ];
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
  beforeEach(() => {
    getScorecardMock.mockReset();
    getTechniciansMock.mockReset();
    getOfficeRepsMock.mockReset();
    useWorkspaceIdMock.mockReset();
    canMock.mockReset().mockReturnValue(true);
  });

  it("fails closed without reports access", () => {
    canMock.mockReturnValue(false);
    useWorkspaceIdMock.mockReturnValue("ws-1");

    renderPage();

    expect(screen.getByText("Access denied")).toBeVisible();
    expect(getScorecardMock).not.toHaveBeenCalled();
    expect(getTechniciansMock).not.toHaveBeenCalled();
    expect(getOfficeRepsMock).not.toHaveBeenCalled();
  });

  it("renders the receptionist scorecard metrics", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard());

    renderPage();

    expect(await screen.findByText("Receptionist Scorecard")).toBeInTheDocument();
    // Answered calls metric (answered / total).
    expect(await screen.findByText("34 / 40")).toBeInTheDocument();
    expect(screen.getByText("85.0% answer rate")).toBeInTheDocument();
    // Recovery + top reasons.
    expect(screen.getByText("66.7% recovery rate")).toBeInTheDocument();
    expect(screen.getByText("pricing")).toBeInTheDocument();
    expect(screen.getByText("booking")).toBeInTheDocument();
  });

  it("shows pause-adjusted technician activity without a rating", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard());
    getTechniciansMock.mockResolvedValue(sampleTechnicians());

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "Technicians" }));

    expect(
      await screen.findByRole("heading", { name: "Technician Scorecard" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Taylor Tech")).toBeInTheDocument();
    expect(screen.getByText("7.0h")).toBeInTheDocument();
    expect(screen.getByText("0.5h")).toBeInTheDocument();
    expect(screen.getByText("Activity context—not an employee rating")).toBeInTheDocument();
    expect(screen.queryByText("Employee score")).not.toBeInTheDocument();
    expect(getTechniciansMock).toHaveBeenCalledWith(
      "ws-1",
      expect.objectContaining({ start_date: expect.any(String), end_date: expect.any(String) }),
    );
  });

  it("shows admin and CSR metrics on each private profile", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard());
    getOfficeRepsMock.mockResolvedValue(sampleOfficeReps());

    renderPage();
    await userEvent.click(screen.getByRole("tab", { name: "Admin / CSR" }));

    expect(await screen.findByRole("heading", { name: "Admin / CSR Scorecard" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Casey Admin" })).toBeVisible();
    expect(screen.getByText("Admin")).toBeVisible();
    expect(screen.getByText("18 days")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("8.3%")).toBeVisible();
    expect(screen.getByText("1m 32s")).toBeVisible();
    expect(screen.getByText("9 measured replies")).toBeVisible();
    expect(screen.getByText("Profile activity, not an automatic rating")).toBeVisible();
    expect(getOfficeRepsMock).toHaveBeenCalledWith(
      "ws-1",
      expect.objectContaining({ start_date: expect.any(String), end_date: expect.any(String) }),
    );
  });

  it("shows an empty state for top reasons when none exist", async () => {
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getScorecardMock.mockResolvedValue(sampleScorecard({ top_call_reasons: [] }));

    renderPage();

    expect(await screen.findByText("No call reasons yet")).toBeInTheDocument();
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

    expect(await screen.findByText("No receptionist calls yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect a phone number" })).toHaveAttribute(
      "href",
      "/phone-numbers",
    );
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
    expect(screen.queryByText("No receptionist calls yet")).not.toBeInTheDocument();
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

    expect(await screen.findByText("No new leads in this range")).toBeInTheDocument();
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
