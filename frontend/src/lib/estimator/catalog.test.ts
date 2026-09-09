import { describe, expect, it } from "vitest";

import type { LinearFeetEstimateResult } from "@/types/estimate";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import {
  BULB_SIZE_OPTIONS,
  buildBistroCatalog,
  buildCatalog,
  buildSavedBistroFallbacks,
  bulbSizeNameFor,
} from "./catalog";

// A minimal but complete rep estimate. Overrides let each test flip one knob
// (permanent enabled, catalog contents) without restating the whole shape.
function estimate(overrides: Partial<LinearFeetEstimateResult> = {}): LinearFeetEstimateResult {
  return {
    feet: 0,
    proposal_side: "comparison",
    discount_amount: 0,
    permanent: {
      enabled: false,
      total: 0,
      subtotal: 0,
      per_ft: 0,
      package_feet: 0,
      package_cogs: 0,
      markup: 3.5,
      roofline_cost: 0,
      custom_total: 0,
    },
    christmas: {
      enabled: true,
      total: 0,
      subtotal: 0,
      per_ft: 6,
      roofline_cost: 0,
      custom_total: 0,
      items: [],
    },
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
      estimate({
        permanent: {
          enabled: false,
          total: 0,
          subtotal: 0,
          per_ft: 0,
          package_feet: 0,
          package_cogs: 0,
          markup: 3.5,
          roofline_cost: 0,
          custom_total: 0,
        },
      }),
    );
    expect(catalog.find((p) => p.id === "roofline-permanent")).toBeUndefined();
  });

  it("adds a permanent roofline using a package-derived display hint", () => {
    const catalog = buildCatalog(
      estimate({
        permanent: {
          enabled: true,
          total: 4371.5,
          subtotal: 4371.5,
          per_ft: 0,
          package_feet: 100,
          package_cogs: 1249,
          markup: 3.5,
          roofline_cost: 4371.5,
          custom_total: 0,
        },
      }),
    );
    const perm = catalog.find((p) => p.id === "roofline-permanent");
    expect(perm).toBeDefined();
    expect(perm?.kind).toBe("linear");
    expect(perm?.style).toBe("permanent");
    expect(perm?.category).toBe("permanent");
    expect(perm?.price).toBe(43.715);
    expect(perm?.bulbScale).toBe(1);
    // Shares the measured roofline feet — it's another visual for the one run.
    expect(perm?.target).toEqual({ field: "roofline" });
  });

  it("never adds the permanent roofline for a null estimate", () => {
    expect(buildCatalog(null).find((p) => p.id === "roofline-permanent")).toBeUndefined();
  });
});

