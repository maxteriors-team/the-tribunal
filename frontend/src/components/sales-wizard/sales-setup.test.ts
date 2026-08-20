import { describe, expect, it } from "vitest";

import type { CatalogItemResponse, PricingSettings } from "@/types/sales-wizard";

import { hasSellableLandscapePackage } from "./sales-setup";

const pricing = {
  tiers: [
    {
      key: "good",
      label: "GOOD",
      popular: false,
      sections: [{ title: "Fixtures", item_ids: ["starter-uplight"] }],
    },
  ],
} as PricingSettings;

function catalogItem(overrides: Partial<CatalogItemResponse> = {}): CatalogItemResponse {
  return {
    id: "0ef615a3-4fa5-43e7-bb3b-2dbfa0788001",
    workspace_id: "0ef615a3-4fa5-43e7-bb3b-2dbfa0788002",
    name: "Starter uplight",
    sku: "starter-uplight",
    kind: "service",
    unit_price: 172,
    taxable: true,
    is_active: true,
    is_attachable: false,
    attach_targets: [],
    created_at: "2026-08-19T12:00:00Z",
    updated_at: "2026-08-19T12:00:00Z",
    ...overrides,
  };
}

describe("hasSellableLandscapePackage", () => {
  it("accepts an active priced Price Book row referenced by SKU", () => {
    expect(hasSellableLandscapePackage(pricing, [catalogItem()])).toBe(true);
  });

  it.each([
    ["missing package tiers", { tiers: [] } as unknown as PricingSettings, [catalogItem()]],
    ["missing catalog rows", pricing, []],
    ["a zero-dollar row", pricing, [catalogItem({ unit_price: 0 })]],
    ["an archived row", pricing, [catalogItem({ is_active: false })]],
    ["an unresolved SKU", pricing, [catalogItem({ sku: "other-uplight" })]],
  ])("rejects %s", (_label, candidatePricing, candidateCatalog) => {
    expect(hasSellableLandscapePackage(candidatePricing, candidateCatalog)).toBe(false);
  });
});
