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

/** Which estimator surface a product belongs to. Phase 1 draws `seasonal` only. */
export type Mode = "seasonal" | "permanent";

/** How a product's lights are rendered on the canvas. */
export type RenderStyle =
  | "c9"
  | "mini"
  | "garland"
  | "stake"
  | "wreath"
  | "treewrap"
  | "permanent";

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
 */
export type DrawTarget =
  | { field: "roofline" }
  | { field: "christmas"; category: string; option: string };

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
  target: DrawTarget;
}

export interface Run {
  id: string;
  productId: string;
  points: Point[];
  /** Per-run overrides — fall back to the product's values when unset. */
  spacingIn?: number;
  colors?: string[];
}

export interface PlacedItem {
  id: string;
  productId: string;
  at: Point;
  /** Rendered size (diameter / height) in image pixels. */
  sizePx: number;
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
