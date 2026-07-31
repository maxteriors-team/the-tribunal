import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PackageGrid,
  type ComparisonPackageView,
} from "@/components/estimator/package-grid";

const PACKAGES: ComparisonPackageView[] = [
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
];

describe("PackageGrid seasonal defaults", () => {
  // The grid was lifted out of ComparisonCard so any category can use it. Its
  // no-copy rendering is what every already-shared seasonal link renders, so it
  // is asserted as an exact markup snapshot, not a loose text match.
  it("renders the exact seasonal markup when no category copy is supplied", () => {
    const { container } = render(<PackageGrid packages={PACKAGES} />);

    expect(container.innerHTML).toBe(
      '<div class="cmp-pkg-section">' +
        '<div class="cmp-pkg-head">' +
        "<h2>Choose your seasonal package</h2>" +
        "<p>Three ways to light up the season. Pick the look that fits your home.</p>" +
        "</div>" +
        '<div class="cmp-pkg-grid">' +
        '<div class="cmp-card cmp-pkg">' +
        '<h3><span class="cmp-pkg-marker">●</span>The Essential</h3>' +
        '<div class="cmp-pkg-exp">A festive first impression.</div>' +
        '<div class="cmp-price">$700.00</div>' +
        '<div class="cmp-price-note">Per season</div>' +
        '<ul class="cmp-perks"><li>Trees and bushes wrapped</li></ul>' +
        "</div>" +
        '<div class="cmp-card cmp-pkg recommended">' +
        '<span class="cmp-card-tag">Recommended</span>' +
        '<h3><span class="cmp-pkg-marker">◆</span>The Classic</h3>' +
        '<div class="cmp-pkg-exp">The complete outline.</div>' +
        '<div class="cmp-price">$1,100.00</div>' +
        '<div class="cmp-price-note">Per season</div>' +
        '<ul class="cmp-perks"><li>Full roofline outlined</li></ul>' +
        "</div>" +
        "</div>" +
        "</div>",
    );
  });

  it("renders nothing at all for a category with no packages", () => {
    const { container } = render(<PackageGrid packages={[]} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("PackageGrid for a non-seasonal category", () => {
  const ROOF: ComparisonPackageView[] = [
    { key: "good", name: "Essential", total: 12000 },
    {
      key: "better",
      name: "Preferred",
      total: 16200,
      popular: true,
      recommended: true,
      points: ["Upgraded materials"],
    },
    { key: "best", name: "Premier", total: 20800 },
  ];

  it("uses the category's own headline and price note", () => {
    render(
      <PackageGrid
        packages={ROOF}
        copy={{
          title: "Choose your roof",
          blurb: "Three ways to replace it. Most homeowners pick the middle.",
          priceNote: "One-time install",
        }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Choose your roof" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/seasonal/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("One-time install")).toHaveLength(3);
    expect(screen.getByText("$16,200.00")).toBeInTheDocument();
  });

  it("steers the middle tier with the same Recommended highlight", () => {
    render(<PackageGrid packages={ROOF} copy={{ title: "Choose your roof" }} />);

    const tags = screen.getAllByText("Recommended");
    expect(tags).toHaveLength(1);
    const card = tags[0].closest(".cmp-pkg");
    expect(card).toHaveClass("recommended");
    expect(within(card as HTMLElement).getByText("Preferred")).toBeInTheDocument();
    // "Recommended" wins over "Most popular" on the same card, as it always has.
    expect(screen.queryByText("Most popular")).not.toBeInTheDocument();
  });

  it("falls back to the seasonal wording for any copy field left blank", () => {
    render(<PackageGrid packages={ROOF} copy={{ title: "Choose your roof" }} />);

    expect(screen.getAllByText("Per season")).toHaveLength(3);
  });
});
