import { describe, expect, it } from "vitest";

import {
  c9BulbPositions,
  distance,
  polylineLength,
  pxPerFoot,
  type Point,
} from "./measure";

describe("measure", () => {
  it("computes euclidean distance", () => {
    expect(distance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });

  it("sums a multi-segment polyline", () => {
    const pts: Point[] = [
      { x: 0, y: 0 },
      { x: 3, y: 4 }, // +5
      { x: 3, y: 4 + 10 }, // +10
    ];
    expect(polylineLength(pts)).toBe(15);
  });

  it("returns 0 length for fewer than two points", () => {
    expect(polylineLength([])).toBe(0);
    expect(polylineLength([{ x: 1, y: 1 }])).toBe(0);
  });

  it("derives pixels-per-foot from a reference segment", () => {
    // A garage door 8ft wide drawn as 80px -> 10 px/ft.
    expect(pxPerFoot(80, 8)).toBe(10);
  });

  it("guards against divide-by-zero / bad calibration", () => {
    expect(pxPerFoot(0, 8)).toBe(0);
    expect(pxPerFoot(80, 0)).toBe(0);
    expect(pxPerFoot(-5, 8)).toBe(0);
  });

});

describe("c9BulbPositions", () => {
  it("returns [] for fewer than two points", () => {
    expect(c9BulbPositions([], 10)).toEqual([]);
    expect(c9BulbPositions([{ x: 1, y: 1 }], 10)).toEqual([]);
  });

  it("returns [] for a non-positive spacing", () => {
    const line: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ];
    expect(c9BulbPositions(line, 0)).toEqual([]);
    expect(c9BulbPositions(line, -5)).toEqual([]);
  });

  it("returns [] for a zero-length line", () => {
    expect(
      c9BulbPositions(
        [
          { x: 5, y: 5 },
          { x: 5, y: 5 },
        ],
        10,
      ),
    ).toEqual([]);
  });

  it("spaces bulbs evenly and includes both endpoints", () => {
    // 100px line at 10px spacing -> 10 intervals -> 11 bulbs, 10px apart.
    const bulbs = c9BulbPositions(
      [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
      ],
      10,
    );
    expect(bulbs).toHaveLength(11);
    expect(bulbs[0]).toEqual({ x: 0, y: 0 });
    expect(bulbs[10]).toEqual({ x: 100, y: 0 });
    expect(bulbs[1].x).toBeCloseTo(10);
    expect(bulbs[5].x).toBeCloseTo(50);
  });

  it("walks corners of a multi-segment polyline", () => {
    // L-shape: 50px across then 50px down (total 100px) at 25px spacing.
    const bulbs = c9BulbPositions(
      [
        { x: 0, y: 0 },
        { x: 50, y: 0 },
        { x: 50, y: 50 },
      ],
      25,
    );
    expect(bulbs).toHaveLength(5);
    expect(bulbs[0]).toEqual({ x: 0, y: 0 });
    expect(bulbs[2].x).toBeCloseTo(50);
    expect(bulbs[2].y).toBeCloseTo(0);
    expect(bulbs[4].x).toBeCloseTo(50);
    expect(bulbs[4].y).toBeCloseTo(50);
  });
});
