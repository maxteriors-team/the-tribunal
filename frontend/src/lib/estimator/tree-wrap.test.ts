import { describe, expect, it } from "vitest";

import { indexProducts } from "./catalog";
import { designToEstimateInputs } from "./design";
import {
  MAX_BILLABLE_QUANTITY,
  calculateWrap,
  isMeasured,
  measuredWrapLines,
  switchWrapShape,
  wrapEstimateLines,
  wrapLineLabel,
  type WrapSpec,
} from "./tree-wrap";
import type { Design, PlacedItem, Product } from "./types";

/**
 * Reference values produced by the standalone Tree Light Quoter, which has been
 * billing real jobs from this geometry. They are pinned here so a refactor of
 * the CRM port can never quietly change what a customer is charged.
 */
const REFERENCE = {
  evergreen: { plannedFeet: 379, rowCount: 20, unitCount: 16 },
  deciduous: { plannedFeet: 477, rowCount: 14, unitCount: 239 },
  trunk: { plannedFeet: 76, rowCount: 16, unitCount: 61 },
  bush: { plannedFeet: 145, rowCount: 6, unitCount: 17 },
} as const;

const evergreen: WrapSpec = {
  shape: "evergreen",
  lightType: "mini",
  heightFt: 20,
  radiusFt: 6,
  rowSpacingIn: 12,
  feetPerUnit: 25,
  pricingMode: "unit",
  unitPrice: 39.99,
};

describe("calculateWrap", () => {
  it("matches the shipped quoter on a 20ft evergreen", () => {
    const result = calculateWrap(evergreen);
    expect(result).toMatchObject(REFERENCE.evergreen);
    expect(result?.unitKind).toBe("strand");
    expect(result?.price).toBe(639.84);
  });

  it("matches the shipped quoter on a rounded canopy", () => {
    const result = calculateWrap({
      shape: "deciduous",
      lightType: "c7",
      heightFt: 16,
      radiusFt: 7,
      rowSpacingIn: 14,
      bulbSpacingIn: 24,
      pricingMode: "unit",
      unitPrice: 1.75,
    });
    expect(result).toMatchObject(REFERENCE.deciduous);
    expect(result?.unitKind).toBe("bulb");
  });

  it("matches the shipped quoter on a wrapped trunk", () => {
    expect(
      calculateWrap({
        shape: "trunk",
        lightType: "c9",
        heightFt: 8,
        trunkWidthIn: 18,
        rowSpacingIn: 6,
        bulbSpacingIn: 15,
        pricingMode: "unit",
        unitPrice: 2.25,
      }),
    ).toMatchObject(REFERENCE.trunk);
  });

  it("matches the shipped quoter on a bush wrapped in garland", () => {
    expect(
      calculateWrap({
        shape: "bush",
        lightType: "garland",
        heightFt: 4,
        widthFt: 8,
        depthFt: 4,
        rowSpacingIn: 8,
        feetPerUnit: 9,
        pricingMode: "unit",
        unitPrice: 24.99,
      }),
    ).toMatchObject(REFERENCE.bush);
  });

  it("bills measured feet when the rep charges by the foot", () => {
    const perFoot = calculateWrap({ ...evergreen, pricingMode: "foot", unitPrice: 2 });
    expect(perFoot?.billedQuantity).toBe(REFERENCE.evergreen.plannedFeet);
    expect(perFoot?.price).toBe(758);
  });

  it("measures without pricing until the rep enters a rate", () => {
    const result = calculateWrap({ ...evergreen, unitPrice: undefined });
    expect(result?.plannedFeet).toBe(REFERENCE.evergreen.plannedFeet);
    expect(result?.price).toBeNull();
  });

  it("counts no units until the strand length is known", () => {
    const result = calculateWrap({ ...evergreen, feetPerUnit: undefined });
    expect(result?.unitCount).toBeNull();
    expect(result?.billedQuantity).toBeNull();
    expect(result?.price).toBeNull();
  });

  it("refuses to price a quantity the server would reject the estimate over", () => {
    // 500 limbs is within every per-field bound, yet bills far past the
    // server's 10,000-line-quantity cap. Sending it 422s the whole estimate.
    const huge = calculateWrap({
      ...evergreen,
      shape: "branch",
      branchWidthIn: 6,
      branchCount: 500,
      rowSpacingIn: 3,
      pricingMode: "foot",
      unitPrice: 2,
    })!;
    expect(huge.billedQuantity).toBeGreaterThan(MAX_BILLABLE_QUANTITY);
    // Still measured for the rep to see, but carries no price to send.
    expect(huge.plannedFeet).toBeGreaterThan(0);
    expect(huge.price).toBeNull();
  });

  it("refuses impossible dimensions instead of pricing them", () => {
    for (const bad of [0, -4, Number.NaN, Number.POSITIVE_INFINITY, 10_000]) {
      expect(calculateWrap({ ...evergreen, heightFt: bad })).toBeNull();
      expect(calculateWrap({ ...evergreen, radiusFt: bad })).toBeNull();
      expect(calculateWrap({ ...evergreen, rowSpacingIn: bad })).toBeNull();
    }
  });

  it("refuses a shape whose own dimensions are missing", () => {
    expect(calculateWrap({ ...evergreen, shape: "trunk", trunkWidthIn: undefined })).toBeNull();
    expect(calculateWrap({ ...evergreen, shape: "bush", widthFt: 8 })).toBeNull();
    expect(
      calculateWrap({ ...evergreen, shape: "branch", branchWidthIn: 4, branchCount: 2.5 }),
    ).toBeNull();
  });

  it("never returns less footage for a taller tree", () => {
    let previous = 0;
    for (let heightFt = 6; heightFt <= 40; heightFt += 2) {
      const result = calculateWrap({ ...evergreen, heightFt });
      expect(result!.plannedFeet).toBeGreaterThanOrEqual(previous);
      previous = result!.plannedFeet;
    }
  });

  it("needs more wire as the rows get tighter", () => {
    const loose = calculateWrap({ ...evergreen, rowSpacingIn: 24 })!;
    const tight = calculateWrap({ ...evergreen, rowSpacingIn: 6 })!;
    expect(tight.plannedFeet).toBeGreaterThan(loose.plannedFeet);
    expect(tight.rowCount).toBeGreaterThan(loose.rowCount);
  });
});

