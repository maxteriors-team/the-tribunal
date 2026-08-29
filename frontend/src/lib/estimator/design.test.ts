import { describe, expect, it } from "vitest";

import { buildCatalog, indexProducts } from "./catalog";
import {
  ASSUMED_PHOTO_WIDTH_FT,
  designScale,
  designToEstimateInputs,
  hasDesign,
  permanentRunFeet,
  sumEstimateInputs,
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

  it("resolves Scale 2 and falls back to Scale 1 when it is missing", () => {
    const design: Design = {
      calibration: cal,
      secondaryCalibration: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, feet: 10 },
      runs: [],
      items: [],
    };

    expect(designScale(design, PHOTO_W, 2).ftPerPx).toBeCloseTo(0.05);
    expect(designScale({ ...design, secondaryCalibration: null }, PHOTO_W, 2).ftPerPx).toBeCloseTo(
      0.1,
    );
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
      runs: [
        run("r1", roofline.id, [
          { x: 0, y: 0 },
          { x: 400, y: 0 },
        ]),
      ],
      items: [],
    };
    const out = designToEstimateInputs(design, productById, PHOTO_W);
    expect(out.feet).toBe(40); // 400px / 10px-per-ft
    expect(out.christmas_items).toEqual({});
  });

  describe("gable pitch (Pythagorean rake correction)", () => {
    const gable = (roofPitch?: "normal" | "steep"): Design => ({
      calibration: cal,
      runs: [
        {
          ...run("r1", roofline.id, [
            { x: 0, y: 0 },
            { x: 400, y: 0 },
          ]),
          ...(roofPitch ? { roofPitch } : {}),
        },
      ],
      items: [],
    });
    const feetOf = (design: Design) => designToEstimateInputs(design, productById, PHOTO_W).feet;

    it("leaves an unmarked run at its measured length", () => {
      // A horizontal eave is already true length; saved designs predate pitch.
      expect(feetOf(gable())).toBe(40);
    });

    it("scales a normal 6/12 gable by sqrt(1 + (6/12)^2)", () => {
      expect(feetOf(gable("normal"))).toBe(Math.round(40 * Math.sqrt(1.25))); // 45
    });

    it("scales a steep 12/12 gable by sqrt(2)", () => {
      expect(feetOf(gable("steep"))).toBe(Math.round(40 * Math.SQRT2)); // 57
    });

    it("orders flat < normal < steep and never shrinks a run", () => {
      const [flat, normal, steep] = [
        feetOf(gable()),
        feetOf(gable("normal")),
        feetOf(gable("steep")),
      ];
      expect(flat).toBeLessThan(normal);
      expect(normal).toBeLessThan(steep);
    });

    it("corrects only the roofline, leaving other linear products measured flat", () => {
      const design: Design = {
        calibration: cal,
        runs: [
          {
            ...run("c1", mini.id, [
              { x: 0, y: 0 },
              { x: 400, y: 0 },
            ]),
            roofPitch: "steep",
          },
        ],
        items: [],
      };
      const out = designToEstimateInputs(design, productById, PHOTO_W);
      expect(out.feet).toBe(0);
      expect(out.christmas_items.mini_lights?.standard).toBe(40);
    });
  });

  it("sums equal-pixel runs using their assigned scales while old runs stay on Scale 1", () => {
    const design: Design = {
      calibration: cal,
      secondaryCalibration: { a: { x: 0, y: 0 }, b: { x: 200, y: 0 }, feet: 10 },
      runs: [
        run("scale-1", roofline.id, [
          { x: 0, y: 0 },
          { x: 400, y: 0 },
        ]),
        {
          ...run("scale-2", roofline.id, [
            { x: 0, y: 20 },
            { x: 400, y: 20 },
          ]),
          scaleSlot: 2,
        },
      ],
      items: [],
    };

    expect(designToEstimateInputs(design, productById, PHOTO_W).feet).toBe(60);
    expect(
      designToEstimateInputs({ ...design, secondaryCalibration: undefined }, productById, PHOTO_W)
        .feet,
    ).toBe(80);
  });

  it("sums multiple roofline runs into a single feet total", () => {
    const design: Design = {
      calibration: cal,
      runs: [
        run("r1", roofline.id, [
          { x: 0, y: 0 },
          { x: 300, y: 0 },
        ]),
        run("r2", roofline.id, [
          { x: 0, y: 0 },
          { x: 200, y: 0 },
        ]),
      ],
      items: [],
    };
    expect(designToEstimateInputs(design, productById, PHOTO_W).feet).toBe(50);
  });

  it("routes per-ft decor runs into christmas_items feet", () => {
    const design: Design = {
      calibration: cal,
      runs: [
        run("r1", mini.id, [
          { x: 0, y: 0 },
          { x: 250, y: 0 },
        ]),
      ],
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
        run("r1", roofline.id, [
          { x: 0, y: 0 },
          { x: 500, y: 0 },
        ]),
        run("r2", mini.id, [
          { x: 0, y: 0 },
          { x: 120, y: 0 },
        ]),
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
      runs: [
        run("r1", mini.id, [
          { x: 0, y: 0 },
          { x: 3, y: 0 },
        ]),
      ], // 0.3ft
      items: [],
    };
    expect(designToEstimateInputs(design, productById, PHOTO_W).christmas_items).toEqual({});
  });

  it("ignores runs whose product is unknown", () => {
    const design: Design = {
      calibration: cal,
      runs: [
        run("r1", "ghost", [
          { x: 0, y: 0 },
          { x: 400, y: 0 },
        ]),
      ],
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
      proposal_side: "comparison",
      discount_amount: 0,
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

describe("designToEstimateInputs — landscape", () => {
  const uplight: Product = {
    id: "fixture-best-zd-up",
    name: "ZD Uplight",
    category: "landscape",
    kind: "each",
    price: 411,
    style: "uplight",
    colors: ["#ffd98a"],
    spacingIn: 0,
    sizeFt: 14,
    sku: "best-zd-up",
    target: { field: "landscape", fixtureType: "uplight" },
  };

  const bistro: Product = {
    id: "fixture-bistro-color",
    name: "Bistro String Lighting",
    category: "landscape",
    kind: "linear",
    price: 18,
    style: "bistro",
    colors: ["#ffd98a"],
    spacingIn: 24,
    sizeFt: 0,
    sku: "bistro-color",
    target: { field: "bistro" },
  };

  const transformer: Product = {
    ...uplight,
    id: "fixture-transformer",
    name: "Transformer",
    style: "transformer",
    sizeFt: 3,
    target: { field: "annotation", annotationType: "transformer" },
  };

  const wire: Product = {
    ...bistro,
    id: "landscape-wire",
    name: "Wire circuit",
    price: 0,
    style: "wire",
    target: { field: "annotation", annotationType: "wire" },
  };

  const productById = indexProducts([uplight, bistro, transformer, wire]);

  it("counts each placed fixture by type, for the package to resolve", () => {
    const items: PlacedItem[] = [
      { id: "i1", productId: uplight.id, at: { x: 10, y: 10 }, sizePx: 100 },
      { id: "i2", productId: uplight.id, at: { x: 40, y: 10 }, sizePx: 100 },
      { id: "i3", productId: uplight.id, at: { x: 70, y: 10 }, sizePx: 100 },
    ];
    const out = designToEstimateInputs({ calibration: cal, runs: [], items }, productById, PHOTO_W);
    expect(out.fixtures).toEqual({ uplight: 3 });
    // Landscape counts never leak into the holiday buckets.
    expect(out.feet).toBe(0);
    expect(out.christmas_items).toEqual({});
  });

  it("keeps the transformer as a plan symbol instead of adding an unpriced fixture", () => {
    const out = designToEstimateInputs(
      {
        calibration: cal,
        runs: [],
        items: [{ id: "tx", productId: transformer.id, at: { x: 10, y: 10 }, sizePx: 30 }],
      },
      productById,
      PHOTO_W,
    );

    expect(out.fixtures).toEqual({});
    expect(out.christmas_items).toEqual({});
  });

  it("keeps plan-only wire routes out of quote-producing footage", () => {
    const out = designToEstimateInputs(
      {
        calibration: cal,
        runs: [
          {
            id: "circuit-1",
            productId: wire.id,
            points: [
              { x: 0, y: 0 },
              { x: 500, y: 0 },
            ],
            circuitLabel: "C1",
            wireGauge: 12,
            sourceVoltage: 12,
          },
        ],
        items: [],
      },
      productById,
      PHOTO_W,
    );

    expect(out.feet).toBe(0);
    expect(out.bistro_feet).toBe(0);
    expect(out.fixtures).toEqual({});
  });

  it("totals several photos of one job into a single set of inputs", () => {
    // Front elevation + back patio: the quote covers both, and each photo was
    // already measured on its own calibration before it got here.
    const front = {
      feet: 120,
      christmas_items: { wreaths: { small: 2 } },
      fixtures: { uplight: 4 },
      bistro_feet: 0,
    };
    const back = {
      feet: 40,
      christmas_items: { wreaths: { small: 1 }, trees: { medium: 1 } },
      fixtures: { uplight: 2, path: 6 },
      bistro_feet: 35,
    };

    expect(sumEstimateInputs([front, back])).toEqual({
      feet: 160,
      christmas_items: { wreaths: { small: 3 }, trees: { medium: 1 } },
      fixtures: { uplight: 6, path: 6 },
      bistro_feet: 35,
    });
    // No photos is a zero job, never NaN or missing buckets.
    expect(sumEstimateInputs([])).toEqual({
      feet: 0,
      christmas_items: {},
      fixtures: {},
      bistro_feet: 0,
    });
  });

  it("does not mutate the per-photo inputs it totals", () => {
    // The designer keeps these per shot, so summing must not fold one photo's
    // counts into another photo's object.
    const front = {
      feet: 10,
      christmas_items: { wreaths: { small: 1 } },
      fixtures: { uplight: 1 },
      bistro_feet: 0,
    };
    sumEstimateInputs([front, front]);
    expect(front.christmas_items).toEqual({ wreaths: { small: 1 } });
    expect(front.fixtures).toEqual({ uplight: 1 });
  });

  it("measures a traced bistro strand in whole feet", () => {
    // 10 px/ft from the shared calibration → a 400px span is 40 ft.
    const runs: Run[] = [
      {
        id: "r1",
        productId: bistro.id,
        points: [
          { x: 0, y: 0 },
          { x: 400, y: 0 },
        ],
      },
    ];
    const out = designToEstimateInputs({ calibration: cal, runs, items: [] }, productById, PHOTO_W);
    expect(out.bistro_feet).toBe(40);
    expect(out.feet).toBe(0);
  });
});

describe("permanentRunFeet", () => {
  const permanent: Product = {
    id: "roofline-permanent",
    name: "Permanent LED Roofline",
    category: "permanent",
    kind: "linear",
    price: 30,
    style: "permanent",
    colors: ["#ffd98a"],
    spacingIn: 12,
    sizeFt: 0,
    target: { field: "roofline" },
  };
  // Seasonal footage is priced on its own path; counting it here would inflate
  // the permanent quote.
  const permanentProducts = indexProducts([permanent, roofline]);

  // 10 px/ft from the shared calibration, so each 400px span is 40 ft.
  function permanentRun(id: string, y: number, extra: Partial<Run> = {}): Run {
    return {
      id,
      productId: permanent.id,
      points: [
        { x: 0, y },
        { x: 400, y },
      ],
      ...extra,
    };
  }

  function measure(runs: Run[]) {
    return permanentRunFeet(
      [{ design: { calibration: cal, runs, items: [] }, photo: { width: PHOTO_W } }],
      permanentProducts,
    );
  }

  it("buckets measured footage by the elevation tagged on each run", () => {
    const totals = measure([
      permanentRun("front-1", 0, { elevation: "front" }),
      permanentRun("side-1", 20, { elevation: "side" }),
      permanentRun("side-2", 40, { elevation: "side" }),
      permanentRun("back-1", 60, { elevation: "back" }),
    ]);

    expect(totals.elevation.front).toBeCloseTo(40);
    expect(totals.elevation.side).toBeCloseTo(80);
    expect(totals.elevation.back).toBeCloseTo(40);
  });

  it("counts an untagged run as front so older drawings price unchanged", () => {
    const totals = measure([permanentRun("legacy", 0)]);

    expect(totals.elevation).toEqual({ front: 40, side: 0, back: 0 });
    expect(totals.complexity.standard).toBeCloseTo(40);
  });

  it("keeps elevation and complexity independent, and ignores seasonal runs", () => {
    const totals = measure([
      permanentRun("back-complex", 0, { elevation: "back", permanentComplexity: "complex" }),
      {
        ...run("seasonal", roofline.id, [
          { x: 0, y: 20 },
          { x: 400, y: 20 },
        ]),
        elevation: "back",
      },
    ]);

    expect(totals.elevation.back).toBeCloseTo(40);
    expect(totals.complexity.complex).toBeCloseTo(40);
    expect(totals.complexity.standard).toBe(0);
  });
});
