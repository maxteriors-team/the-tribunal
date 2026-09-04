import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UpsellScoreboard } from "@/components/upsell/upsell-scoreboard";
import type { UpsellMyStats } from "@/lib/api/upsell";

const stats: UpsellMyStats = {
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  proposals_sent: 4,
  proposals_approved: 2,
  revenue_approved: 1_200,
  close_rate: 50,
  care_plans_sold: 1,
  rank: {
    current_key: "starter",
    current_name: "Starter",
    current_reward: null,
    next_name: "Closer",
    next_reward: null,
    next_threshold: 2_000,
    amount_to_next: 800,
    progress: 0.6,
  },
};

describe("UpsellScoreboard", () => {
  it("labels the existing sales ladder as an upsell tier", () => {
    render(<UpsellScoreboard stats={stats} />);

    expect(screen.getByText("Upsell tier: Starter")).toBeVisible();
    expect(screen.getByText("$1,200.00")).toBeVisible();
  });
});