describe("switchWrapShape", () => {
  it("keeps the tree priced when the rep changes their mind", () => {
    // The rep says "actually that's a bush" mid-conversation. If the price and
    // the customer's photo blank out at that moment, the tool has failed.
    const asBush = switchWrapShape(evergreen, "bush");
    expect(asBush.widthFt).toBe(12);
    expect(asBush.depthFt).toBe(12);
    expect(calculateWrap(asBush)?.price).toBeGreaterThan(0);
  });

  it("reads a bush's width back as a canopy radius", () => {
    const bush: WrapSpec = {
      ...evergreen,
      shape: "bush",
      radiusFt: undefined,
      widthFt: 10,
      depthFt: 6,
    };
    expect(switchWrapShape(bush, "evergreen").radiusFt).toBe(5);
  });

  it("carries a girth between a trunk and a limb", () => {
    const trunk = switchWrapShape({ ...evergreen, shape: "trunk", trunkWidthIn: 18 }, "branch");
    expect(trunk.branchWidthIn).toBe(18);
    expect(trunk.branchCount).toBe(1);
    expect(switchWrapShape(trunk, "trunk").trunkWidthIn).toBe(18);
  });

  it("never overwrites what the rep already measured", () => {
    const withBoth: WrapSpec = { ...evergreen, radiusFt: 6, widthFt: 20, depthFt: 4 };
    const asBush = switchWrapShape(withBoth, "bush");
    expect(asBush.widthFt).toBe(20);
    expect(asBush.depthFt).toBe(4);
    // Switching away and back returns exactly what was measured.
    expect(switchWrapShape(asBush, "evergreen").radiusFt).toBe(6);
  });

  it("moves a hand-wrapped shape off bulb cord it cannot be installed with", () => {
    const c9: WrapSpec = { ...evergreen, lightType: "c9", bulbSpacingIn: 12 };
    expect(switchWrapShape(c9, "bush").lightType).toBe("mini");
    // A cone can take bulb cord, so leave the rep's choice alone.
    expect(switchWrapShape(c9, "deciduous").lightType).toBe("c9");
  });

  it("leaves a dimension blank when nothing comparable is known", () => {
    // A canopy radius says nothing about trunk girth; guessing would quietly
    // put a wrong number on the customer's quote.
    expect(switchWrapShape(evergreen, "trunk").trunkWidthIn).toBeUndefined();
  });
});

