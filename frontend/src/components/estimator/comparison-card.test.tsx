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
