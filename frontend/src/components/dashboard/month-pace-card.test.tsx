import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MonthPaceCard, paceStatus } from "@/components/dashboard/month-pace-card";
import type { RevenuePace } from "@/lib/api/revenue-targets";

const { getPaceMock } = vi.hoisted(() => ({ getPaceMock: vi.fn() }));

vi.mock("@/lib/api/revenue-targets", () => ({
  revenueTargetsApi: { getPace: getPaceMock },
}));

function pace(overrides: Partial<RevenuePace> = {}): RevenuePace {
  return {
    period_month: "2026-06-01",
    as_of: "2026-06-15",
    has_target: true,
    currency: "USD",
    revenue_goal: 100_000,
    revenue_sold_to_date: 50_000,
    days_elapsed: 15,
    days_in_month: 30,
    projected_month_end: 100_000,
    gap_to_goal: 50_000,
    projected_gap_to_goal: 0,
    on_pace: true,
    stages: [
      { stage: "leads", actual: 40, required: 93, required_to_date: 46.5, gap: 53 },
      { stage: "estimates", actual: 30, required: 56, required_to_date: 28, gap: 26 },
      { stage: "sold", actual: 10, required: 20, required_to_date: 10, gap: 10 },
    ],
    estimate_capacity_per_month: null,
    estimates_over_capacity: null,
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <MonthPaceCard workspaceId="ws-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

/**
 * Read one metric tile by its label. Money figures repeat between the tiles and
 * the pace-bar caption, so a bare text query is ambiguous by design.
 */
function metricValue(label: string): string {
  const tile = screen.getByText(label).previousElementSibling;
  return tile?.textContent ?? "";
}

describe("paceStatus", () => {
  it("is on track once the projection clears the goal", () => {
    expect(paceStatus(100_000, 100_000)).toBe("on-track");
    expect(paceStatus(140_000, 100_000)).toBe("on-track");
  });

  it("scores against the required pace, not against a previous month", () => {
    // 10% short is amber; anything below that is red.
    expect(paceStatus(90_000, 100_000)).toBe("at-risk");
    expect(paceStatus(89_999, 100_000)).toBe("behind");
    expect(paceStatus(1_000, 100_000)).toBe("behind");
  });

  it("reports unknown when the month cannot be projected or has no goal", () => {
    expect(paceStatus(null, 100_000)).toBe("unknown");
    expect(paceStatus(50_000, null)).toBe("unknown");
    expect(paceStatus(50_000, 0)).toBe("unknown");
  });
});

describe("MonthPaceCard", () => {
  it("prompts for a goal instead of rendering zeros when none is set", async () => {
    getPaceMock.mockResolvedValue(
      pace({
        has_target: false,
        revenue_goal: null,
        revenue_sold_to_date: 0,
        projected_month_end: 0,
        gap_to_goal: null,
        projected_gap_to_goal: null,
        on_pace: null,
        stages: [
          { stage: "leads", actual: 0, required: null, required_to_date: null, gap: null },
          { stage: "estimates", actual: 0, required: null, required_to_date: null, gap: null },
          { stage: "sold", actual: 0, required: null, required_to_date: null, gap: null },
        ],
      }),
    );

    renderCard();

    expect(
      await screen.findByText("No revenue goal set for June 2026"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /set a revenue goal/i })).toHaveAttribute(
      "href",
      "/settings?tab=sales-targets",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reports money, days remaining and the projection when on pace", async () => {
    getPaceMock.mockResolvedValue(pace());

    renderCard();

    expect(await screen.findByText("On pace to hit the goal")).toBeInTheDocument();
    expect(metricValue("Sold this month")).toBe("$50,000");
    expect(metricValue("Projected at this pace")).toBe("$100,000");
    expect(metricValue("Still to sell")).toBe("$50,000");
    expect(metricValue("Days remaining of 30")).toBe("15");
  });

  it("calls a projection within 10% of the goal at risk, not on pace", async () => {
    getPaceMock.mockResolvedValue(
      pace({ revenue_sold_to_date: 46_000, projected_month_end: 92_000 }),
    );

    renderCard();

    expect(
      await screen.findByText("Within 10% of the goal at this pace"),
    ).toBeInTheDocument();
  });

  it("calls a projection more than 10% short behind pace", async () => {
    getPaceMock.mockResolvedValue(
      pace({ revenue_sold_to_date: 20_000, projected_month_end: 40_000 }),
    );

    renderCard();

    expect(await screen.findByText("Behind the pace needed")).toBeInTheDocument();
  });

  it("lists each funnel stage as actual against required", async () => {
    getPaceMock.mockResolvedValue(pace());

    renderCard();

    const table = await screen.findByRole("table");
    const leads = screen.getByRole("row", { name: /Leads/ });
    // Actual, required by today (46.5 rounded up), whole-month requirement.
    expect(leads).toHaveTextContent("40");
    expect(leads).toHaveTextContent("47");
    expect(leads).toHaveTextContent("93");
    expect(table).toHaveTextContent("Estimates");
    expect(table).toHaveTextContent("Sold jobs");
  });

  it("warns when the goal needs more estimates than stated capacity", async () => {
    getPaceMock.mockResolvedValue(
      pace({ estimate_capacity_per_month: 40, estimates_over_capacity: 16 }),
    );

    renderCard();

    expect(
      await screen.findByText(
        /needs 16 more estimates than your stated capacity of 40 a month/i,
      ),
    ).toBeInTheDocument();
  });
});
