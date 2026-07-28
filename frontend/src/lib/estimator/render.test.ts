import { afterEach, describe, expect, it, vi } from "vitest";

import {
  drawPlacedItem,
  drawRunLights,
  drawScene,
  itemHit,
  resizeHandlePos,
  withRunOverrides,
} from "./render";
import type { Design, PlacedItem, Product, Run } from "./types";

// jsdom ships no canvas 2D context. A permissive stub records the calls the
// glow engine makes (drawImage/gradients/paths) so we can smoke-test that a
// full scene renders without throwing — the geometry it feeds the context is
// unit-tested separately in geometry.test.ts.
function fakeCtx() {
  const gradient = { addColorStop: vi.fn() };
  return {
    createRadialGradient: vi.fn(() => gradient),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 20 })),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    arcTo: vi.fn(),
    ellipse: vi.fn(),
    rect: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    setLineDash: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    lineJoin: "",
    lineCap: "",
    globalCompositeOperation: "",
    font: "",
    textBaseline: "",
  } as unknown as CanvasRenderingContext2D;
}

function stubSpriteCanvas() {
  // bulbSprite() creates an offscreen canvas and needs a 2D context to paint
  // the radial glow into. Point it at the same permissive stub.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    fakeCtx() as unknown as CanvasRenderingContext2D,
  );
}

function fakePhoto(w = 1200, h = 800): HTMLImageElement {
  return { naturalWidth: w, naturalHeight: h } as HTMLImageElement;
}

const c9: Product = {
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

afterEach(() => {
  vi.restoreAllMocks();
});

describe("drawScene", () => {
  it("paints the photo, a night wash, and every run + item without throwing", () => {
    stubSpriteCanvas();
    const ctx = fakeCtx();
    const photo = fakePhoto();
    const run: Run = {
      id: "run-1",
      productId: c9.id,
      points: [
        { x: 100, y: 100 },
        { x: 500, y: 100 },
      ],
    };
    const item: PlacedItem = {
      id: "item-1",
      productId: wreath.id,
      at: { x: 300, y: 300 },
      sizePx: 80,
    };
    const design: Design = { calibration: null, runs: [run], items: [item] };
    const products = new Map<string, Product>([
      [c9.id, c9],
      [wreath.id, wreath],
    ]);

    expect(() =>
      drawScene(ctx, photo, design, products, 40, {
        viewScale: 1,
        dusk: 0.52,
        showChrome: true,
      }),
    ).not.toThrow();

    // Photo drawn first; bulbs drawn as sprite images afterwards.
    expect(ctx.drawImage).toHaveBeenCalled();
    // Night wash fill covers the full photo.
    expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 1200, 800);
  });
});

describe("drawRunLights / drawPlacedItem styles", () => {
  it("renders each linear style and the treewrap item without throwing", () => {
    stubSpriteCanvas();
    const ctx = fakeCtx();
    const pts = [
      { x: 0, y: 0 },
      { x: 200, y: 0 },
    ];
    for (const style of ["c9", "mini", "garland", "stake", "permanent"] as const) {
      expect(() =>
        drawRunLights(ctx, pts, { ...c9, style }, 40, 2),
      ).not.toThrow();
    }
    const tree: PlacedItem = {
      id: "t",
      productId: "x",
      at: { x: 100, y: 100 },
      sizePx: 120,
    };
    expect(() =>
      drawPlacedItem(ctx, tree, { ...wreath, style: "treewrap" }, 40, 2),
    ).not.toThrow();
  });

  it("renders a scaled (jumbo) bulb without throwing", () => {
    stubSpriteCanvas();
    const ctx = fakeCtx();
    const pts = [
      { x: 0, y: 0 },
      { x: 200, y: 0 },
    ];
    expect(() =>
      drawRunLights(ctx, pts, { ...c9, bulbScale: 1.6 }, 40, 2),
    ).not.toThrow();
    expect(ctx.drawImage).toHaveBeenCalled();
  });
});

