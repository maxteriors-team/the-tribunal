/**
 * Design-domain types for the Holiday-Home-Concepts-style light designer.
 *
 * The rep draws **runs** (linear light strands — C9 roofline, mini lights,
 * garland) and places **items** (wreaths, wrapped trees/bushes) directly on a
 * photo, after setting a photo **calibration** from a known measurement. These
 * types are pure data (no canvas, no React) so the render engine, geometry, the
 * design→estimate mapper, and the editor all share one shape.
 *
 * `Point` (pixel coordinate in image space) is reused from `measure.ts` so the
 * new designer and the existing measurement math never diverge.
 */
import type { Point } from "./measure";

export type { Point };

/** Linear products are traced (priced per foot); each products are placed (priced per unit). */
export type ProductKind = "linear" | "each";

/** Which product line a drawable belongs to (groups the palette). */
export type Mode = "seasonal" | "permanent" | "landscape";

/**
 * How a product's lights are rendered on the canvas.
 *
 * The first block is holiday strand/decor work; the second is landscape
 * lighting, where a fixture throws a beam or a pool of light rather than
 * hanging bulbs. The four landscape styles are exactly the four fixture types
 * the palette offers (see `fixtures.ts`), so what a rep draws reads on the photo
 * the way that fixture actually throws light.
 */
export type RenderStyle =
  | "c9"
  | "mini"
  | "garland"
  | "stake"
  | "wreath"
  | "treewrap"
  | "permanent"
  | "uplight"
  | "ingrade"
  | "pathlight"
  | "downlight"
  | "bistro";

/** Landscape fixture styles — placed, and rendered as a beam or a light pool. */
export const LANDSCAPE_STYLES = [
  "uplight",
  "ingrade",
  "pathlight",
  "downlight",
] as const satisfies readonly RenderStyle[];

/** Whether a style is a landscape fixture (vs a strand or a decor item). */
export function isLandscapeStyle(style: RenderStyle): boolean {
  return (LANDSCAPE_STYLES as readonly RenderStyle[]).includes(style);
}

/**
 * Landscape styles that throw a **cone** and therefore have a beam angle. A path
 * light pools light on the ground rather than aiming a beam, so its spread is
 * its pool diameter (the throw) and it is deliberately absent here.
 */
export const BEAM_STYLES = [
  "uplight",
  "ingrade",
  "downlight",
] as const satisfies readonly RenderStyle[];

export type BeamStyle = (typeof BEAM_STYLES)[number];

/**
 * Default beam spread in degrees per fixture type — the lamp a package ships
 * with by default. These are the standard landscape-lamp spreads (a narrow-spot
 * in-grade grazing a wall, a spot uplight on a column, a flood washing down from
 * a soffit), so the number a rep edits is the one printed on the lamp box.
 */
export const DEFAULT_BEAM_ANGLE_DEG: Record<BeamStyle, number> = {
  ingrade: 15,
  uplight: 30,
  downlight: 36,
};

/** Spread limits: narrower than a pinspot / wider than a wall wash is not a lamp. */
export const MIN_BEAM_ANGLE_DEG = 5;
export const MAX_BEAM_ANGLE_DEG = 120;

/** Whether a style throws an editable beam (vs a ground pool or a strand). */
export function hasBeamAngle(style: RenderStyle): style is BeamStyle {
  return (BEAM_STYLES as readonly RenderStyle[]).includes(style);
}

export function clampBeamAngle(deg: number): number {
  if (!Number.isFinite(deg)) return MIN_BEAM_ANGLE_DEG;
  return Math.min(Math.max(deg, MIN_BEAM_ANGLE_DEG), MAX_BEAM_ANGLE_DEG);
}

/**
 * The spread a fixture actually renders at: the item's own override when the rep
 * has tuned it, else the type's default lamp. `null` for anything that doesn't
 * throw a cone, so callers can't accidentally give a path light a beam.
 */
export function beamAngleFor(
  style: RenderStyle,
  override?: number | null,
): number | null {
  if (!hasBeamAngle(style)) return null;
  return clampBeamAngle(override ?? DEFAULT_BEAM_ANGLE_DEG[style]);
}

