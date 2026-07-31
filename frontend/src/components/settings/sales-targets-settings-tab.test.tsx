import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SalesTargetsSettingsTab,
  backsolveFunnel,
  describeBacksolve,
  seedFromTargets,
  validatePlan,
  type PlanDraft,
} from "@/components/settings/sales-targets-settings-tab";
import type { RevenueTarget } from "@/lib/api/revenue-targets";

const { listMock, bulkUpsertMock, useWorkspaceIdMock, toastError, toastSuccess } =
  vi.hoisted(() => ({
    listMock: vi.fn(),
    bulkUpsertMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastError: vi.fn(),
    toastSuccess: vi.fn(),
  }));

vi.mock("@/lib/api/revenue-targets", () => ({
  revenueTargetsApi: {
    list: listMock,
    bulkUpsert: bulkUpsertMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Frozen "today" so month arithmetic and the writable-month rule are stable. */
const TODAY = new Date(2026, 2, 15); // 15 March 2026

function plan(overrides: Partial<PlanDraft> = {}): PlanDraft {
  return {
    revenueGoal: "100000",
    avgJobValue: "5000",
    closeRate: "36",
    satRate: "60",
    targetLeads: "",
    estimateCapacity: "",
    crewHours: "",
    backlogWeeks: "",
    ...overrides,
  };
}

function target(month: number, overrides: Partial<RevenueTarget> = {}): RevenueTarget {
  return {
    id: `rt-${month}`,
    workspace_id: "ws-1",
    period_month: `2026-${String(month).padStart(2, "0")}-01`,
    revenue_goal: 50000,
    target_avg_job_value: 5000,
    target_close_rate: 36,
    assumed_sat_rate: 60,
    target_leads: null,
    estimate_capacity_per_month: null,
    crew_capacity_hours_per_week: null,
    backlog_alert_weeks: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <SalesTargetsSettingsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(TODAY);
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listMock.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Pure backsolve maths
// ---------------------------------------------------------------------------

describe("backsolveFunnel", () => {
  it("turns a goal into raw job, estimate and lead requirements", () => {
    const funnel = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });

    expect(funnel.jobs).toBe(20);
    expect(funnel.estimates).toBeCloseTo(55.5556, 3);
    expect(funnel.leads).toBeCloseTo(92.5926, 3);
  });

  it("keeps stages unrounded so rounding never compounds down the chain", () => {
    const funnel = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });

    // Ceiling estimates (56) before dividing would report 94 leads. The honest
    // answer from the raw 55.5556 estimates is 93.
    expect(Math.ceil(funnel.leads as number)).toBe(93);
    expect(Math.ceil((Math.ceil(funnel.estimates as number) / 0.6))).toBe(94);
  });

  it("reports nothing downstream of a missing assumption", () => {
    const noAvgJobValue = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: null,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });
    expect(noAvgJobValue).toEqual({ jobs: null, estimates: null, leads: null });

    const noCloseRate = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: null,
      satRatePct: 60,
      targetLeads: null,
    });
    expect(noCloseRate.jobs).toBe(20);
    expect(noCloseRate.estimates).toBeNull();
    expect(noCloseRate.leads).toBeNull();
  });

  it("treats a non-positive divisor as unknown rather than dividing", () => {
    const funnel = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: 0,
      closeRatePct: 0,
      satRatePct: 0,
      targetLeads: null,
    });

    expect(funnel.jobs).toBeNull();
    expect(funnel.estimates).toBeNull();
    expect(funnel.leads).toBeNull();
  });

  it("lets a hand-set lead target override the derived one", () => {
    const funnel = backsolveFunnel({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: 140,
    });

    expect(funnel.leads).toBe(140);
    expect(funnel.estimates).toBeCloseTo(55.5556, 3);
  });
});

