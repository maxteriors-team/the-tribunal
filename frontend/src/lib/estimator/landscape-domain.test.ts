import { describe, expect, it } from "vitest";

import { upsertProposalZone } from "./landscape-annotations";
import {
  calculatePreconProgress,
  LANDSCAPE_PRECON_ITEMS,
  setPreconResponse,
} from "./landscape-precon";
import {
  buildLandscapeProcurement,
  procurementStateForRow,
  recountLandscapeProcurement,
} from "./landscape-procurement";
import { buildLandscapeSchedule, copyScheduleSelectionToType } from "./landscape-schedule";
import {
  deleteLandscapeSheet,
  duplicateLandscapeSheet,
  recountLandscapeFixtures,
} from "./landscape-sheets";
import type { LandscapePreconState, Product } from "./types";

const products: Product[] = [
  {
    id: "fixture-uplight",
    name: "Uplight",
    category: "landscape",
    kind: "each",
    price: 0,
    style: "uplight",
    colors: ["#ffffff"],
    spacingIn: 0,
    sizeFt: 1,
    target: { field: "landscape", fixtureType: "uplight" },
  },
];

const shot = {
  id: "shot-1",
  photo: { dataUrl: "data:image/png;base64,AAAA", width: 100, height: 80 },
  design: {
    calibration: null,
    runs: [],
    items: [
      {
        id: "item-1",
        productId: "fixture-uplight",
        at: { x: 1, y: 2 },
        sizePx: 30,
        catalogItemId: "fixture",
      },
      { id: "item-2", productId: "fixture-uplight", at: { x: 3, y: 4 }, sizePx: 30 },
    ],
  },
  dusk: 0.4,
  sheet: { label: "Front", drawingNumber: "L-1" },
};

