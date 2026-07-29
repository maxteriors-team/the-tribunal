import { describe, expect, it } from "vitest";

import type { CatalogItemResponse, PricingSettings } from "@/types/sales-wizard";

import {
  FIXTURE_TYPES,
  buildFixturePalette,
  classifyFixture,
  hasLandscapeFixtures,
  resolveTierFixtures,
} from "./fixtures";

function item(
  sku: string,
  name: string,
  overrides: Partial<CatalogItemResponse> = {},
): CatalogItemResponse {
  return {
    id: `id-${sku}`,
    workspace_id: "ws",
    name,
    description: null,
    sku,
    kind: "product",
    unit_price: 400,
    taxable: true,
    is_active: true,
    service_category: null,
    is_attachable: false,
    attach_targets: [],
    attributes: null,
    components: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Mirrors the seeded shape: tiers list the SKUs each package includes.
function pricing(): PricingSettings {
  return {
    tier_order: ["best", "essential"],
    tiers: [
      {
        key: "best",
        label: "Best — The Premier",
        tab: "Best",
        sections: [
          { title: "Smart Transformer", item_ids: ["best-luxor"] },
          {
            title: "Fixtures",
            item_ids: [
              "best-zdc-up",
              "best-zdc-down",
              "best-zdc-path",
              "best-cora-in-grade",
            ],
          },
        ],
      },
      {
        key: "essential",
        label: "Good — The Starter",
        tab: "Good",
        sections: [
          { title: "Transformer", item_ids: ["ess-ex"] },
          { title: "Fixtures", item_ids: ["ess-accent", "ess-path"] },
        ],
      },
    ],
  } as unknown as PricingSettings;
}

const CATALOG = [
  item("best-luxor", "Luxor Smart 300W Transformer", {
    attributes: { transformer: true },
  }),
  item("best-zdc-up", "ZDC Color Uplight", { unit_price: 785 }),
  item("best-zdc-down", "ZDC Down Light", { unit_price: 963 }),
  item("best-zdc-path", "ZDC Modern Path Light", { unit_price: 511 }),
  item("best-cora-in-grade", "In-Grade Uplight", { unit_price: 447 }),
  item("ess-ex", "EX 150W Transformer", { attributes: { transformer: true } }),
  item("ess-accent", "EVO Accent Uplight", { unit_price: 172 }),
  item("ess-path", "Pathway Light", { unit_price: 376 }),
];

describe("classifyFixture", () => {
  it("reads the four fixture types from the operator's own product names", () => {
    expect(classifyFixture({ name: "ZDC Color Uplight" })).toBe("uplight");
    expect(classifyFixture({ name: "EVO Accent Uplight" })).toBe("uplight");
    expect(classifyFixture({ name: "ZD Modern Path Light" })).toBe("pathlight");
    expect(classifyFixture({ name: "Pathway Light" })).toBe("pathlight");
    expect(classifyFixture({ name: "ZDC Down Light" })).toBe("downlight");
    expect(classifyFixture({ name: "Hardscape Wash" })).toBe("downlight");
  });

  it("keeps in-ground fixtures out of the generic uplight bucket", () => {
    // Both aim upward, but a well/in-grade light is a different SKU and a
    // different install — conflating them would quote the wrong hardware.
    expect(classifyFixture({ name: "In-Grade Uplight" })).toBe("ingrade");
    expect(classifyFixture({ name: "Well Light" })).toBe("ingrade");
  });

  it("lets an explicit attribute override an unhelpful product name", () => {
    expect(
      classifyFixture({ name: "Model 7714", attributes: { fixture_type: "pathlight" } }),
    ).toBe("pathlight");
  });

  it("returns null for something that isn't a landscape fixture", () => {
    expect(classifyFixture({ name: "Low-voltage wire" })).toBeNull();
  });
});

describe("resolveTierFixtures", () => {
  it("resolves each type to the product that package actually sells", () => {
    const best = resolveTierFixtures(pricing(), CATALOG, "best");
    expect(best.uplight.itemId).toBe("best-zdc-up");
    expect(best.downlight.itemId).toBe("best-zdc-down");
    expect(best.pathlight.itemId).toBe("best-zdc-path");
    expect(best.ingrade.itemId).toBe("best-cora-in-grade");
  });

  it("re-resolves the same drawing when the package changes", () => {
    const good = resolveTierFixtures(pricing(), CATALOG, "essential");
    expect(good.uplight.itemId).toBe("ess-accent");
    expect(good.pathlight.itemId).toBe("ess-path");
    // The Good package sells no downlight or in-grade — reported as unsold
    // rather than quietly substituting the Best package's hardware.
    expect(good.downlight.itemId).toBeNull();
    expect(good.ingrade.itemId).toBeNull();
  });

  it("never resolves a type to a transformer or other non-fixture", () => {
    const best = resolveTierFixtures(pricing(), CATALOG, "best");
    const ids = FIXTURE_TYPES.map((spec) => best[spec.type].itemId);
    expect(ids).not.toContain("best-luxor");
    expect(ids).not.toContain("ess-ex");
  });

  it("skips inactive products so a retired SKU is never quoted", () => {
    const retired = CATALOG.map((c) =>
      c.sku === "best-zdc-up" ? { ...c, is_active: false } : c,
    );
    expect(resolveTierFixtures(pricing(), retired, "best").uplight.itemId).toBeNull();
  });

  it("reports no landscape fixtures for a workspace with an empty price book", () => {
    expect(hasLandscapeFixtures(resolveTierFixtures(pricing(), [], "best"))).toBe(
      false,
    );
  });
});

describe("buildFixturePalette", () => {
  it("offers four type entries carrying the resolved SKU and product name", () => {
    const palette = buildFixturePalette(
      resolveTierFixtures(pricing(), CATALOG, "best"),
    );
    expect(palette).toHaveLength(4);
    const uplight = palette.find((p) => p.id === "fixture-uplight");
    expect(uplight?.name).toBe("Uplight");
    expect(uplight?.productName).toBe("ZDC Color Uplight");
    expect(uplight?.sku).toBe("best-zdc-up");
    expect(uplight?.price).toBe(785);
    expect(uplight?.target).toEqual({ field: "landscape", fixtureType: "uplight" });
  });

  it("still offers a type the package can't fill, with no SKU behind it", () => {
    const palette = buildFixturePalette(
      resolveTierFixtures(pricing(), CATALOG, "essential"),
    );
    const downlight = palette.find((p) => p.id === "fixture-downlight");
    expect(downlight?.sku).toBeNull();
    expect(downlight?.productName).toBeNull();
  });
});
