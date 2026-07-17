/**
 * Drawable-product catalog for the light designer.
 *
 * The palette a rep draws from is derived from the workspace's live pricing
 * config — never hard-coded money. `buildCatalog` merges two sources:
 *
 * 1. **Built-in roofline C9** (warm + multicolor) — the one product that maps to
 *    the estimate request's top-level `feet`, driving BOTH the permanent and
 *    seasonal roofline sides of the comparison. Its display rate comes from the
 *    server estimate (`christmas.per_ft`).
 * 2. **The workspace `christmas_catalog`** (returned by the estimate endpoint) —
 *    every seasonal decor category becomes drawable: `per_ft` categories
 *    (mini-lights, garland) are traced; `each` categories (trees, bushes,
 *    wreaths) are placed. Each option carries its net rate for palette display.
 *
 * `COLOR_PRESETS` / `SPACING_OPTIONS` are the per-run styling choices, shared
 * with the tool palette.
 */
import type { LinearFeetEstimateResult } from "@/types/estimate";

import type { DrawTarget, Product, RenderStyle } from "./types";

export const COLOR_PRESETS: Record<string, string[]> = {
  "Warm White": ["#ffd98a"],
  "Cool White": ["#eaf6ff"],
  Multicolor: ["#ff5252", "#54ff77", "#5aa2ff", "#ffd24f", "#ff5ad8"],
  "Red & White": ["#ff5252", "#ffd98a"],
  "Red & Green": ["#ff5252", "#54ff77"],
  "Blue & White": ["#5aa2ff", "#eaf6ff"],
  "All Red": ["#ff5252"],
  "All Blue": ["#5aa2ff"],
  Halloween: ["#ff8c1a", "#a64dff"],
  Patriotic: ["#ff5252", "#eaf6ff", "#5aa2ff"],
};

export function presetNameFor(colors: readonly string[]): string {
  for (const [name, c] of Object.entries(COLOR_PRESETS)) {
    if (c.length === colors.length && c.every((v, i) => v === colors[i])) {
      return name;
    }
  }
  return "Warm White";
}

/**
 * Named bulb-size choices → a visual radius multiplier for linear runs. Purely
 * cosmetic, exactly like `COLOR_PRESETS` / `SPACING_OPTIONS`: the measured
 * footage and every server-computed dollar are unaffected, so a rep can show a
 * customer C9 vs jumbo bulbs without changing the price.
 */
export const BULB_SIZE_OPTIONS: Record<string, number> = {
  Small: 0.75,
  Standard: 1,
  Large: 1.3,
  Jumbo: 1.6,
};

/** Default bulb-size multiplier when a product/run doesn't specify one. */
export const DEFAULT_BULB_SCALE = 1;

/** Nearest named bulb size for a scale (defaults to Standard). */
export function bulbSizeNameFor(scale: number): string {
  let best = "Standard";
  let bestDelta = Infinity;
  for (const [name, s] of Object.entries(BULB_SIZE_OPTIONS)) {
    const delta = Math.abs(s - scale);
    if (delta < bestDelta) {
      best = name;
      bestDelta = delta;
    }
  }
  return best;
}

/** Quick-toggle bulb spacing choices per light style (inches). */
export const SPACING_OPTIONS: Record<RenderStyle, number[]> = {
  c9: [9, 12, 15, 18],
  mini: [3, 4, 6],
  garland: [6, 8, 12],
  stake: [18, 24, 30, 36],
  wreath: [],
  treewrap: [],
  permanent: [6, 9, 12],
};

export const STYLE_LABELS: Record<RenderStyle, string> = {
  c9: "C9 bulbs",
  mini: "Mini lights",
  garland: "Garland",
  stake: "Stake lights",
  wreath: "Wreath",
  treewrap: "Tree wrap",
  permanent: "Permanent track",
};

/** Default bulb spacing (inches) when a linear product first renders. */
const DEFAULT_SPACING: Record<RenderStyle, number> = {
  c9: 12,
  mini: 4,
  garland: 8,
  stake: 30,
  wreath: 0,
  treewrap: 0,
  permanent: 9,
};

const ROOFLINE_TARGET: DrawTarget = { field: "roofline" };