describe("withRunOverrides", () => {
  it("returns the product unchanged when the run has no overrides", () => {
    const run: Run = { id: "r", productId: c9.id, points: [] };
    expect(withRunOverrides(c9, run)).toBe(c9);
  });

  it("layers per-run spacing, colors, and bulb size over the product", () => {
    const run: Run = {
      id: "r",
      productId: c9.id,
      points: [],
      spacingIn: 6,
      colors: ["#ff0000"],
      bulbScale: 1.6,
    };
    const merged = withRunOverrides(c9, run);
    expect(merged.spacingIn).toBe(6);
    expect(merged.colors).toEqual(["#ff0000"]);
    expect(merged.bulbScale).toBe(1.6);
  });

  it("treats a bulb-size-only override as a change", () => {
    const run: Run = { id: "r", productId: c9.id, points: [], bulbScale: 0.75 };
    const merged = withRunOverrides(c9, run);
    expect(merged).not.toBe(c9);
    expect(merged.bulbScale).toBe(0.75);
    // untouched fields still fall back to the product
    expect(merged.spacingIn).toBe(c9.spacingIn);
  });
});

describe("itemHit / resizeHandlePos", () => {
  const item: PlacedItem = {
    id: "i",
    productId: wreath.id,
    at: { x: 100, y: 100 },
    sizePx: 80,
  };

  it("hits inside the body radius plus slack", () => {
    expect(itemHit(item, { x: 130, y: 100 }, 4)).toBe(true);
    expect(itemHit(item, { x: 200, y: 100 }, 4)).toBe(false);
  });

  it("places the resize handle down-right of the body", () => {
    const h = resizeHandlePos(item);
    expect(h.x).toBeGreaterThan(item.at.x);
    expect(h.y).toBeGreaterThan(item.at.y);
  });
});

describe("landscape fixture geometry", () => {
  const uplight: Product = {
    id: "fixture-up",
    name: "ZD Uplight",
    category: "landscape",
    kind: "each",
    price: 411,
    style: "uplight",
    colors: ["#ffd98a"],
    spacingIn: 0,
    sizeFt: 14,
    target: { field: "landscape", fixtureType: "uplight" },
  };
  const item: PlacedItem = {
    id: "i1",
    productId: uplight.id,
    at: { x: 200, y: 400 },
    sizePx: 300,
  };

  it("puts the resize grip at the end of the throw, not on a bounding box", () => {
    expect(resizeHandlePos(item, uplight)).toEqual({ x: 200, y: 100 });
  });

  it("grabs the fixture, not the whole beam", () => {
    // Near the fixture selects it…
    expect(itemHit(item, { x: 210, y: 405 }, 4, uplight)).toBe(true);
    // …but a point up inside the beam does not, so the house stays clickable.
    expect(itemHit(item, { x: 200, y: 200 }, 4, uplight)).toBe(false);
    // Decor keeps its full-diameter grab area.
    expect(itemHit(item, { x: 200, y: 300 }, 4)).toBe(true);
  });
});

/**
 * A context stub that tracks the current transform.
 *
 * Faithful to the canvas spec on one point that matters here: a gradient's
 * coordinates are interpreted in the user space active when it is **painted**
 * (fill time), not when it is created. So a gradient built before a translate
 * and filled after one lands at double the offset, silently filling the shape
 * with its transparent outer stop — a fixture that is counted and billed but
 * renders nothing on the photo.
 */
