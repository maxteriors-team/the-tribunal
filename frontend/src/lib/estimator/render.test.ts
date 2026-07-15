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
        nightMode: true,
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
});

describe("withRunOverrides", () => {
  it("returns the product unchanged when the run has no overrides", () => {
    const run: Run = { id: "r", productId: c9.id, points: [] };
    expect(withRunOverrides(c9, run)).toBe(c9);
  });

  it("layers per-run spacing and colors over the product", () => {
    const run: Run = {
      id: "r",
      productId: c9.id,
      points: [],
      spacingIn: 6,
      colors: ["#ff0000"],
    };
    const merged = withRunOverrides(c9, run);
    expect(merged.spacingIn).toBe(6);
    expect(merged.colors).toEqual(["#ff0000"]);
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