/** Built-in C9 roofline products. `perFt` is the server display rate. */
function rooflineProducts(perFt: number): Product[] {
  const base = {
    category: "seasonal" as const,
    kind: "linear" as const,
    price: perFt,
    style: "c9" as const,
    spacingIn: DEFAULT_SPACING.c9,
    sizeFt: 0,
    bulbScale: DEFAULT_BULB_SCALE,
    target: ROOFLINE_TARGET,
  };
  return [
    {
      ...base,
      id: "roofline-c9-warm",
      name: "C9 Roofline — Warm White",
      colors: COLOR_PRESETS["Warm White"],
    },
    {
      ...base,
      id: "roofline-c9-multi",
      name: "C9 Roofline — Multicolor",
      colors: COLOR_PRESETS.Multicolor,
    },
  ];
}

/** Map a decor category key → how its lights render on the canvas. */
const CATEGORY_STYLE: Record<string, RenderStyle> = {
  mini_lights: "mini",
  garland: "garland",
  wreaths: "wreath",
  trees: "treewrap",
  bushes: "treewrap",
};

function styleForCategory(key: string, unit: "each" | "per_ft"): RenderStyle {
  return CATEGORY_STYLE[key] ?? (unit === "per_ft" ? "mini" : "wreath");
}

/**
 * Default rendered size (feet) for a placed decor item. The rep can resize on
 * canvas, so this is only a sensible starting scale keyed off the category and
 * any small/medium/large hint in the option.
 */
function sizeFtFor(categoryKey: string, optionKey: string, optionName: string): number {
  const base =
    categoryKey === "trees" ? 12 : categoryKey === "bushes" ? 4 : 3;
  const hint = `${optionKey} ${optionName}`.toLowerCase();
  if (/\b(large|xl|tall|over)\b/.test(hint)) return base * 1.4;
  if (/\b(small|mini|up to)\b/.test(hint)) return base * 0.7;
  return base;
}

/**
 * Build the drawable palette from the current server estimate. Works with a
 * feet=0 estimate (no design yet) since `christmas_catalog` is returned
 * regardless of measured footage.
 */
export function buildCatalog(
  estimate: LinearFeetEstimateResult | null | undefined,
): Product[] {
  const perFt = estimate?.christmas.per_ft ?? 0;
  const products = rooflineProducts(perFt);

  // Permanent LED roofline — offered only when the workspace sells permanent
  // lighting (`permanent.enabled`). Like the warm/multicolor C9 pair, it targets
  // the shared roofline `feet`, so it's another *visual* for the one measured
  // roofline; its per-ft rate is priced server-side (display hint only here).
  if (estimate?.permanent?.enabled) {
    products.push({
      id: "roofline-permanent",
      name: "Permanent LED Roofline",
      category: "permanent",
      kind: "linear",
      price: estimate.permanent.per_ft,
      style: "permanent",
      colors: COLOR_PRESETS["Warm White"],
      spacingIn: DEFAULT_SPACING.permanent,
      sizeFt: 0,
      bulbScale: DEFAULT_BULB_SCALE,
      target: ROOFLINE_TARGET,
    });
  }

  for (const cat of estimate?.christmas_catalog ?? []) {
    const style = styleForCategory(cat.key, cat.unit);
    const kind = cat.unit === "per_ft" ? "linear" : "each";
    for (const opt of cat.options ?? []) {
      products.push({
        id: `cat-${cat.key}-${opt.key}`,
        name: opt.name,
        category: "seasonal",
        kind,
        price: opt.price,
        style,
        colors: COLOR_PRESETS["Warm White"],
        spacingIn: DEFAULT_SPACING[style],
        sizeFt: kind === "each" ? sizeFtFor(cat.key, opt.key, opt.name) : 0,
        bulbScale: DEFAULT_BULB_SCALE,
        target: { field: "christmas", category: cat.key, option: opt.key },
      });
    }
  }
  return products;
}

/** Index a product list by id for O(1) render/hit-test lookups. */
export function indexProducts(products: readonly Product[]): Map<string, Product> {
  return new Map(products.map((p) => [p.id, p]));
}