/**
 * Where a drawn product's measured quantity lands in the server estimate
 * request. The canvas only produces feet/counts; every dollar is still computed
 * server-side, so a product just declares its destination:
 *
 * - `roofline` → the request's top-level `feet` (drives BOTH the permanent and
 *   seasonal roofline sides of the comparison).
 * - `christmas` → `christmas_items[category][option]` (linear feet for `per_ft`
 *   categories like mini-lights/garland, a count for `each` categories like
 *   trees/bushes/wreaths).
 * - `landscape` → a count of one fixture *type* (uplight / in-grade / path /
 *   downlight). The customer's chosen package resolves the type to a real
 *   price-book product, so the quote gets the right SKU and the crew gets its
 *   parts list — and switching package re-resolves without redrawing.
 * - `bistro` → linear feet of string lighting for the wizard's bistro add-on.
 */
export type DrawTarget =
  | { field: "roofline" }
  | { field: "christmas"; category: string; option: string }
  | { field: "landscape"; fixtureType: string }
  | { field: "bistro" };

export interface Product {
  id: string;
  name: string;
  category: Mode;
  kind: ProductKind;
  /**
   * Net unit rate for palette display only ($/ft for linear, $/ea for each).
   * Sourced from the server's pricing config (catalog option price / estimate
   * per-ft) — a display hint, never used to compute a total on the client.
   */
  price: number;
  style: RenderStyle;
  /** Bulb colors, cycled along the run. */
  colors: string[];
  /** Bulb spacing in inches (linear styles only). */
  spacingIn: number;
  /** Default rendered size in feet for placed items (wreath diameter, tree height…). */
  sizeFt: number;
  /**
   * Visual bulb-radius multiplier for linear styles (Small…Jumbo). Optional so
   * existing product literals stay valid; the render engine defaults it to 1.
   * Purely cosmetic — never affects the measured feet or the server price.
   */
  bulbScale?: number;
  /**
   * Price-book SKU this entry resolves to under the current package — the same
   * stable key the wizard and the fulfillment sheet use, so a fixture drawn on
   * the photo is traceable to inventory and the technician's parts list. Null
   * when the package doesn't sell the type; absent for holiday products, which
   * are priced from the pricing config rather than the catalog.
   */
  sku?: string | null;
  /**
   * The resolved product's own name (“ZDC Color Uplight”) shown under the type
   * label, so the rep can see what the package actually installs.
   */
  productName?: string | null;
  target: DrawTarget;
}

export interface Run {
  id: string;
  productId: string;
  points: Point[];
  /** Per-run overrides — fall back to the product's values when unset. */
  spacingIn?: number;
  colors?: string[];
  /** Per-run bulb-size multiplier (visual only); falls back to the product's. */
  bulbScale?: number;
}

export interface PlacedItem {
  id: string;
  productId: string;
  at: Point;
  /** Rendered size (diameter / height) in image pixels. */
  sizePx: number;
  /**
   * Per-fixture beam spread in degrees, overriding the type's default lamp
   * (see `DEFAULT_BEAM_ANGLE_DEG`). Optional so existing designs stay valid, and
   * ignored for styles that throw no cone. Changes what the customer sees on the
   * photo — a 15° graze up a column versus a 60° wash — and never the count, so
   * the quantity that reaches the quote is untouched.
   */
  beamAngleDeg?: number;
}

export interface Calibration {
  a: Point;
  b: Point;
  feet: number;
}

export interface Design {
  calibration: Calibration | null;
  runs: Run[];
  items: PlacedItem[];
}

export type Tool =
  | { type: "select" }
  | { type: "calibrate" }
  | { type: "draw"; productId: string }
  | { type: "place"; productId: string };

export type Selection = { kind: "run" | "item"; id: string } | null;

/** A loaded house photo: its data URL plus intrinsic pixel dimensions. */
export interface PhotoInfo {
  dataUrl: string;
  width: number;
  height: number;
}
