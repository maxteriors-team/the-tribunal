import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobCostingPanel } from "@/components/jobs/job-costing-panel";
import type { JobExpense, JobProfitability, TimeEntry } from "@/lib/api/jobs";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";

/**
 * Money scoping for the job "Field work" tab.
 *
 * Product rule: the field tier (role `technician`) sees no pricing anywhere on a
 * job — no hourly rate, no labor cost, no expenses. Profitability was already
 * gated on `billing:read`, but the currency-bearing time-entry and expense UI
 * underneath it rendered for every tier, so a technician could read and enter
 * rates and expense amounts. Clock in/out stays available as a plain start/stop.
 */

const {
  listTimeEntriesMock,
  listExpensesMock,
  profitabilityMock,
  clockInMock,
  pauseTimerMock,
  endTimerMock,
  capabilitiesMock,
} = vi.hoisted(() => ({
  listTimeEntriesMock: vi.fn(),
  listExpensesMock: vi.fn(),
  profitabilityMock: vi.fn(),
  clockInMock: vi.fn(),
  pauseTimerMock: vi.fn(),
  endTimerMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: {
      ...actual.jobsApi,
      listTimeEntries: listTimeEntriesMock,
      listExpenses: listExpensesMock,
      profitability: profitabilityMock,
      clockIn: clockInMock,
      pauseTimer: pauseTimerMock,
      endTimer: endTimerMock,
    },
  };
});

// Capabilities need a workspace provider; drive them from a role string through
// the real permission matrix instead, so the matrix and this gate stay in sync.
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

const timeEntry: TimeEntry = {
  id: "entry-1",
  job_id: "job-1",
  technician_id: "tech-1",
  started_at: "2026-07-20T14:00:00.000Z",
  ended_at: "2026-07-20T17:00:00.000Z",
  stop_reason: "manual",
  is_mine: true,
  duration_hours: 3,
  rate: 45,
  labor_cost: 135,
  note: null,
  created_at: "2026-07-20T14:00:00.000Z",
  updated_at: "2026-07-20T17:00:00.000Z",
};

const expense: JobExpense = {
  id: "expense-1",
  job_id: "job-1",
  description: "Bleach + surfactant",
  amount: 38.5,
  category: null,
  incurred_on: null,
  note: null,
  created_at: "2026-07-20T18:00:00.000Z",
  updated_at: "2026-07-20T18:00:00.000Z",
};

const profitability: JobProfitability = {
  job_id: "job-1",
  currency: "USD",
  revenue: 600,
  labor_cost: 135,
  expense_cost: 38.5,
  material_cost: 0,
  total_cost: 173.5,
  profit: 426.5,
  margin: 0.71,
  total_hours: 3,
  open_timer: false,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobCostingPanel workspaceId="ws-1" jobId="job-1" contactId={42} jobStatus="scheduled" />
    </QueryClientProvider>,
  );
}

describe("JobCostingPanel money scoping", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listTimeEntriesMock.mockResolvedValue([timeEntry]);
    listExpensesMock.mockResolvedValue([expense]);
    profitabilityMock.mockResolvedValue(profitability);
  });

  it.each(["technician", "sales_rep"])(
    "shows no pricing when %s lacks billing permission",
    async (role) => {
      signedInAs(role);
      renderPanel();

    // The logged time itself is still visible — only the money is stripped.
    expect(await screen.findByText(/3h/)).toBeInTheDocument();

    expect(screen.queryByLabelText("Hourly rate")).not.toBeInTheDocument();
    expect(screen.queryByText("Expenses")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Amount")).not.toBeInTheDocument();
    expect(screen.queryByText("Bleach + surfactant")).not.toBeInTheDocument();
    expect(screen.queryByText("Profitability")).not.toBeInTheDocument();
    // Nothing currency-shaped anywhere in the panel.
    expect(document.body.textContent).not.toMatch(/\$/);

    // Expenses are not even fetched for a tier that cannot see them.
      expect(listExpensesMock).not.toHaveBeenCalled();
      expect(profitabilityMock).not.toHaveBeenCalled();
    },
  );

  it("keeps start available to a field technician without exposing rates", async () => {
    signedInAs("technician");
    renderPanel();

    expect(await screen.findByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Hourly rate")).not.toBeInTheDocument();
  });

  it("lets a technician pause or end only their running timer", async () => {
    const user = userEvent.setup();
    const runningEntry = { ...timeEntry, ended_at: null, stop_reason: null };
    listTimeEntriesMock.mockResolvedValue([runningEntry]);
    pauseTimerMock.mockResolvedValue({ ...runningEntry, ended_at: timeEntry.ended_at });
    endTimerMock.mockResolvedValue({
      ...runningEntry,
      ended_at: timeEntry.ended_at,
      stop_reason: "ended",
    });
    signedInAs("technician");
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Pause" }));
    expect(pauseTimerMock).toHaveBeenCalledWith("ws-1", "job-1");
    await user.click(screen.getByRole("button", { name: "End" }));
    expect(endTimerMock).toHaveBeenCalledWith("ws-1", "job-1");
  });

  it("shows resume and end after the technician pauses", async () => {
    listTimeEntriesMock.mockResolvedValue([{ ...timeEntry, stop_reason: "paused", is_mine: true }]);
    signedInAs("technician");
    renderPanel();

    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "End" })).toBeInTheDocument();
  });

  it("allows a fresh timer after an ended work interval", async () => {
    listTimeEntriesMock.mockResolvedValue([{ ...timeEntry, stop_reason: "ended", is_mine: true }]);
    signedInAs("technician");
    renderPanel();

    expect(await screen.findByText("Ended")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("keeps rates, expenses, and P&L for a write-capable role", async () => {
    signedInAs("owner");
    renderPanel();

    expect(await screen.findByLabelText("Hourly rate")).toBeInTheDocument();
    expect(screen.getByText("Expenses")).toBeInTheDocument();
    expect(await screen.findByText("Bleach + surfactant")).toBeInTheDocument();
    expect(screen.getByText("$38.50")).toBeInTheDocument();
    expect(screen.getByText(/\$45\.00\/h/)).toBeInTheDocument();
    expect(screen.getByText("Profitability")).toBeInTheDocument();
  });

  it("hides costs from a manager's field crew view only, not the manager", async () => {
    signedInAs("dispatcher");
    renderPanel();

    // Dispatchers dispatch and price work — unchanged by the field-tier rule.
    expect(await screen.findByLabelText("Hourly rate")).toBeInTheDocument();
    expect(screen.getByText("Expenses")).toBeInTheDocument();
  });
});