describe("wrapLineLabel", () => {
  it("reads as a self-explaining quote line", () => {
    const result = calculateWrap(evergreen)!;
    expect(wrapLineLabel(evergreen, result, "Front spruce")).toBe(
      "Front spruce — 379 ft · 16 strands",
    );
  });

  it("falls back to the shape when the product has no name", () => {
    const result = calculateWrap(evergreen)!;
    expect(wrapLineLabel(evergreen, result, "")).toContain("Evergreen tree");
  });

  it("shows only footage when the job is billed per foot", () => {
    const spec: WrapSpec = { ...evergreen, pricingMode: "foot", unitPrice: 2 };
    expect(wrapLineLabel(spec, calculateWrap(spec)!, "Front spruce")).toBe("Front spruce — 379 ft");
  });

  it("stays within the server's label limit", () => {
    const result = calculateWrap(evergreen)!;
    expect(wrapLineLabel(evergreen, result, "x".repeat(400)).length).toBeLessThanOrEqual(120);
  });
});

const treeProduct: Product = {
  id: "cat-trees-medium",
  name: "Front spruce",
  category: "seasonal",
  kind: "each",
  price: 250,
  style: "treewrap",
  colors: ["#ffd98a"],
  spacingIn: 0,
  sizeFt: 12,
  target: { field: "christmas", category: "trees", option: "medium" },
};

const productById = indexProducts([treeProduct]);

function item(id: string, wrap?: WrapSpec): PlacedItem {
  return { id, productId: treeProduct.id, at: { x: 100, y: 100 }, sizePx: 80, wrap };
}

function design(items: PlacedItem[]): Design {
  return {
    runs: [],
    items,
    calibration: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, feet: 10 },
  } as Design;
}