function trackingCtx() {
  type M = { tx: number; ty: number; sx: number; sy: number };
  const stack: M[] = [];
  let cur: M = { tx: 0, ty: 0, sx: 1, sy: 1 };
  const dev = (m: M, x: number, y: number) => ({
    x: m.tx + x * m.sx,
    y: m.ty + y * m.sy,
  });

  // Raw, untransformed declaration of the pending fill style.
  let pending: { cx: number; cy: number; r: number } | null = null;
  const painted: { cx: number; cy: number; r: number }[] = [];
  const arcs: { cx: number; cy: number; r: number }[] = [];
  let pendingArc: { cx: number; cy: number; r: number } | null = null;

  const ctx = {
    createRadialGradient: vi.fn(
      (_x0: number, _y0: number, _r0: number, x1: number, y1: number, r1: number) => {
        const decl = { cx: x1, cy: y1, r: r1 };
        return { addColorStop: vi.fn(), __decl: decl };
      },
    ),
    createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
    arc: vi.fn((x: number, y: number, r: number) => {
      pendingArc = { cx: x, cy: y, r };
    }),
    // fill() is where both the shape and the gradient resolve to device space.
    fill: vi.fn(() => {
      if (pendingArc) {
        const d = dev(cur, pendingArc.cx, pendingArc.cy);
        arcs.push({ cx: d.x, cy: d.y, r: pendingArc.r * cur.sx });
        pendingArc = null;
      }
      if (pending) {
        const d = dev(cur, pending.cx, pending.cy);
        painted.push({ cx: d.x, cy: d.y, r: pending.r * cur.sx });
        pending = null;
      }
    }),
    save: vi.fn(() => stack.push({ ...cur })),
    restore: vi.fn(() => {
      cur = stack.pop() ?? cur;
    }),
    translate: vi.fn((x: number, y: number) => {
      cur = { ...cur, tx: cur.tx + x * cur.sx, ty: cur.ty + y * cur.sy };
    }),
    scale: vi.fn((x: number, y: number) => {
      cur = { ...cur, sx: cur.sx * x, sy: cur.sy * y };
    }),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    ellipse: vi.fn(),
    stroke: vi.fn(),
    setLineDash: vi.fn(),
    fillRect: vi.fn(),
    drawImage: vi.fn(),
    set fillStyle(v: unknown) {
      const decl = (v as { __decl?: { cx: number; cy: number; r: number } })?.__decl;
      pending = decl ?? null;
    },
    get fillStyle() {
      return "";
    },
    strokeStyle: "",
    lineWidth: 0,
    globalCompositeOperation: "",
    globalAlpha: 1,
    setTransform: vi.fn(),
  };
  return { ctx, painted, arcs };
}

describe("landscape fixture light actually lands on the fixture", () => {
  const pathLight: Product = {
    id: "fixture-pathlight",
    name: "Path light",
    category: "landscape",
    kind: "each",
    price: 511,
    style: "pathlight",
    colors: ["#ffd98a"],
    spacingIn: 0,
    sizeFt: 7,
    target: { field: "landscape", fixtureType: "pathlight" },
  };

  it("centres a path light's pool gradient on the pool it fills", () => {
    const { ctx, painted, arcs } = trackingCtx();
    const item: PlacedItem = {
      id: "i1",
      productId: pathLight.id,
      at: { x: 400, y: 300 },
      sizePx: 120,
    };
    drawPlacedItem(ctx as unknown as CanvasRenderingContext2D, item, pathLight, 15, 1);

    // The pool is drawn…
    expect(arcs.length).toBeGreaterThan(0);
    expect(painted.length).toBeGreaterThan(0);

    // …and its gradient paints exactly where the pool is. If the gradient were
    // built outside the translated space it would land at (800, 600) and the
    // path light would be invisible on the photo despite being quoted.
    const pool = arcs[0];
    const glow = painted[0];
    expect(glow.cx).toBeCloseTo(pool.cx, 5);
    expect(glow.cy).toBeCloseTo(pool.cy, 5);
    expect(pool.cx).toBeCloseTo(400, 5);
    expect(glow.r).toBeCloseTo(pool.r, 5);
  });

  it("puts a downlight's ground splash under the fixture, not doubled away", () => {
    const downlight: Product = { ...pathLight, style: "downlight", id: "d1" };
    const { ctx, painted, arcs } = trackingCtx();
    const item: PlacedItem = {
      id: "i2",
      productId: downlight.id,
      at: { x: 200, y: 100 },
      sizePx: 90,
    };
    drawPlacedItem(ctx as unknown as CanvasRenderingContext2D, item, downlight, 15, 1);

    // Splash pool sits at the end of the throw (y + reach), gradient on top of it.
    const splash = arcs[0];
    expect(splash.cy).toBeCloseTo(100 + 90, 5);
    expect(painted[0].cx).toBeCloseTo(splash.cx, 5);
    expect(painted[0].cy).toBeCloseTo(splash.cy, 5);
  });
});