function bistroItem(
  name: string,
  overrides: Partial<CatalogItemResponse> = {},
): CatalogItemResponse {
  return {
    id: `id-${name.toLowerCase().replaceAll(" ", "-")}`,
    workspace_id: "ws",
    name,
    description: null,
    sku: "BISTRO-CLASSIC",
    kind: "product",
    unit_price: 14,
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

describe("buildBistroCatalog landscape variants", () => {
  it("offers temporary and permanent runs while preserving the legacy product id", () => {
    const products = buildBistroCatalog([bistroItem("Classic Bistro Lights")], {
      installationVariants: true,
    });

    expect(products.find((product) => product.id === "bistro-BISTRO-CLASSIC")?.paletteHidden).toBe(
      true,
    );
    expect(
      products
        .filter((product) => !product.paletteHidden)
        .map((product) => [product.name, product.target]),
    ).toEqual([
      ["Temporary Classic Bistro Lights", { field: "bistro", installation: "temporary" }],
      ["Permanent Classic Bistro Lights", { field: "bistro", installation: "permanent" }],
    ]);
  });

  it("does not mistake unrelated string products for Bistro lighting", () => {
    expect(buildBistroCatalog([bistroItem("Commercial String Trimmer")])).toEqual([]);
    expect(
      buildBistroCatalog([bistroItem("Patio Cable Kit", { attributes: { bistro_product: true } })]),
    ).toHaveLength(1);
  });

  it("keeps both layout tools available without configured price-book products", () => {
    const products = buildBistroCatalog([], { installationVariants: true });

    expect(products.map((product) => product.name)).toEqual([
      "Temporary Bistro Lights",
      "Permanent Bistro Lights",
    ]);
    expect(products.every((product) => product.sku === null && product.price === 0)).toBe(true);
  });

  it("uses explicit installation metadata without duplicating that catalog item", () => {
    const products = buildBistroCatalog(
      [
        bistroItem("Seasonal Bistro Rental", {
          attributes: { bistro_installation_type: "temporary" },
        }),
      ],
      { installationVariants: true },
    );
    const visible = products.filter((product) => !product.paletteHidden);

    expect(visible.filter((product) => product.sku).map((product) => product.target)).toEqual([
      { field: "bistro", installation: "temporary" },
    ]);
    expect(visible.some((product) => product.id === "bistro-permanent-layout")).toBe(true);
  });

  it("keeps archived SKU runs resolvable without putting them back in the palette", () => {
    const [fallback] = buildSavedBistroFallbacks(
      ["bistro-permanent-ARCHIVED-SKU"],
      buildBistroCatalog([], { installationVariants: true }),
    );

    expect(fallback).toMatchObject({
      id: "bistro-permanent-ARCHIVED-SKU",
      name: "Saved Permanent Bistro Lights",
      paletteHidden: true,
      target: { field: "bistro", installation: "permanent" },
    });
  });

  it("does not duplicate a saved bistro product that still resolves", () => {
    const configured = buildBistroCatalog([bistroItem("Classic Bistro Lights")], {
      installationVariants: true,
    });

    expect(buildSavedBistroFallbacks(["bistro-permanent-BISTRO-CLASSIC"], configured)).toEqual([]);
  });
});

describe("buildCatalog measured tree wraps", () => {
  const CATALOG = [
    {
      key: "trees",
      label: "Trees",
      unit: "each" as const,
      options: [{ key: "medium", name: "Medium tree (8–15 ft)", price: 260 }],
    },
    {
      key: "mini_lights",
      label: "Mini Lights",
      unit: "per_ft" as const,
      options: [{ key: "standard", name: "Mini lights", price: 5 }],
    },
  ];

  const pkg = (key: string, itemKeys: string[]) => ({
    key,
    label: key,
    name: key,
    marker: null,
    experience: null,
    points: [],
    value_tag: null,
    popular: false,
    includes_roofline: false,
    item_keys: itemKeys,
    pricing: {
      roofline_feet: 0,
      roofline_cost: 0,
      items: [],
      takedown_cost: 0,
      storage_cost: 0,
      minimum: 0,
      raw_total: 0,
      total: 0,
      min_applied: false,
      lines: [],
    },
  });

  const treeFrom = (over: Partial<LinearFeetEstimateResult> = {}) =>
    buildCatalog(estimate({ christmas_catalog: CATALOG, ...over })).find(
      (p) => p.id === "cat-trees-medium",
    );

  it("points a tree at the per-foot wrap rate so measuring can price it", () => {
    expect(treeFrom()?.wrapTarget).toEqual({ category: "mini_lights", option: "standard" });
  });

  it("does not offer wrap pricing when no per-foot rate is configured", () => {
    // Measuring must never bill against a rate the operator never set.
    const trees = buildCatalog(
      estimate({ christmas_catalog: [CATALOG[0]] }),
    ).find((p) => p.id === "cat-trees-medium");

    expect(trees?.wrapTarget).toBeUndefined();
  });

  it("keeps wrap pricing when every tree package also covers the wrap rate", () => {
    const trees = treeFrom({
      christmas_packages: [
        pkg("essential", ["trees", "bushes", "mini_lights"]),
        pkg("premier", ["trees", "bushes", "mini_lights", "wreaths"]),
      ],
    });

    expect(trees?.wrapTarget).toEqual({ category: "mini_lights", option: "standard" });
  });

  it("refuses wrap pricing when a package sells trees but not the wrap rate", () => {
    // That package prices only the categories it lists, so a measured wrap would
    // be dropped from its total and the tree would silently cost nothing. The
    // flat per-tree rate is less precise but keeps the tree on the quote.
    const trees = treeFrom({
      christmas_packages: [
        pkg("essential", ["trees", "bushes"]),
        pkg("premier", ["trees", "bushes", "mini_lights"]),
      ],
    });

    expect(trees?.wrapTarget).toBeUndefined();
  });

  it("ignores packages that sell no wraps at all", () => {
    // A wreath-only tier cannot drop a tree it never covered.
    const trees = treeFrom({
      christmas_packages: [
        pkg("wreaths-only", ["wreaths"]),
        pkg("premier", ["trees", "mini_lights"]),
      ],
    });

    expect(trees?.wrapTarget).toEqual({ category: "mini_lights", option: "standard" });
  });

  it("never offers wrap pricing on a wreath", () => {
    const wreathCatalog = [
      {
        key: "wreaths",
        label: "Wreaths",
        unit: "each" as const,
        options: [{ key: "standard", name: "Wreath (36 in)", price: 85 }],
      },
      CATALOG[1],
    ];
    const wreath = buildCatalog(estimate({ christmas_catalog: wreathCatalog })).find(
      (p) => p.id === "cat-wreaths-standard",
    );

    expect(wreath?.wrapTarget).toBeUndefined();
  });
});
