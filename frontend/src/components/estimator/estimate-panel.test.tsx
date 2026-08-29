import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("sells the three coverage levels as priced cards, cheapest first", async () => {
    const onSelectCoverage = vi.fn();
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
        coverage="whole"
        onSelectCoverage={onSelectCoverage}
        coverageFeet={{ whole: 100, "front-sides": 75, front: 40 }}
        coveragePrices={[4000, 7500, 10000]}
      />,
    );

    const coverage = screen.getByRole("group", { name: "Permanent lighting coverage" });
    const cards = within(coverage).getAllByRole("button");
    // A ladder has to climb, so the cheapest layer is the first card.
    expect(cards.map((card) => card.textContent)).toEqual([
      expect.stringContaining("Front only"),
      expect.stringContaining("Front and sides"),
      expect.stringContaining("Whole home"),
    ]);

    // Each card carries the price of its own layer, not the selected one's.
    expect(within(cards[0]).getByText("$4,000.00")).toBeInTheDocument();
    expect(within(cards[1]).getByText("$7,500.00")).toBeInTheDocument();
    expect(within(cards[2]).getByText("$10,000.00")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Most Popular")).toBeInTheDocument();

    expect(cards[2]).toHaveAttribute("aria-pressed", "true");
    expect(cards[0]).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(cards[0]);

    expect(onSelectCoverage).toHaveBeenCalledWith("front");
  });

  it("shows no price on a coverage card that has not priced yet", () => {
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
        coverage="front"
        onSelectCoverage={vi.fn()}
        coverageFeet={{ whole: 100, "front-sides": 75, front: 40 }}
        coveragePrices={[4000, null, null]}
      />,
    );

    // A stale or borrowed number here would misquote a job, so a card with no
    // price of its own shows none.
    const cards = within(
      screen.getByRole("group", { name: "Permanent lighting coverage" }),
    ).getAllByRole("button");
    expect(within(cards[0]).getByText("$4,000.00")).toBeInTheDocument();
    expect(within(cards[1]).queryByText(/\$/)).not.toBeInTheDocument();
    expect(within(cards[2]).queryByText(/\$/)).not.toBeInTheDocument();
  });

  it("hides coverage when the design has no permanent side to scope", () => {
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
        sides={{ permanent: false, seasonal: true }}
      />,
    );

    expect(screen.queryByRole("group", { name: "Coverage" })).not.toBeInTheDocument();
  });
});
