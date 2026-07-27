import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ComparisonCard,
  type ComparisonView,
} from "@/components/estimator/comparison-card";

// A both-services-offered comparison; individual tests layer the seasonal
// package ladder on top to exercise the client-facing Good/Better/Best grid.
const BASE: ComparisonView = {
  currency: "USD",
  clientName: "The Rivera Residence",
  permanent: { enabled: true, total: 4200 },
  christmas: { enabled: true, total: 1100 },
  difference: 3100,
  years: 5,
  temporary_multi_year: 5500,
  permanent_one_time: 4200,
  multi_year_savings: 1300,
  permanent_perks: ["Installed once"],
  christmas_perks: ["Lower upfront cost"],
};

const PACKAGES: NonNullable<ComparisonView["christmasPackages"]> = [
  {
    key: "essential",
    name: "The Essential",
    marker: "●",
    total: 700,
    popular: false,
    recommended: false,
    points: ["Trees and bushes wrapped"],
    experience: "A festive first impression.",
  },
  {
    key: "middle",
    name: "The Classic",
    marker: "◆",
    total: 1100,
    popular: false,
    recommended: true,
    points: ["Full roofline outlined"],
    experience: "The complete outline.",
  },
  {
    // Popular but not the rep's recommendation, so the "Most popular" tag branch
    // renders independently of the "Recommended" highlight.
    key: "premier",
    name: "The Premier",
    marker: "★",
    total: 1400,
    popular: true,
    recommended: false,
    points: ["Everything, fully dressed"],
    experience: "The whole property, transformed.",
  },
];

describe("ComparisonCard seasonal package ladder", () => {
  it("renders the three Good/Better/Best cards with names, prices, and perks", () => {
    render(<ComparisonCard view={{ ...BASE, christmasPackages: PACKAGES }} />);

    expect(
      screen.getByRole("heading", { name: /Choose your seasonal package/i }),
    ).toBeInTheDocument();

    // Every tier surfaces to the client with its client-facing name + price.
    expect(screen.getByText("The Essential")).toBeInTheDocument();
    expect(screen.getByText("The Classic")).toBeInTheDocument();
    expect(screen.getByText("The Premier")).toBeInTheDocument();
    expect(screen.getByText("$700.00")).toBeInTheDocument();
    expect(screen.getByText("$1,400.00")).toBeInTheDocument();
    expect(screen.getByText(/Everything, fully dressed/i)).toBeInTheDocument();
  });

  it("highlights only the recommended tier with the Recommended tag", () => {
    render(<ComparisonCard view={{ ...BASE, christmasPackages: PACKAGES }} />);

    // The recommended package (The Classic) is the only card tagged Recommended…
    const tags = screen.getAllByText("Recommended");
    expect(tags).toHaveLength(1);
    const recommendedCard = tags[0].closest(".cmp-pkg");
    expect(recommendedCard).not.toBeNull();
    expect(within(recommendedCard as HTMLElement).getByText("The Classic")).toBeInTheDocument();
    expect(recommendedCard).toHaveClass("recommended");

    // …and the non-recommended popular tier reads as "Most popular" instead.
    expect(screen.getByText("Most popular")).toBeInTheDocument();
  });

  it("omits the package section for à la carte seasonal (no packages)", () => {
    render(<ComparisonCard view={BASE} />);

    expect(
      screen.queryByText(/Choose your seasonal package/i),
    ).not.toBeInTheDocument();
    // The single seasonal summary card still renders its total.
    expect(screen.getByText("Seasonal Lighting")).toBeInTheDocument();
    expect(screen.getByText("$1,100.00")).toBeInTheDocument();
  });
});

// The roofline-only cost comparison: an opt-in, feet-free block that compares
// roofline to roofline (decor excluded) so the numbers are like-for-like.
const ROOFLINE: NonNullable<ComparisonView["roofline"]> = {
  permanent_total: 3000,
  seasonal_total: 800,
  seasonal_multi_year: 4000,
  savings: 1000,
};

describe("ComparisonCard roofline cost comparison", () => {
  it("renders both roofline costs and the multi-year projection when present", () => {
    render(<ComparisonCard view={{ ...BASE, roofline: ROOFLINE }} />);

    expect(
      screen.getByRole("heading", { name: /Roofline, side by side/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Permanent roofline")).toBeInTheDocument();
    expect(screen.getByText("Seasonal roofline")).toBeInTheDocument();
    // Roofline-only costs, distinct from the headline totals above ($4,200/$1,100).
    expect(screen.getByText("$3,000.00")).toBeInTheDocument();
    expect(screen.getByText("$800.00")).toBeInTheDocument();
    // The seasonal side shows what paying every season adds up to.
    expect(
      screen.getByText(/\$4,000\.00 over 5 seasons/i),
    ).toBeInTheDocument();
  });

  it("tags the permanent roofline as the saver when it wins the horizon", () => {
    render(<ComparisonCard view={{ ...BASE, roofline: ROOFLINE }} />);

    const tag = screen.getByText(/Saves \$1,000\.00/i);
    const card = tag.closest(".cmp-card");
    expect(card).toHaveClass("recommended");
    expect(
      within(card as HTMLElement).getByText("Permanent roofline"),
    ).toBeInTheDocument();
  });

  it("omits the saver tag when seasonal is not more expensive over the horizon", () => {
    render(
      <ComparisonCard
        view={{
          ...BASE,
          roofline: { ...ROOFLINE, seasonal_multi_year: 2500, savings: -500 },
        }}
      />,
    );

    expect(screen.getByText("Permanent roofline")).toBeInTheDocument();
    expect(screen.queryByText(/^Saves /i)).not.toBeInTheDocument();
  });

  it("renders nothing when the workspace has the comparison off", () => {
    // The flag defaults off server-side, so `roofline` is null/absent and the
    // page renders exactly as it did before the feature existed.
    const { rerender } = render(<ComparisonCard view={BASE} />);
    expect(
      screen.queryByText(/Roofline, side by side/i),
    ).not.toBeInTheDocument();

    rerender(<ComparisonCard view={{ ...BASE, roofline: null }} />);
    expect(
      screen.queryByText(/Roofline, side by side/i),
    ).not.toBeInTheDocument();
  });
});
