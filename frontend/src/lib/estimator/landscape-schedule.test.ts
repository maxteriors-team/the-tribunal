import { describe, expect, it } from "vitest";

import type { CatalogItemResponse } from "@/types/sales-wizard";

import { buildLandscapeProcurement } from "./landscape-procurement";
import { buildLandscapeSchedule, updateFixtureScheduleSelection } from "./landscape-schedule";
import type { DesignerShot, Product } from "./types";

function fixtureProduct(
  type: "uplight" | "downlight" | "underwater",
  catalogItemId?: string,
  catalogSku?: string,
): Product {
  return {
    id: `fixture-${type}`,
    name: type,
    category: "landscape",
    kind: "each",
    price: 0,
    style: type,
    colors: ["#ffffff"],
    spacingIn: 0,
    sizeFt: 10,
    sku: catalogSku ?? null,
    catalogItemId,
    catalogSku,
    productName: catalogItemId ? `${type} assembly` : null,
    target: { field: "landscape", fixtureType: type },
  };
}

function catalogItem(
  id: string,
  sku: string,
  components: CatalogItemResponse["components"] = [],
): CatalogItemResponse {
  return {
    id,
    workspace_id: "workspace-1",
    name: `${sku} assembly`,
    sku,
    kind: "product",
    unit_price: 100,
    taxable: true,
    is_active: true,
    is_attachable: false,
    components,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const products = [
  fixtureProduct("uplight", "catalog-uplight", "UP-ASSEMBLY"),
  fixtureProduct("downlight", "catalog-downlight", "DOWN-ASSEMBLY"),
  fixtureProduct("underwater"),
];
const catalog = [
  catalogItem("catalog-uplight", "UP-ASSEMBLY"),
  catalogItem("catalog-downlight", "DOWN-ASSEMBLY", [
    { sku: "DOWN-COMPONENT", qty: 1, description: "Downlight body" },
  ]),
  catalogItem("catalog-down-component", "DOWN-COMPONENT"),
];
const shots: DesignerShot[] = [
  {
    id: "sheet-front",
    photo: { dataUrl: "data:image/png;base64,AAAA", width: 100, height: 80 },
    design: {
      calibration: null,
      runs: [],
      items: [
        {
          id: "fixture-front",
          productId: "fixture-uplight",
          at: { x: 1, y: 2 },
          sizePx: 30,
        },
      ],
    },
    dusk: 0.4,
    sheet: { label: "Front", drawingNumber: "L-1" },
  },
  {
    id: "sheet-back",
    photo: { dataUrl: "data:image/png;base64,BBBB", width: 100, height: 80 },
    design: {
      calibration: null,
      runs: [],
      items: [
        {
          id: "fixture-back",
          productId: "fixture-uplight",
          at: { x: 3, y: 4 },
          sizePx: 30,
          catalogItemId: "manual-fixture",
          catalogSku: "MANUAL-FIXTURE",
          lampCatalogItemId: "manual-lamp",
          accessoryCatalogItemIds: ["manual-shield"],
        },
      ],
    },
    dusk: 0.4,
    sheet: { label: "Back", drawingNumber: "L-2" },
  },
];

describe("landscape fixture schedule type updates", () => {
  it("persists the new type on the matching sheet, clears overrides, and recounts package BOM", () => {
    const updated = updateFixtureScheduleSelection(shots, "fixture-back", {
      productId: "fixture-downlight",
      catalogItemId: undefined,
      catalogSku: undefined,
      lampCatalogItemId: undefined,
      accessoryCatalogItemIds: [],
    });

    expect(updated[0].design.items[0].productId).toBe("fixture-uplight");
    expect(updated[1].design.items[0]).toMatchObject({
      productId: "fixture-downlight",
      catalogItemId: undefined,
      catalogSku: undefined,
      lampCatalogItemId: undefined,
      accessoryCatalogItemIds: [],
    });

    const schedule = buildLandscapeSchedule(updated, products, catalog);
    expect(
      schedule.map(({ number, sheetLabel, fixtureType, fixtureSku }) => ({
        number,
        sheetLabel,
        fixtureType,
        fixtureSku,
      })),
    ).toEqual([
      { number: 1, sheetLabel: "L-1", fixtureType: "uplight", fixtureSku: "UP-ASSEMBLY" },
      {
        number: 2,
        sheetLabel: "L-2",
        fixtureType: "downlight",
        fixtureSku: "DOWN-ASSEMBLY",
      },
    ]);

    const procurement = buildLandscapeProcurement(schedule, catalog);
    expect(procurement).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          category: "fixture",
          catalogItemId: "catalog-downlight",
          sku: "DOWN-ASSEMBLY",
        }),
        expect.objectContaining({ category: "component", sku: "DOWN-COMPONENT", needed: 1 }),
      ]),
    );
  });

  it("keeps an unsupported package type unresolved instead of substituting another fixture", () => {
    const updated = updateFixtureScheduleSelection(shots, "fixture-back", {
      productId: "fixture-underwater",
      catalogItemId: undefined,
      catalogSku: undefined,
      lampCatalogItemId: undefined,
      accessoryCatalogItemIds: [],
    });
    const schedule = buildLandscapeSchedule(updated, products, catalog);
    const underwater = schedule.find((row) => row.itemId === "fixture-back");

    expect(underwater).toMatchObject({
      productId: "fixture-underwater",
      fixtureType: "underwater",
      fixtureCatalogItemId: null,
      fixtureSku: null,
    });
    expect(underwater?.unresolved).toContain("Fixture has no price-book mapping");
    expect(buildLandscapeProcurement(schedule, catalog)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          category: "fixture",
          name: "underwater",
          sku: null,
          status: "unresolved",
        }),
      ]),
    );
  });
});
