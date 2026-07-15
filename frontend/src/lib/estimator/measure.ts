/**
 * Pure roofline-measurement math for the linear-feet estimator.
 *
 * The rep marks a **known reference** (front door / garage door) on a photo to
 * establish a pixels-per-foot scale, then traces the roofline as a multi-segment
 * polyline. Feet = polyline pixel length / (reference pixel length / reference
 * feet). Kept dependency-free and framework-free so the scale conversion is unit
 * tested without a canvas — the canvas component only supplies pixel points.
 */

export interface Point {
  x: number;
  y: number;
}

/** A preset real-world width the rep can line up against on the photo. */
export interface ReferencePreset {
  key: string;
  label: string;
  feet: number;
}

/**
 * Common exterior dimensions, in feet. Editable list; the rep picks the one that
 * matches the object they trace. Values are typical US residential sizes.
 */
export const REFERENCE_PRESETS: readonly ReferencePreset[] = [
  { key: "front_door", label: "Front door (single)", feet: 6.67 },
  { key: "double_door", label: "Double / French door", feet: 5 },
  { key: "single_garage", label: "Single garage door", feet: 8 },
  { key: "double_garage", label: "Double garage door", feet: 16 },
] as const;

/** Straight-line distance between two points, in pixels. */
export function distance(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** Total pixel length of an ordered polyline (0 for < 2 points). */
export function polylineLength(points: readonly Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += distance(points[i - 1], points[i]);
  }
  return total;
}

/**
 * Pixels-per-foot from a reference segment. Returns 0 when the inputs can't yield
 * a usable scale (zero-length line or non-positive reference feet), so callers
 * treat "not calibrated yet" as zero rather than dividing by zero.
 */
export function pxPerFoot(referencePx: number, referenceFeet: number): number {
  if (referencePx <= 0 || referenceFeet <= 0) return 0;
  return referencePx / referenceFeet;
}

/**
 * Convert a traced roofline polyline into linear feet given the reference line.
 *
 * Rounded to the nearest whole foot (rooflines are quoted in whole feet). Returns
 * 0 when uncalibrated or nothing is traced.
 */
export function rooflineFeet(
  roofline: readonly Point[],
  referenceLine: readonly Point[],
  referenceFeet: number,
): number {
  const refPx = polylineLength(referenceLine);
  const scale = pxPerFoot(refPx, referenceFeet);
  if (scale <= 0) return 0;
  const feet = polylineLength(roofline) / scale;
  return Math.round(feet);
}

/**
 * Evenly spaced bulb centers along a traced polyline, for rendering a C9 light
 * strand on the eaves. Bulbs divide the polyline into equal segments closest to
 * `spacingPx`, so the strand always ends flush on the last corner. Both
 * endpoints are always included.
 *
 * Pure (no canvas): the caller converts these pixel points into glowing bulbs.
 * Returns [] for a degenerate line (< 2 points or zero length) or a
 * non-positive spacing, so callers can skip drawing without extra guards.
 */
export function c9BulbPositions(
  polyline: readonly Point[],
  spacingPx: number,
): Point[] {
  if (polyline.length < 2 || spacingPx <= 0) return [];
  const total = polylineLength(polyline);
  if (total <= 0) return [];
  const intervals = Math.max(1, Math.round(total / spacingPx));
  const step = total / intervals;
  const positions: Point[] = [];
  let segIndex = 1;
  let segStart = polyline[0];
  let segEnd = polyline[1];
  let segLen = distance(segStart, segEnd);
  let distConsumed = 0; // arc length from the polyline start to segStart
  for (let i = 0; i <= intervals; i += 1) {
    const target = Math.min(total, i * step);
    // Advance to the segment that contains the target arc length.
    while (segIndex < polyline.length - 1 && target > distConsumed + segLen) {
      distConsumed += segLen;
      segIndex += 1;
      segStart = polyline[segIndex - 1];
      segEnd = polyline[segIndex];
      segLen = distance(segStart, segEnd);
    }
    const along = segLen > 0 ? (target - distConsumed) / segLen : 0;
    positions.push({
      x: segStart.x + (segEnd.x - segStart.x) * along,
      y: segStart.y + (segEnd.y - segStart.y) * along,
    });
  }
  return positions;
}
