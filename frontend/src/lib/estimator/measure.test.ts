import { describe, expect, it } from "vitest";

import {
  distance,
  polylineLength,
  pxPerFoot,
  REFERENCE_PRESETS,
  rooflineFeet,
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

  it("converts a traced roofline to whole feet using the reference", () => {
    // Reference: 80px == 8ft -> 10 px/ft.
    const reference: Point[] = [
      { x: 0, y: 0 },
      { x: 80, y: 0 },
    ];
    // Roofline traced as 400px total -> 40 ft.
    const roofline: Point[] = [
      { x: 0, y: 0 },
      { x: 200, y: 0 }, // 200px
      { x: 200, y: 200 }, // 200px
    ];
    expect(rooflineFeet(roofline, reference, 8)).toBe(40);
  });

  it("rounds to the nearest foot", () => {
    const reference: Point[] = [
      { x: 0, y: 0 },
      { x: 10, y: 0 }, // 10px == 1ft -> 10 px/ft
    ];
    const roofline: Point[] = [
      { x: 0, y: 0 },
      { x: 44, y: 0 }, // 44px -> 4.4ft -> 4
    ];
    expect(rooflineFeet(roofline, reference, 1)).toBe(4);
  });

  it("returns 0 feet when uncalibrated", () => {
    const roofline: Point[] = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
    ];
    expect(rooflineFeet(roofline, [], 8)).toBe(0);
  });

  it("ships sane reference presets", () => {
    const garage = REFERENCE_PRESETS.find((p) => p.key === "single_garage");
    expect(garage?.feet).toBe(8);
    expect(REFERENCE_PRESETS.every((p) => p.feet > 0 && p.label)).toBe(true);
  });
});
