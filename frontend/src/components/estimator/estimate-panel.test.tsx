import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LinearFeetEstimateResult } from "@/types/estimate";

import { EstimatePanel } from "./estimate-panel";

const ESTIMATE: LinearFeetEstimateResult = {
  feet: 100,
  proposal_side: "comparison",
  discount_amount: 0,
  permanent: {
    enabled: true,
    total: 3300,
    subtotal: 3300,
    per_ft: 0,
    package_feet: 100,
    package_cogs: 1249,
    markup: 3.5,
    roofline_cost: 3300,
    custom_total: 0,
  },
  christmas: {
    enabled: true,
    total: 900,
    subtotal: 900,
    per_ft: 6,
    roofline_cost: 600,
    custom_total: 0,
    items: [],
  },
  difference: 2400,
  years: 5,
  temporary_multi_year: 4500,
  permanent_one_time: 3300,
  multi_year_savings: 1200,
  permanent_perks: [],
  christmas_perks: [],
  christmas_catalog: [],
};

describe("EstimatePanel", () => {
  it("highlights the service price instead of multi-year savings", () => {
    render(
      <EstimatePanel
        estimate={ESTIMATE}
        isFetching={false}
        feet={100}
        calibrated
        hasDesign
        selectedPackage={null}
        onSelectPackage={vi.fn()}
        customLines={[]}
        onChangeCustomLines={vi.fn()}
        sides={{ permanent: true, seasonal: true }}
      />,
    );

    expect(screen.getByText("Service price")).toBeInTheDocument();
    expect(screen.getAllByText("$3,300.00")).toHaveLength(2);
    expect(screen.queryByText(/saves|difference/i)).not.toBeInTheDocument();
    expect(screen.queryByText("$1,200.00")).not.toBeInTheDocument();
  });
});
