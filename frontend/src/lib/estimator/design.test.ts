import { describe, expect, it } from "vitest";

import { buildCatalog, indexProducts } from "./catalog";
import {
  ASSUMED_PHOTO_WIDTH_FT,
  designScale,
  designToEstimateInputs,
  hasDesign,
} from "./design";
import type { Design, PlacedItem, Product, Run } from "./types";

const PHOTO_W = 1200;

// A calibration where a 100px line == 10ft → 10 px/ft, so a 400px run == 40ft.
const cal = { a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, feet: 10 };

const roofline: Product = {
  id: "roofline-c9-warm",
  name: "C9 Roofline",
  category: "seasonal",
  kind: "linear",
  price: 6,
  style: "c9",
  colors: ["#ffd98a"],
  spacingIn: 12,
  sizeFt: 0,
  target: { field: "roofline" },
};

const mini: Product = {
  id: "cat-mini_lights-standard",
  name: "Mini Lights",
  category: "seasonal",
  kind: "linear",
  price: 4,
  style: "mini",
  colors: ["#ffd98a"],
  spacingIn: 4,
  sizeFt: 0,
  target: { field: "christmas", category: "mini_lights", option: "standard" },
};

const wreath: Product = {
  id: "cat-wreaths-standard",
  name: "Wreath",
  category: "seasonal",
  kind: "each",
  price: 85,
  style: "wreath",
  colors: ["#ffd98a"],
  spacingIn: 0,
  sizeFt: 3,
  target: { field: "christmas", category: "wreaths", option: "standard" },
};

const productById = indexProducts([roofline, mini, wreath]);

function run(id: string, productId: string, points: Run["points"]): Run {
  return { id, productId, points };
}

describe("designScale", () => {
  it("derives ft/px from the calibration line", () => {
    const s = designScale({ calibration: cal, runs: [], items: [] }, PHOTO_W);
    expect(s.calibrated).toBe(true);
    expect(s.ftPerPx).toBeCloseTo(0.1); // 10ft / 100px
    expect(s.pxPerFt).toBeCloseTo(10);
  });

  it("falls back to an assumed photo width when uncalibrated", () => {
    const s = designScale({ calibration: null, runs: [], items: [] }, PHOTO_W);
    expect(s.calibrated).toBe(false);
    expect(s.ftPerPx).toBeCloseTo(ASSUMED_PHOTO_WIDTH_FT / PHOTO_W);
  });
});

describe("designToEstimateInputs", () => {
  it("routes a roofline run into whole feet", () => {
    const design: Design = {
      calibration: cal,
      runs: [run("r1", roofline.id, [{ x: 0, y: 0 }, { x: 400, y: 0 }])],
      items: [],
    };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.feet).toBe(40); // 400px / 10px-per-ft
    expect(out.christmas_items).toEqual({});
  });

  it("sums multiple roofline runs into a single feet total", () => {
    const design: Design = {
      calibration: cal,
      runs: [
        run("r1", roofline.id, [{ x: 0, y: 0 }, { x: 300, y: 0 }]),
        run("r2", roofline.id, [{ x: 0, y: 0 }, { x: 200, y: 0 }]),
      ],
      items: [],
    };
    expect(designToEstimateInputs(design, productById, PHOTO_W).feet).toBe(50);
  });

  it("routes per-ft decor runs into christmas_items feet", () => {
    const design: Design = {
      calibration: cal,
      runs: [run("r1", mini.id, [{ x: 0, y: 0 }, { x: 250, y: 0 }])],
      items: [],
    };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.feet).toBe(0);
    expect(out.christmas_items).toEqual({ mini_lights: { standard: 25 } });
  });

  it("counts placed each-items", () => {
    const items: PlacedItem[] = [
      { id: "i1", productId: wreath.id, at: { x: 10, y: 10 }, sizePx: 40 },
      { id: "i2", productId: wreath.id, at: { x: 90, y: 10 }, sizePx: 40 },
    ];
    const design: Design = { calibration: cal, runs: [], items };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.christmas_items).toEqual({ wreaths: { standard: 2 } });
  });

  it("combines roofline, decor runs, and placed items in one payload", () => {
    const design: Design = {
      calibration: cal,
      runs: [
        run("r1", roofline.id, [{ x: 0, y: 0 }, { x: 500, y: 0 }]),
        run("r2", mini.id, [{ x: 0, y: 0 }, { x: 120, y: 0 }]),
      ],
      items: [{ id: "i1", productId: wreath.id, at: { x: 5, y: 5 }, sizePx: 40 }],
    };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.feet).toBe(50);
    expect(out.christmas_items).toEqual({
      mini_lights: { standard: 12 },
      wreaths: { standard: 1 },
    });
  });

  it("drops sub-foot stray runs after rounding", () => {
    const design: Design = {
      calibration: cal,
      runs: [run("r1", mini.id, [{ x: 0, y: 0 }, { x: 3, y: 0 }])], // 0.3ft
      items: [],
    };
    expect(designToEstimateInputs(design, productById, PHOTO_W).christmas_items).toEqual(
      {},
    );
  });

  it("ignores runs whose product is unknown", () => {
    const design: Design = {
      calibration: cal,
      runs: [run("r1", "ghost", [{ x: 0, y: 0 }, { x: 400, y: 0 }])],
      items: [],
    };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.feet).toBe(0);
    expect(out.christmas_items).toEqual({});
  });
});

describe("hasDesign", () => {
  it("is false for an empty design and true once anything is added", () => {
    expect(hasDesign({ calibration: cal, runs: [], items: [] })).toBe(false);
    expect(
      hasDesign({
        calibration: cal,
        runs: [run("r", roofline.id, [])],
        items: [],
      }),
    ).toBe(true);
  });
});

describe("buildCatalog bridge", () => {
  it("always yields the built-in roofline C9 products", () => {
    const catalog = buildCatalog(null);
    const ids = catalog.map((p) => p.id);
    expect(ids).toContain("roofline-c9-warm");
    expect(ids).toContain("roofline-c9-multi");
    expect(catalog.every((p) => p.target.field === "roofline")).toBe(true);
  });

  it("derives draw/place products from the christmas catalog", () => {
    const catalog = buildCatalog({
      feet: 0,
      permanent: { enabled: true, total: 0, per_ft: 32 },
      christmas: { enabled: true, total: 0, per_ft: 6, items: [] },
      difference: 0,
      years: 5,
      temporary_multi_year: 0,
      permanent_one_time: 0,
      multi_year_savings: 0,
      permanent_perks: [],
      christmas_perks: [],
      christmas_catalog: [
        {
          key: "mini_lights",
          label: "Mini Lights",
          unit: "per_ft",
          options: [{ key: "standard", name: "Mini lights (installed)", price: 4 }],
        },
        {
          key: "wreaths",
          label: "Wreaths",
          unit: "each",
          options: [{ key: "standard", name: "Wreath (up to 36 in)", price: 85 }],
        },
      ],
    });

    const miniProduct = catalog.find((p) => p.id === "cat-mini_lights-standard");
    expect(miniProduct?.kind).toBe("linear");
    expect(miniProduct?.style).toBe("mini");
    expect(miniProduct?.target).toEqual({
      field: "christmas",
      category: "mini_lights",
      option: "standard",
    });

    const wreathProduct = catalog.find((p) => p.id === "cat-wreaths-standard");
    expect(wreathProduct?.kind).toBe("each");
    expect(wreathProduct?.style).toBe("wreath");
    expect(wreathProduct?.sizeFt).toBeGreaterThan(0);
  });
});
