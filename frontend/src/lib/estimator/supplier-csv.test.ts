import { describe, expect, it } from "vitest";

import type { CatalogItemResponse } from "@/types/sales-wizard";

import { buildSupplierCsvRows, serializeSupplierCsv } from "./supplier-csv";

const catalogItem = (overrides: Partial<CatalogItemResponse> = {}): CatalogItemResponse =>
  ({
    id: "item-1",
    workspace_id: "workspace-1",
    name: "ZDC Color Uplight",
    sku: "best-zdc-up",
    kind: "product",
    unit_price: 0,
    taxable: true,
    is_active: true,
    is_attachable: false,
    attach_targets: [],
    attributes: { supplier: "SiteOne", manufacturer: "FX Luminaire" },
    components: [
      { sku: "59400232", qty: 1, description: "NP ZDC uplight" },
      { sku: "75390063", qty: 2, description: "Waterproof connector" },
    ],
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
    ...overrides,
  }) as CatalogItemResponse;

describe("supplier CSV", () => {
  it("expands catalog components and aggregates identical supplier parts", () => {
    const rows = buildSupplierCsvRows(
      [
        { label: "Uplight", quantity: 3, item: catalogItem() },
        { label: "Downlight", quantity: 1, item: catalogItem() },
      ],
      [],
    );

    expect(rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          supplier: "SiteOne",
          manufacturer: "FX Luminaire",
          sku: "59400232",
          quantity: 4,
          planSource: "Uplight, Downlight",
          status: "Ready",
        }),
        expect.objectContaining({ sku: "75390063", quantity: 8 }),
      ]),
    );
  });

  it("includes traced wire without inventing a supplier SKU or waste allowance", () => {
    const [row] = buildSupplierCsvRows([], [{ label: "C1", wireGauge: 12, lengthFeet: 42.2 }]);

    expect(row).toMatchObject({
      description: "12/2 AWG low-voltage landscape wire",
      quantity: 43,
      unit: "ft",
      status: "Needs SKU",
    });
    expect(row.notes).toContain("add field allowance");
  });

  it("uses the selected package wire SKU when the catalog carries one", () => {
    const wire = catalogItem({
      name: "12/2 Landscape Wire",
      sku: "WIRE-12-2",
      components: null,
    });
    const [row] = buildSupplierCsvRows(
      [],
      [{ label: "C1", wireGauge: 12, lengthFeet: 42.2, item: wire }],
    );

    expect(row).toMatchObject({
      supplier: "SiteOne",
      manufacturer: "FX Luminaire",
      sku: "WIRE-12-2",
      description: "12/2 Landscape Wire",
      quantity: 43,
      status: "Ready",
    });
  });

  it("flags wire whose drawing has not been calibrated", () => {
    const [row] = buildSupplierCsvRows([], [{ label: "C1", wireGauge: 10, lengthFeet: null }]);

    expect(row).toMatchObject({ quantity: 0, status: "Needs route scale" });
  });

  it("escapes spreadsheet formulas and quotes in exported cells", () => {
    const csv = serializeSupplierCsv([
      {
        category: "fixture",
        catalogItemId: "item-1",
        supplier: '=HYPERLINK("bad")',
        manufacturer: "FX Luminaire",
        sku: "SKU-1",
        description: 'Accent "Black"',
        quantity: 2,
        unit: "each",
        planSource: "Uplight",
        status: "Ready",
        notes: "",
      },
    ]);

    expect(csv).toContain('"\'=HYPERLINK(""bad"")"');
    expect(csv).toContain('"Accent ""Black"""');
  });
});