describe("describeBacksolve", () => {
  it("states the full chain a goal implies, rounding counts up", () => {
    const readout = describeBacksolve({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });

    expect(readout.sentence).toBe(
      "$100,000 at $5,000 avg job = 20 jobs, at 36% close = 56 estimates, at 60% sat rate = 93 leads/month.",
    );
    expect(readout.missing).toBeNull();
  });

  it("asks for a goal before it claims anything", () => {
    const readout = describeBacksolve({
      revenueGoal: null,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });

    expect(readout.sentence).toBe("");
    expect(readout.missing).toMatch(/monthly revenue goal/i);
  });

  it("truncates at the first missing assumption and names it", () => {
    const noAvg = describeBacksolve({
      revenueGoal: 100_000,
      avgJobValue: null,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: null,
    });
    expect(noAvg.sentence).toBe("$100,000/month.");
    expect(noAvg.missing).toMatch(/average job value/i);

    const noClose = describeBacksolve({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: null,
      satRatePct: 60,
      targetLeads: null,
    });
    expect(noClose.sentence).toBe("$100,000 at $5,000 avg job = 20 jobs.");
    expect(noClose.missing).toMatch(/close rate/i);
  });

  it("credits a hand-set lead target instead of backsolving leads", () => {
    const readout = describeBacksolve({
      revenueGoal: 100_000,
      avgJobValue: 5_000,
      closeRatePct: 36,
      satRatePct: 60,
      targetLeads: 140,
    });

    expect(readout.sentence).toBe(
      "$100,000 at $5,000 avg job = 20 jobs, at 36% close = 56 estimates, 140 leads/month (your target).",
    );
    expect(readout.missing).toBeNull();
  });
});

