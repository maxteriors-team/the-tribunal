import { afterEach, describe, expect, it, vi } from "vitest";

import {
  beamAngleAt,
  beamHandlePos,
  beamRotationAt,
  drawPlacedItem,
  drawRunLights,
  drawScene,
  itemHit,
  resizeHandlePos,
  rotateHandlePos,
  withRunOverrides,
} from "./render";
import {
  DEFAULT_BEAM_ANGLE_DEG,
  MAX_BEAM_ANGLE_DEG,
  MIN_BEAM_ANGLE_DEG,
} from "./types";
import type { Design, PlacedItem, Product, Run } from "./types";

// jsdom ships no canvas 2D context. A permissive stub records the calls the
// glow engine makes (drawImage/gradients/paths) so we can smoke-test that a
// full scene renders without throwing — the geometry it feeds the context is
// unit-tested separately in geometry.test.ts.
function fakeCtx() {
  const gradient = { addColorStop: vi.fn() };
  return {
    createRadialGradient: vi.fn(() => gradient),
    createLinearGradient: vi.fn(() => gradient),
    translate: vi.fn(),
    rotate: vi.fn(),
    scale: vi.fn(),
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

  /** Half-width of the cone at the end of the throw, from the fixture's spread. */
  const halfWidth = (reach: number, deg: number) =>
    reach * Math.tan((deg * Math.PI) / 360);

  it("puts the spread grip on the cone's edge at the default lamp angle", () => {
    const grip = beamHandlePos(item, uplight)!;
    expect(grip.y).toBe(100); // end of the throw, same as the resize grip
    expect(grip.x).toBeCloseTo(
      200 + halfWidth(300, DEFAULT_BEAM_ANGLE_DEG.uplight),
      5,
    );
  });

  it("opens and closes the cone with the fixture's own beam angle", () => {
    const narrow = beamHandlePos({ ...item, beamAngleDeg: 10 }, uplight)!;
    const wide = beamHandlePos({ ...item, beamAngleDeg: 60 }, uplight)!;
    expect(narrow.x).toBeCloseTo(200 + halfWidth(300, 10), 5);
    expect(wide.x).toBeCloseTo(200 + halfWidth(300, 60), 5);
    expect(wide.x).toBeGreaterThan(narrow.x);
  });

  it("leaves the throw alone when the beam opens up", () => {
    // Spread and throw are separate gestures: widening the beam must never also
    // stretch how far the light reaches (which is what the customer is buying).
    expect(resizeHandlePos({ ...item, beamAngleDeg: 60 }, uplight)).toEqual({
      x: 200,
      y: 100,
    });
  });

  it("round-trips a dragged grip back to the angle that drew it", () => {
    for (const deg of [10, 24, 36, 60]) {
      const grip = beamHandlePos({ ...item, beamAngleDeg: deg }, uplight)!;
      expect(beamAngleAt(item, grip)).toBeCloseTo(deg, 5);
    }
  });

  it("clamps a drag past the ends of the range", () => {
    expect(beamAngleAt(item, { x: 200, y: 100 })).toBe(MIN_BEAM_ANGLE_DEG);
    expect(beamAngleAt(item, { x: 100000, y: 100 })).toBe(MAX_BEAM_ANGLE_DEG);
  });

  it("offers no spread grip on fixtures that pool instead of beam", () => {
    const pathlight: Product = { ...uplight, id: "p1", style: "pathlight" };
    expect(beamHandlePos(item, pathlight)).toBeNull();
    expect(beamHandlePos(item, wreath)).toBeNull();
    expect(beamHandlePos(item)).toBeNull();
  });

  // ------------------------------------------------------------------ //
  // Aim — which way the fixture points, independent of how wide it opens
  // ------------------------------------------------------------------ //
  describe("beam aim", () => {
    it("leaves every fixture pointing its natural way by default", () => {
      // The guarantee for designs saved before aiming existed: no rotation
      // field means the exact geometry these fixtures always had.
      expect(resizeHandlePos(item, uplight)).toEqual({ x: 200, y: 100 });
      expect(beamRotationAt(item, { x: 200, y: 100 }, uplight)).toBe(0);
    });

    it("swings the throw around the fixture", () => {
      // A quarter turn clockwise from straight up points due right, and the
      // fixture itself must not move — only the light it throws.
      const grip = resizeHandlePos({ ...item, beamRotationDeg: 90 }, uplight);
      expect(grip.x).toBeCloseTo(500, 5);
      expect(grip.y).toBeCloseTo(400, 5);
    });

    it("keeps the throw length identical at every aim", () => {
      // Aiming is a rotation, not a resize: the customer is buying this reach.
      for (const deg of [-135, -42, 0, 30, 90, 180]) {
        const grip = resizeHandlePos({ ...item, beamRotationDeg: deg }, uplight);
        expect(Math.hypot(grip.x - 200, grip.y - 400)).toBeCloseTo(300, 5);
      }
    });

    it("round-trips a dragged aim grip back to the rotation that drew it", () => {
      for (const deg of [-135, -90, -20, 0, 45, 120, 179]) {
        const aimed = { ...item, beamRotationDeg: deg };
        const grip = rotateHandlePos(aimed, uplight, 1)!;
        expect(beamRotationAt(aimed, grip, uplight)).toBeCloseTo(deg, 5);
      }
    });

    it("reads the same aim for a downlight, which starts pointing the other way", () => {
      // Rotation is a delta from each style's natural axis, so 0 means "down"
      // here and "up" for an uplight — one number, correct for both.
      const downlight: Product = { ...uplight, id: "d1", style: "downlight" };
      expect(resizeHandlePos(item, downlight)).toEqual({ x: 200, y: 700 });
      for (const deg of [-90, -30, 0, 60, 150]) {
        const aimed = { ...item, beamRotationDeg: deg };
        const grip = rotateHandlePos(aimed, downlight, 1)!;
        expect(beamRotationAt(aimed, grip, downlight)).toBeCloseTo(deg, 5);
      }
    });

    it("measures spread across the aimed cone, not across the photo", () => {
      // The spread grip and the spread hit-test must agree at any aim, or
      // grabbing the rim of a tilted beam would snap it to a different angle.
      for (const rot of [0, 35, -80, 140]) {
        for (const deg of [10, 24, 60]) {
          const aimed = { ...item, beamRotationDeg: rot, beamAngleDeg: deg };
          const grip = beamHandlePos(aimed, uplight)!;
          expect(beamAngleAt(aimed, grip)).toBeCloseTo(deg, 5);
        }
      }
    });

    it("floats the aim grip past the throw grip by a constant on-screen gap", () => {
      // Constant in screen pixels so a 5° spot and a 120° flood never bunch
      // their grips together at the moment the rep reaches for one.
      const near = resizeHandlePos(item, uplight);
      const far = rotateHandlePos(item, uplight, 1)!;
      expect(Math.hypot(far.x - near.x, far.y - near.y)).toBeCloseTo(22, 5);
      // Zoomed 2x, the same on-screen gap is half as many image pixels.
      const zoomed = rotateHandlePos(item, uplight, 2)!;
      expect(Math.hypot(zoomed.x - near.x, zoomed.y - near.y)).toBeCloseTo(11, 5);
    });

    it("holds the current aim when the pointer sits on the fixture", () => {
      // No direction to read from a zero-length vector; snapping to an
      // arbitrary bearing would fling the beam mid-drag.
      const aimed = { ...item, beamRotationDeg: 42 };
      expect(beamRotationAt(aimed, item.at, uplight)).toBeCloseTo(42, 5);
    });

    it("wraps past a half turn instead of sticking", () => {
      // Dragging round the back keeps turning rather than jamming at the end of
      // a range. Straight down from an uplight is a half turn either way, and
      // the canonical circle is [-180, 180) — so it reads -180, not +180.
      expect(beamRotationAt(item, { x: 200, y: 700 }, uplight)).toBeCloseTo(-180, 5);
      expect(
        Math.abs(beamRotationAt(item, { x: 199, y: 700 }, uplight)),
      ).toBeGreaterThan(179);
    });

    it("offers no aim grip on fixtures with no beam to aim", () => {
      const pathlight: Product = { ...uplight, id: "p1", style: "pathlight" };
      expect(rotateHandlePos(item, pathlight, 1)).toBeNull();
      expect(rotateHandlePos(item, wreath, 1)).toBeNull();
      expect(rotateHandlePos(item, undefined, 1)).toBeNull();
    });

    it("paints the cone somewhere else once it is aimed", () => {
      stubSpriteCanvas();
      const rotation = (beamRotationDeg?: number) => {
        const ctx = fakeCtx();
        drawPlacedItem(ctx, { ...item, beamRotationDeg }, uplight, 15, 1);
        return (ctx.rotate as unknown as ReturnType<typeof vi.fn>).mock
          .calls[0][0] as number;
      };
      // Straight up asks the canvas for no rotation at all...
      expect(rotation()).toBeCloseTo(0, 5);
      // ...and an aimed fixture rotates by exactly the angle the rep set.
      expect(rotation(45)).toBeCloseTo(Math.PI / 4, 5);
    });
  });

  it("paints a wider cone for a wider beam", () => {
    stubSpriteCanvas();
    const spread = (beamAngleDeg: number) => {
      const ctx = fakeCtx();
      drawPlacedItem(ctx, { ...item, beamAngleDeg }, uplight, 15, 1);
      const xs = (ctx.lineTo as unknown as ReturnType<typeof vi.fn>).mock.calls.map(
        (call) => call[0] as number,
      );
      return Math.max(...xs) - Math.min(...xs);
    };
    expect(spread(60)).toBeGreaterThan(spread(15));
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
  type M = { tx: number; ty: number; sx: number; sy: number; rot: number };
  const stack: M[] = [];
  let cur: M = { tx: 0, ty: 0, sx: 1, sy: 1, rot: 0 };
  // Scale, then rotate, then translate — the order a canvas CTM composes them.
  const dev = (m: M, x: number, y: number) => {
    const cos = Math.cos(m.rot);
    const sin = Math.sin(m.rot);
    const sx = x * m.sx;
    const sy = y * m.sy;
    return { x: m.tx + sx * cos - sy * sin, y: m.ty + sx * sin + sy * cos };
  };

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
      // Translating an already-rotated space moves along the rotated axes.
      const d = dev(cur, x, y);
      cur = { ...cur, tx: d.x, ty: d.y };
    }),
    rotate: vi.fn((a: number) => {
      cur = { ...cur, rot: cur.rot + a };
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
