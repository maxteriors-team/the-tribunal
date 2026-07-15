import { describe, expect, it } from "vitest";

import {
  distToPolyline,
  distToSegment,
  jitter,
  pointsAlongPath,
  snapAngle,
} from "./geometry";

describe("pointsAlongPath", () => {
  it("returns [] for degenerate input", () => {
    expect(pointsAlongPath([], 10)).toEqual([]);
    expect(pointsAlongPath([{ x: 0, y: 0 }], 10)).toEqual([]);
    expect(pointsAlongPath([{ x: 0, y: 0 }, { x: 10, y: 0 }], 0)).toEqual([]);
  });

  it("spaces points along a horizontal line, offset by half a step", () => {
    const pts = pointsAlongPath([{ x: 0, y: 0 }, { x: 100, y: 0 }], 20);
    // First bulb centered at half-spacing (10), then every 20px: 10,30,50,70,90.
    expect(pts.map((q) => Math.round(q.p.x))).toEqual([10, 30, 50, 70, 90]);
    // All flat → angle 0.
    for (const q of pts) expect(q.angle).toBeCloseTo(0);
  });

  it("carries leftover spacing across a corner and reports segment angle", () => {
    const pts = pointsAlongPath(
      [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 40 },
      ],
      10,
    );
    // Second segment runs straight down → angle +90°.
    const vertical = pts.filter((q) => Math.abs(q.p.x - 10) < 0.001 && q.p.y > 0);
    expect(vertical.length).toBeGreaterThan(0);
    for (const q of vertical) expect(q.angle).toBeCloseTo(Math.PI / 2);
  });
});

describe("distToSegment / distToPolyline", () => {
  it("measures perpendicular distance to a segment", () => {
    expect(distToSegment({ x: 5, y: 4 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBe(4);
  });

  it("clamps to the nearest endpoint past the segment", () => {
    expect(distToSegment({ x: -3, y: 0 }, { x: 0, y: 0 }, { x: 10, y: 0 })).toBe(3);
  });

  it("returns Infinity for an empty polyline and the min over segments", () => {
    expect(distToPolyline({ x: 0, y: 0 }, [])).toBe(Infinity);
    const d = distToPolyline({ x: 5, y: 2 }, [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
    ]);
    expect(d).toBe(2);
  });
});

describe("jitter", () => {
  it("is deterministic and bounded to [-1, 1)", () => {
    for (let seed = 0; seed < 50; seed += 1) {
      const v = jitter(seed);
      expect(v).toBeGreaterThanOrEqual(-1);
      expect(v).toBeLessThan(1);
      expect(jitter(seed)).toBe(v); // stable per seed
    }
  });
});

describe("snapAngle", () => {
  it("snaps a near-horizontal drag to exactly horizontal", () => {
    const p = snapAngle({ x: 0, y: 0 }, { x: 100, y: 8 }, 15);
    expect(p.y).toBeCloseTo(0);
    expect(Math.hypot(p.x, p.y)).toBeCloseTo(Math.hypot(100, 8));
  });

  it("returns the point unchanged for a zero-length drag", () => {
    expect(snapAngle({ x: 5, y: 5 }, { x: 5, y: 5 })).toEqual({ x: 5, y: 5 });
  });
});
