import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";

const { capabilitiesMock, getPaceMock, useDashboardMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  capabilitiesMock: vi.fn(),
  getPaceMock: vi.fn(),
  useDashboardMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

vi.mock("@/hooks/useDashboard", () => ({
  useDashboard: () => useDashboardMock(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("@/lib/api/revenue-targets", () => ({
  revenueTargetsApi: { getPace: getPaceMock },
}));

// Keep this suite on dashboard composition. MonthPaceCard stays real because its
// query is the behavior under test; the other cards have their own coverage.
vi.mock("@/components/dashboard/appointment-performance-card", () => ({
  AppointmentPerformanceCard: () => null,
}));
vi.mock("@/components/dashboard/dashboard-stats", () => ({ DashboardStatsGrid: () => null }));
vi.mock("@/components/dashboard/knowledge-base-card", () => ({ KnowledgeBaseCard: () => null }));
vi.mock("@/components/dashboard/lead-source-roi-card", () => ({ LeadSourceRoiCard: () => null }));
vi.mock("@/components/dashboard/performance-metrics", () => ({
  ActiveCampaignsCard: () => null,
  AgentsCard: () => null,
  AppointmentStatsCard: () => null,
}));
vi.mock("@/components/dashboard/recent-activity-feed", () => ({ RecentActivityFeed: () => null }));
vi.mock("@/components/dashboard/revenue-roi-card", () => ({ RevenueRoiCard: () => null }));
vi.mock("@/components/dashboard/reviews-card", () => ({ ReviewsCard: () => null }));
vi.mock("@/components/dashboard/roleplay-card", () => ({ RoleplayCard: () => null }));
vi.mock("@/components/dashboard/speed-to-lead-card", () => ({ SpeedToLeadCard: () => null }));
vi.mock("@/components/dashboard/today-overview", () => ({
  NudgesCard: () => null,
  QuickActionsCard: () => null,
  TodayOverviewCard: () => null,
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  useDashboardMock.mockReturnValue({
    data: undefined,
    isPending: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
  });
  getPaceMock.mockImplementation(() => new Promise(() => {}));
  signedInAs("admin");
});

describe("DashboardPage role coverage", () => {
  it("omits Month Pace for managers without requesting the reports endpoint", () => {
    signedInAs("manager");

    renderDashboard();

    expect(screen.queryByText("Month Pace")).not.toBeInTheDocument();
    expect(getPaceMock).not.toHaveBeenCalled();
  });

  it("shows Month Pace and requests its endpoint for reports viewers", async () => {
    renderDashboard();

    expect(screen.getByText("Month Pace")).toBeInTheDocument();
    await waitFor(() => expect(getPaceMock).toHaveBeenCalledWith("ws-1"));
  });
});
