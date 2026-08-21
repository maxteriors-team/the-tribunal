import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DashboardStatsGrid } from "@/components/dashboard/dashboard-stats";
import type { DashboardStats } from "@/lib/api/dashboard";

vi.mock("@/components/dashboard/animations", () => ({
  AnimatedNumber: ({ value }: { value: number }) => <span>{value}</span>,
  containerVariants: {},
  isTrendUp: (change: string) => change.startsWith("+"),
  itemVariants: {},
}));

const stats: DashboardStats = {
  leads_last_24_hours: 7,
  total_contacts: 42,
  active_campaigns: 3,
  calls_today: 5,
  messages_sent: 11,
  contacts_change: "+2%",
  campaigns_change: "+1",
  calls_change: "-1%",
  messages_change: "+4%",
};

describe("DashboardStatsGrid", () => {
  it("shows the workspace's lead count for the trailing 24 hours", () => {
    render(<DashboardStatsGrid stats={stats} isPending={false} />);

    const leadsCard = screen.getByText("Leads Received").closest("a");

    expect(leadsCard).toHaveAttribute("href", "/contacts");
    expect(within(leadsCard!).getByText("7")).toBeInTheDocument();
    expect(within(leadsCard!).getByText("Last 24 hours")).toBeInTheDocument();
  });
});
