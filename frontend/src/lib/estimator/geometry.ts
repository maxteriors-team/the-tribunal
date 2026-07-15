/**
 * Path geometry for the light-designer canvas.
 *
 * Extends the pure scale math in `measure.ts` (`Point`, `distance`,
 * `polylineLength`) with the sampling/estimation helpers the glow renderer and
 * canvas editor need: evenly spaced points (with segment angle) along a
 * polyline, deterministic jitter for natural-looking bulb scatter, angle
 * snapping while drawing, and point→segment distance for hit-testing.
 *
 * Framework-free and canvas-free so it unit-tests without a DOM, exactly like
 * `measure.test.ts`. Re-exports `distance`/`polylineLength` so canvas code can
 * pull every path helper from one module.
 */
import { distance, polylineLength, type Point } from "./measure";

export { distance, polylineLength };
export type { Point };

export interface PathPoint {
  p: Point;
  angle: number;
}

/**
 * Emit evenly spaced points (with segment angle) along a polyline. The first
 * point is offset by half a spacing so a strand of bulbs reads centered rather
 * than starting flush on the first vertex. Returns [] for a degenerate line or
 * non-positive spacing so callers can skip drawing without extra guards.
 */
export function pointsAlongPath(
  pts: readonly Point[],
  spacing: number,
): PathPoint[] {
  const out: PathPoint[] = [];
  if (pts.length < 2 || spacing <= 0) return out;
  let carry = spacing / 2;
  for (let i = 1; i < pts.length; i += 1) {
    const a = pts[i - 1];
    const b = pts[i];
    const segLen = distance(a, b);
    if (segLen === 0) continue;
    const ux = (b.x - a.x) / segLen;
    const uy = (b.y - a.y) / segLen;
    const angle = Math.atan2(uy, ux);
    let d = carry;
    while (d <= segLen) {
      out.push({ p: { x: a.x + ux * d, y: a.y + uy * d }, angle });
      d += spacing;
    }
    carry = d - segLen;
  }
  return out;
}

/** Shortest distance from a point to the segment a→b, in pixels. */
export function distToSegment(p: Point, a: Point, b: Point): number {
  const l2 = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
  if (l2 === 0) return distance(p, a);
  let t = ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / l2;
  t = Math.max(0, Math.min(1, t));
  return distance(p, { x: a.x + t * (b.x - a.x), y: a.y + t * (b.y - a.y) });
}

/** Shortest distance from a point to a polyline (Infinity for an empty path). */
export function distToPolyline(p: Point, pts: readonly Point[]): number {
  if (pts.length === 0) return Infinity;
  if (pts.length === 1) return distance(p, pts[0]);
  let best = Infinity;
  for (let i = 1; i < pts.length; i += 1) {
    best = Math.min(best, distToSegment(p, pts[i - 1], pts[i]));
  }
  return best;
}

/** Deterministic pseudo-random in [-1, 1) from an integer seed. */
export function jitter(seed: number): number {
  const s = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return (s - Math.floor(s)) * 2 - 1;
}

/** Snap `to` so the segment from→to lies on a multiple of `stepDeg` degrees. */
export function snapAngle(from: Point, to: Point, stepDeg = 15): Point {
  const d = distance(from, to);
  if (d === 0) return to;
  const ang = Math.atan2(to.y - from.y, to.x - from.x);
  const step = (stepDeg * Math.PI) / 180;
  const snapped = Math.round(ang / step) * step;
  return { x: from.x + Math.cos(snapped) * d, y: from.y + Math.sin(snapped) * d };
}