describe("measured items and the estimate", () => {
  it("bills a measured tree as its own line, not a size band", () => {
    const inputs = designToEstimateInputs(design([item("i1", evergreen)]), productById, 1200);
    // The band count is deliberately absent: the tree is billed by its geometry.
    expect(inputs.christmas_items.trees).toBeUndefined();

    const lines = measuredWrapLines(design([item("i1", evergreen)]), productById);
    expect(lines).toHaveLength(1);
    expect(lines[0].result.plannedFeet).toBe(REFERENCE.evergreen.plannedFeet);
    expect(lines[0].label).toContain("Front spruce");
  });

  it("leaves unmeasured trees on band pricing exactly as before", () => {
    const inputs = designToEstimateInputs(design([item("i1")]), productById, 1200);
    expect(inputs.christmas_items.trees).toEqual({ medium: 1 });
    expect(measuredWrapLines(design([item("i1")]), productById)).toHaveLength(0);
  });

  it("prices a mixed yard once per tree, each on its own basis", () => {
    const yard = design([item("measured", evergreen), item("banded"), item("banded2")]);
    expect(designToEstimateInputs(yard, productById, 1200).christmas_items.trees).toEqual({
      medium: 2,
    });
    expect(measuredWrapLines(yard, productById)).toHaveLength(1);
  });

  it("keeps an over-cap tree off the request but still on the quote", () => {
    const overCap: WrapSpec = {
      ...evergreen,
      shape: "branch",
      branchWidthIn: 6,
      branchCount: 500,
      rowSpacingIn: 3,
      pricingMode: "foot",
      unitPrice: 2,
    };
    const yard = design([item("i1", overCap)]);
    // Not sent as a line — it would 422 the whole estimate...
    expect(measuredWrapLines(yard, productById)).toHaveLength(1);
    expect(wrapEstimateLines(yard, productById)).toHaveLength(0);
    // ...so it keeps its band price rather than riding along free.
    expect(designToEstimateInputs(yard, productById, 1200).christmas_items.trees).toEqual({
      medium: 1,
    });
  });

  it("sends a measured tree as a seasonal line the server will accept", () => {
    const lines = wrapEstimateLines(design([item("i1", evergreen)]), productById);
    expect(lines).toEqual([
      {
        label: "Front spruce — 379 ft · 16 strands",
        quantity: 16,
        unit_price: 39.99,
        side: "seasonal",
      },
    ]);
    // Mirrors the server's own bounds on a custom line.
    expect(lines[0].label.length).toBeLessThanOrEqual(120);
    expect(lines[0].quantity).toBeGreaterThan(0);
    expect(lines[0].quantity).toBeLessThanOrEqual(MAX_BILLABLE_QUANTITY);
  });

  it("leaves a measured-but-unpriced tree on its band price, not free", () => {
    const unpriced = design([item("i1", { ...evergreen, unitPrice: undefined })]);
    expect(measuredWrapLines(unpriced, productById)).toHaveLength(1);
    expect(wrapEstimateLines(unpriced, productById)).toHaveLength(0);
    // The rep sees the footage on the canvas, and the customer is still charged.
    expect(designToEstimateInputs(unpriced, productById, 1200).christmas_items.trees).toEqual({
      medium: 1,
    });
  });

  it("bills every tree exactly once, whichever way it is priced", () => {
    const yard = design([
      item("priced", evergreen),
      item("unpriced", { ...evergreen, unitPrice: undefined }),
      item("banded"),
    ]);
    const banded =
      designToEstimateInputs(yard, productById, 1200).christmas_items.trees?.medium ?? 0;
    // Three trees, three charges: one measured line plus two band counts.
    expect(wrapEstimateLines(yard, productById)).toHaveLength(1);
    expect(banded).toBe(2);
  });

  it("ignores a wrap on decor that is counted, not wrapped", () => {
    // A stored document must not move a wreath onto the seasonal side, nor drop
    // it from its own decor count, just by carrying an unexpected field.
    const wreath: Product = {
      ...treeProduct,
      id: "cat-wreaths-standard",
      style: "wreath",
      target: { field: "christmas", category: "wreaths", option: "standard" },
    };
    const byId = indexProducts([wreath]);
    const doc = design([{ ...item("i1", evergreen), productId: wreath.id }]);
    expect(wrapEstimateLines(doc, byId)).toHaveLength(0);
    expect(designToEstimateInputs(doc, byId, 1200).christmas_items.wreaths).toEqual({
      standard: 1,
    });
  });

  it("falls back to band pricing when the measurement is unusable", () => {
    // A half-typed form must not silently drop the tree off the quote entirely.
    const broken = item("i1", { ...evergreen, radiusFt: undefined });
    expect(isMeasured(broken)).toBe(false);
    expect(designToEstimateInputs(design([broken]), productById, 1200).christmas_items.trees).toEqual(
      { medium: 1 },
    );
    expect(measuredWrapLines(design([broken]), productById)).toHaveLength(0);
  });

  it("ignores a measured item whose product left the catalog", () => {
    const orphan: PlacedItem = { ...item("i1", evergreen), productId: "gone" };
    expect(measuredWrapLines(design([orphan]), productById)).toHaveLength(0);
  });
});
