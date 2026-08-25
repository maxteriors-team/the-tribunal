import { describe, expect, it } from "vitest";

import type { CatalogItemResponse, PricingSettings } from "@/types/sales-wizard";

import {
  aggregateBistroRuns,
  aggregateWireFeet,
  buildLandscapeProposalPayload,
  buildLandscapeProposalQuantities,
  hasUnpriceableBistroRuns,
} from "./landscape-proposal";

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
    unit_price: 100,
    taxable: true,
    is_active: true,
    service_category: "landscape",
    is_attachable: false,
    attach_targets: [],
    attributes: null,
    components: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const PRICING = {
  tier_order: ["best", "good"],
  tiers: [
    {
      ["key"]: "best",
      label: "Best",
      tab: "Best",
      sections: [
        { title: "Fixtures", item_ids: ["best-up", "shared-path"] },
        { title: "Specialty Fixtures", item_ids: ["59306832", "59407330"] },
        { title: "Wire", item_ids: ["best-wire-12", "best-wire-10"] },
      ],
    },
    {
      ["key"]: "good",
      label: "Good",
      tab: "Good",
      sections: [
        { title: "Fixtures", item_ids: ["good-up", "shared-path"] },
        { title: "Wire", item_ids: ["good-wire-12"] },
      ],
    },
  ],
} as unknown as PricingSettings;

const CATALOG = [
  item("best-up", "ZDC Uplight"),
  item("good-up", "EVO Uplight"),
  item("shared-path", "Path Light"),
  item("59306832", "FX PO ZD Round Core-Drilled Wall Light — Black", {
    unit_price: 775,
    attributes: { fixture_type: "walllight", unit_cost: 166.76 },
  }),
  item("59407330", "FX LL ZDC Underwater Light — Brass", {
    unit_price: 1295,
    attributes: { fixture_type: "underwater", unit_cost: 374.37 },
  }),
  item("best-wire-12", "12/2 Landscape Wire", { unit_price: 1.25 }),
  item("best-wire-10", "10/2 Landscape Wire", { unit_price: 1.85 }),
  item("good-wire-12", "12/2 Standard Cable", { unit_price: 0.95 }),
];

const WIRES = [
  { gauge: 12 as const, lengthFeet: 42.4 },
  { gauge: 12 as const, lengthFeet: 20.1 },
  { gauge: 10 as const, lengthFeet: 85 },
  { gauge: 10 as const, lengthFeet: null },
];

describe("landscape proposal pricing payload", () => {
  it("aggregates calibrated wire routes by the offered 12/2 and 10/2 sizes", () => {
    expect([...aggregateWireFeet(WIRES)]).toEqual([
      [12, 62.5],
      [10, 85],
    ]);
  });

  it("aggregates temporary and permanent Bistro footage across sheets", () => {
    const runs = [
      { installation: "temporary" as const, lengthFeet: 32.5 },
      { installation: "permanent" as const, lengthFeet: 20 },
      { installation: "temporary" as const, lengthFeet: 7.5 },
    ];

    expect(aggregateBistroRuns(runs)).toEqual([
      { installation: "temporary", feet: 40 },
      { installation: "permanent", feet: 20 },
    ]);

    const payload = buildLandscapeProposalPayload({
      pricing: PRICING,
      catalog: CATALOG,
      fixtureCounts: {},
      wireRuns: [],
      bistroRuns: runs,
      selectedTierKey: "best",
      selectedCarePlanKey: null,
    });
    const bistro = payload.bistro as typeof payload.bistro & {
      runs: Array<{ installation: string; feet: number }>;
    };
    expect(payload.categories).toEqual(["landscape", "bistro"]);
    expect(bistro.runs).toEqual([
      { installation: "temporary", feet: 40 },
      { installation: "permanent", feet: 20 },
    ]);
    expect(bistro.feet).toBe(60);
  });

  it("excludes uncalibrated Bistro footage and exposes the quote guard", () => {
    const runs = [
      { installation: "temporary" as const, lengthFeet: 25 },
      { installation: "permanent" as const, lengthFeet: null },
    ];

    expect(hasUnpriceableBistroRuns(runs)).toBe(true);
    expect(aggregateBistroRuns(runs)).toEqual([{ installation: "temporary", feet: 25 }]);
  });

  it("prices every package without multiplying SKUs reused between tiers", () => {
    const quantities = buildLandscapeProposalQuantities(
      PRICING,
      CATALOG,
      { uplight: 4, pathlight: 3 },
      WIRES,
    );

    expect(quantities).toEqual(
      expect.arrayContaining([
        { item_id: "best-up", quantity: 4 },
        { item_id: "good-up", quantity: 4 },
        { item_id: "shared-path", quantity: 3 },
        { item_id: "best-wire-12", quantity: 62.5 },
        { item_id: "good-wire-12", quantity: 62.5 },
        { item_id: "best-wire-10", quantity: 85 },
      ]),
    );
    expect((quantities ?? []).filter((line) => line.item_id === "shared-path")).toHaveLength(1);
  });

  it("quotes the approved specialty products without substituting another fixture type", () => {
    const quantities = buildLandscapeProposalQuantities(
      PRICING,
      CATALOG,
      { walllight: 2, underwater: 3 },
      [],
    );

    expect(quantities).toEqual([
      { item_id: "59306832", quantity: 2 },
      { item_id: "59407330", quantity: 3 },
    ]);
    expect(CATALOG.find((catalogItem) => catalogItem.sku === "59306832")?.unit_price).toBe(775);
    expect(CATALOG.find((catalogItem) => catalogItem.sku === "59407330")?.unit_price).toBe(1295);
  });

  it("includes valid additional line items in server-priced package totals", () => {
    const payload = buildLandscapeProposalPayload({
      pricing: PRICING,
      catalog: CATALOG,
      fixtureCounts: { uplight: 2 },
      wireRuns: [],
      selectedTierKey: "good",
      selectedCarePlanKey: null,
      additionalLineItems: [
        { description: "  Core drill through masonry  ", amount: 275.5 },
        { description: "", amount: 99 },
        { description: "No-charge note", amount: 0 },
      ],
    });

    expect(payload.additional_charges).toEqual([
      {
        description: "Core drill through masonry",
        net_amount: 275.5,
        catalog_item_id: null,
        tier_key: null,
      },
    ]);
  });

  it("keeps project linkage, package, and care-plan choices in the server-owned quote payload", () => {
    const payload = buildLandscapeProposalPayload({
      pricing: PRICING,
      catalog: CATALOG,
      fixtureCounts: { uplight: 4, pathlight: 3 },
      wireRuns: WIRES,
      selectedTierKey: "good",
      selectedCarePlanKey: "essential",
      contactId: 42,
      opportunityId: "opp-1",
      serviceLocationId: "location-1",
      title: "Smith Residence",
    });

    expect(payload).toMatchObject({
      pricing_source: "price_book",
      contact_id: 42,
      opportunity_id: "opp-1",
      service_location_id: "location-1",
      title: "Smith Residence",
      categories: ["landscape"],
      selected_tier: "good",
      care_plan_tier: "essential",
      care_count_manual: 7,
      night_preview: null,
    });
  });
});