describe("validatePlan", () => {
  it("accepts a complete plan", () => {
    expect(validatePlan(plan())).toEqual({});
  });

  it("requires a revenue goal above zero", () => {
    expect(validatePlan(plan({ revenueGoal: "" })).revenueGoal).toBeDefined();
    expect(validatePlan(plan({ revenueGoal: "0" })).revenueGoal).toBeDefined();
    expect(validatePlan(plan({ revenueGoal: "-5" })).revenueGoal).toBeDefined();
  });

  it("rejects a non-positive average job value but allows a blank one", () => {
    expect(validatePlan(plan({ avgJobValue: "0" })).avgJobValue).toBeDefined();
    expect(validatePlan(plan({ avgJobValue: "" })).avgJobValue).toBeUndefined();
  });

  it("bounds the close rate to 1..100", () => {
    expect(validatePlan(plan({ closeRate: "0" })).closeRate).toBeDefined();
    expect(validatePlan(plan({ closeRate: "101" })).closeRate).toBeDefined();
    expect(validatePlan(plan({ closeRate: "100" })).closeRate).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Seeding a saved year back into the editor
// ---------------------------------------------------------------------------

describe("seedFromTargets", () => {
  it("derives the default from the months that share a plan and flags the rest", () => {
    const targets = [
      ...[3, 4, 5, 7, 8, 9, 10, 11, 12].map((month) => target(month)),
      target(6, { revenue_goal: 130000 }),
    ];

    const seed = seedFromTargets(targets, 2026, TODAY);

    expect(seed.defaults.revenueGoal).toBe("50000");
    expect(seed.months[5].override?.revenueGoal).toBe("130000");
    expect(seed.months[2].override).toBeNull();
    expect(seed.months.filter((m) => m.override !== null)).toHaveLength(1);
  });

  it("ignores already-passed months when deriving the default", () => {
    // January and February are history at TODAY, and their goals must not
    // become the default for the rest of the year.
    const targets = [
      target(1, { revenue_goal: 9000 }),
      target(2, { revenue_goal: 9000 }),
      target(3, { revenue_goal: 60000 }),
    ];

    const seed = seedFromTargets(targets, 2026, TODAY);

    expect(seed.defaults.revenueGoal).toBe("60000");
    expect(seed.months[0].override?.revenueGoal).toBe("9000");
  });

  it("falls back to an empty plan when the year has no targets", () => {
    const seed = seedFromTargets([], 2026, TODAY);

    expect(seed.defaults.revenueGoal).toBe("");
    expect(seed.defaults.satRate).toBe("60");
    expect(seed.months).toHaveLength(12);
    expect(seed.months.every((m) => m.override === null && !m.stored)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Rendered tab
// ---------------------------------------------------------------------------

describe("SalesTargetsSettingsTab", () => {
  it("shows the live backsolve as the operator types a goal", async () => {
    const user = userEvent.setup();
    renderTab();

    const goal = await screen.findByLabelText("Monthly revenue goal ($)");
    await user.type(goal, "100000");
    await user.type(screen.getByLabelText("Target average job value ($)"), "5000");
    await user.type(screen.getByLabelText("Target close rate (%)"), "36");

    expect(
      await screen.findByText(
        "$100,000 at $5,000 avg job = 20 jobs, at 36% close = 56 estimates, at 60% sat rate = 93 leads/month.",
      ),
    ).toBeInTheDocument();
  });

  it("disables save while the plan is invalid", async () => {
    const user = userEvent.setup();
    renderTab();

    const save = await screen.findByRole("button", { name: /save sales targets/i });
    // No goal yet, so the plan cannot be committed.
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Monthly revenue goal ($)"), "100000");
    await waitFor(() => expect(save).toBeEnabled());

    await user.type(screen.getByLabelText("Target close rate (%)"), "150");
    await waitFor(() => expect(save).toBeDisabled());
    expect(
      screen.getByText("Close rate must be between 1 and 100."),
    ).toBeInTheDocument();
  });

  it("writes the default to every remaining month and the override to its own", async () => {
    const user = userEvent.setup();
    bulkUpsertMock.mockResolvedValue({ items: [], total: 10 });
    renderTab();

    await user.type(
      await screen.findByLabelText("Monthly revenue goal ($)"),
      "50000",
    );

    // Give June its own, much larger goal.
    await user.click(screen.getByRole("button", { name: /Jun 2026/ }));
    await user.click(
      screen.getByRole("button", { name: /Give June its own plan/i }),
    );
    const juneGoal = screen.getByLabelText("Monthly revenue goal ($)", {
      selector: "#sales-target-month-6-revenueGoal",
    });
    await user.clear(juneGoal);
    await user.type(juneGoal, "130000");

    await user.click(screen.getByRole("button", { name: /save sales targets/i }));

    await waitFor(() => expect(bulkUpsertMock).toHaveBeenCalledTimes(1));
    const [workspaceId, payload] = bulkUpsertMock.mock.calls[0];
    expect(workspaceId).toBe("ws-1");

    // March through December: history (January, February) is left untouched.
    expect(payload).toHaveLength(10);
    expect(payload[0].period_month).toBe("2026-03-01");
    expect(payload[0].revenue_goal).toBe(50000);
    const june = payload.find(
      (entry: { period_month: string }) => entry.period_month === "2026-06-01",
    );
    expect(june.revenue_goal).toBe(130000);
  });

  it("marks overridden months in the year grid", async () => {
    listMock.mockResolvedValue({
      items: [
        ...[3, 4, 5].map((month) => target(month)),
        target(6, { revenue_goal: 130000 }),
      ],
      total: 4,
    });

    renderTab();

    const juneTile = await screen.findByRole("button", { name: /Jun 2026/ });
    expect(within(juneTile).getByText("Custom")).toBeInTheDocument();
    expect(within(juneTile).getByText("$130,000")).toBeInTheDocument();

    const mayTile = screen.getByRole("button", { name: /May 2026/ });
    expect(within(mayTile).queryByText("Custom")).not.toBeInTheDocument();
    expect(screen.getByText("1 of 12 months override the default.")).toBeInTheDocument();
  });
});
