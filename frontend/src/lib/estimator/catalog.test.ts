import { describe, expect, it } from "vitest";

import type { LinearFeetEstimateResult } from "@/types/estimate";

import { BULB_SIZE_OPTIONS, buildCatalog, bulbSizeNameFor } from "./catalog";

// A minimal but complete rep estimate. Overrides let each test flip one knob
// (permanent enabled, catalog contents) without restating the whole shape.
function estimate(
  overrides: Partial<LinearFeetEstimateResult> = {},
): LinearFeetEstimateResult {
  return {
    feet: 0,
    permanent: { enabled: false, total: 0, per_ft: 32 },
    christmas: { enabled: true, total: 0, per_ft: 6, items: [] },
    difference: 0,
    years: 5,
    temporary_multi_year: 0,
    permanent_one_time: 0,
    multi_year_savings: 0,
    permanent_perks: [],
    christmas_perks: [],
    christmas_catalog: [],
    ...overrides,
  };
}

describe("bulbSizeNameFor", () => {
  it("round-trips every named bulb size", () => {
    for (const [name, scale] of Object.entries(BULB_SIZE_OPTIONS)) {
      expect(bulbSizeNameFor(scale)).toBe(name);
    }
  });

  it("snaps an arbitrary scale to the nearest named size", () => {
    expect(bulbSizeNameFor(1.05)).toBe("Standard");
    expect(bulbSizeNameFor(1.45)).toBe("Large");
    expect(bulbSizeNameFor(999)).toBe("Jumbo");
  });
});

describe("buildCatalog bulb size", () => {
  it("gives every built linear product a numeric bulb scale", () => {
    const catalog = buildCatalog(
      estimate({
        christmas_catalog: [
          {
            key: "mini_lights",
            label: "Mini Lights",
            unit: "per_ft",
            options: [{ key: "standard", name: "Mini lights", price: 4 }],
          },
        ],
      }),
    );
    const linear = catalog.filter((p) => p.kind === "linear");
    expect(linear.length).toBeGreaterThan(0);
    for (const p of linear) {
      expect(p.bulbScale).toBe(1);
    }
  });

  it("carries a bulb scale on the built-in roofline products", () => {
    const warm = buildCatalog(null).find((p) => p.id === "roofline-c9-warm");
    expect(warm?.bulbScale).toBe(1);
  });
});

describe("buildCatalog permanent roofline", () => {
  it("omits the permanent roofline when permanent lighting is disabled", () => {
    const catalog = buildCatalog(
      estimate({ permanent: { enabled: false, total: 0, per_ft: 32 } }),
    );
    expect(catalog.find((p) => p.id === "roofline-permanent")).toBeUndefined();
  });

  it("adds a permanent roofline priced per foot when enabled", () => {
    const catalog = buildCatalog(
      estimate({ permanent: { enabled: true, total: 0, per_ft: 40 } }),
    );
    const perm = catalog.find((p) => p.id === "roofline-permanent");
    expect(perm).toBeDefined();
    expect(perm?.kind).toBe("linear");
    expect(perm?.style).toBe("permanent");
    expect(perm?.category).toBe("permanent");
    expect(perm?.price).toBe(40);
    expect(perm?.bulbScale).toBe(1);
    // Shares the measured roofline feet — it's another visual for the one run.
    expect(perm?.target).toEqual({ field: "roofline" });
  });

  it("never adds the permanent roofline for a null estimate", () => {
    expect(
      buildCatalog(null).find((p) => p.id === "roofline-permanent"),
    ).toBeUndefined();
  });
});