const catalog = [
  {
    id: "fixture",
    workspace_id: "w",
    name: "Brass Uplight",
    sku: "UP-1",
    kind: "product" as const,
    unit_price: 100,
    taxable: true,
    is_active: true,
    is_attachable: false,
    components: [{ sku: "LAMP-1", qty: 1, description: "MR16 lamp" }],
    attributes: { manufacturer: "Maxteriors", supplier: "Local Supply" },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "lamp",
    workspace_id: "w",
    name: "MR16 Lamp",
    sku: "LAMP-1",
    kind: "product" as const,
    unit_price: 20,
    taxable: true,
    is_active: true,
    is_attachable: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

describe("landscape domain modules", () => {
  it("duplicates, deletes, relabels, and recounts sheets safely", () => {
    const duplicate = duplicateLandscapeSheet([shot], "shot-1");
    expect(duplicate).toHaveLength(2);
    expect(duplicate[1].id).not.toBe("shot-1");
    expect(duplicate[1].design.items[0].id).not.toBe("item-1");
    expect(duplicate.map((entry) => entry.sheet?.drawingNumber)).toEqual(["L-1", "L-2"]);
    expect(deleteLandscapeSheet(duplicate, duplicate[0].id)).toHaveLength(1);
    expect(deleteLandscapeSheet([shot], "shot-1")).toHaveLength(1);
    expect(recountLandscapeFixtures(duplicate, () => true)).toHaveLength(4);
  });

  it("resolves schedule catalog data and copies fixture selections by type", () => {
    const schedule = buildLandscapeSchedule([shot], products, catalog);
    expect(schedule).toHaveLength(2);
    expect(schedule[0]).toMatchObject({ fixtureName: "Brass Uplight", fixtureSku: "UP-1" });
    expect(schedule[1].unresolved).toContain("Fixture has no price-book mapping");
    const copied = copyScheduleSelectionToType([shot], "item-1");
    expect(copied[0].design.items[1].catalogItemId).toBe("fixture");
  });

  it("rolls up live catalog costs, components, procurement status, and unresolved lines", () => {
    const schedule = buildLandscapeSchedule([shot], products, catalog);
    const procurement = buildLandscapeProcurement(schedule, catalog, {
      "fixture:fixture": { orderedQuantity: 1, receivedQuantity: 0, supplierNote: "PO-1" },
    });
    expect(procurement.find((row) => row.key === "fixture:fixture")).toMatchObject({
      needed: 1,
      ordered: 1,
      unitCost: 100,
      supplier: "Local Supply",
      status: "ordered",
    });
    expect(procurement.find((row) => row.key === "component:LAMP-1")).toMatchObject({
      needed: 1,
      unitCost: 20,
    });
    expect(procurement.some((row) => row.status === "unresolved")).toBe(true);
  });

  it("replaces a fixture's bundled lamp when a schedule lamp is assigned", () => {
    const scheduledShot = {
      ...shot,
      design: {
        ...shot.design,
        items: shot.design.items.map((item, index) =>
          index === 0
            ? { ...item, lampCatalogItemId: "lamp" }
            : { ...item, catalogItemId: "fixture" },
        ),
      },
    };
    const schedule = buildLandscapeSchedule([scheduledShot], products, catalog);
    const procurement = buildLandscapeProcurement(schedule, catalog);

    expect(procurement.find((row) => Object.is(row.key, "lamp:lamp"))).toMatchObject({
      needed: 1,
      name: "MR16 Lamp",
    });
    expect(procurement.find((row) => Object.is(row.key, "component:LAMP-1"))).toMatchObject({
      needed: 1,
    });
  });

  it("preserves editable order fields while recounting plan quantities", () => {
    const schedule = buildLandscapeSchedule([shot], products, catalog);
    const procurement = buildLandscapeProcurement(schedule, catalog, {
      "fixture:fixture": {
        catalogItemId: "fixture",
        catalogSku: "CUSTOM-UP",
        description: "Patina uplight",
        manufacturer: "Tribunal Lighting",
        supplier: "Regional Supply",
        neededQuantity: 4,
        orderedQuantity: 3,
        receivedQuantity: 1,
        unitCost: 82.5,
        supplierNote: "PO-1042",
      },
    });
    const fixture = procurement.find((row) => Object.is(row.key, "fixture:fixture"))!;

    expect(fixture).toMatchObject({
      name: "Patina uplight",
      sku: "CUSTOM-UP",
      manufacturer: "Tribunal Lighting",
      supplier: "Regional Supply",
      needed: 4,
      ordered: 3,
      received: 1,
      unitCost: 82.5,
      totalCost: 330,
      supplierNote: "PO-1042",
    });

    const saved = procurementStateForRow(fixture);
    const recounted = recountLandscapeProcurement({ [fixture.key]: saved });
    expect(recounted[fixture.key]).not.toHaveProperty("neededQuantity");
    expect(recounted[fixture.key]).toMatchObject({
      orderedQuantity: 3,
      receivedQuantity: 1,
      unitCost: 82.5,
      supplierNote: "PO-1042",
    });
  });

  it("keeps exactly 26 canonical pre-con items and calculates completion", () => {
    expect(LANDSCAPE_PRECON_ITEMS).toHaveLength(26);
    let state: LandscapePreconState = { responses: [], leadInstaller: "Morgan", notes: "" };
    state = setPreconResponse(state, LANDSCAPE_PRECON_ITEMS[0].id, "yes");
    state = setPreconResponse(state, LANDSCAPE_PRECON_ITEMS[1].id, "no", "Awaiting deposit");
    expect(calculatePreconProgress(state)).toMatchObject({ completed: 2, ready: 1, blocked: 1 });
  });

  it("normalizes proposal zones without duplicating sheet references", () => {
    const zones = upsertProposalZone([], {
      id: "front",
      name: "  Front elevation ",
      description: " Arrival view ",
      shotIds: ["shot-1", "shot-1"],
    });
    expect(zones).toEqual([
      { id: "front", name: "Front elevation", description: "Arrival view", shotIds: ["shot-1"] },
    ]);
  });
});
