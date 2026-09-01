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
import type { CatalogItemResponse } from "@/types/sales-wizard";

import type { BistroInstallationType, DrawTarget, Product, RenderStyle } from "./types";

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

/**
 * Quick-toggle beam spreads for a placed landscape fixture, in degrees.
 *
 * These are the lamp spreads actually stocked for landscape work (pinspot
 * through wide flood), so picking one here is picking the lamp the crew
 * installs — not an arbitrary slider position. Visual only, exactly like
 * `BULB_SIZE_OPTIONS`: the fixture count that reaches the quote is unchanged by
 * the beam it throws.
 */
export interface BeamAngleOption {
  deg: number;
  name: string;
  /** What that spread is for, shown as the chip's tooltip. */
  blurb: string;
}

export const BEAM_ANGLE_OPTIONS: readonly BeamAngleOption[] = [
  { deg: 10, name: "Very narrow", blurb: "Pinspot — a single column or statue" },
  { deg: 15, name: "Narrow spot", blurb: "Tight graze up a wall or a chimney" },
  { deg: 24, name: "Spot", blurb: "Standard accent on a tree or a column" },
  { deg: 36, name: "Flood", blurb: "Washes a facade section or a wide canopy" },
  { deg: 60, name: "Wide flood", blurb: "Broad wash over hardscape or planting" },
];

/** Nearest named beam spread for an angle (for the palette readout). */
export function beamAngleNameFor(deg: number): string {
  let best = BEAM_ANGLE_OPTIONS[0];
  for (const option of BEAM_ANGLE_OPTIONS) {
    if (Math.abs(option.deg - deg) < Math.abs(best.deg - deg)) best = option;
  }
  return best.name;
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
  uplight: [],
  ingrade: [],
  pathlight: [],
  downlight: [],
  walllight: [],
  underwater: [],
  transformer: [],
  wire: [],
  bistro: [12, 18, 24, 36],
  "bistro-pole": [],
};

export const STYLE_LABELS: Record<RenderStyle, string> = {
  c9: "C9 bulbs",
  mini: "Mini lights",
  garland: "Garland",
  stake: "Stake lights",
  wreath: "Wreath",
  treewrap: "Tree wrap",
  permanent: "Permanent track",
  uplight: "Uplight",
  ingrade: "In-grade",
  pathlight: "Path light",
  downlight: "Downlight",
  walllight: "Wall light",
  underwater: "Underwater light",
  transformer: "Transformer",
  wire: "Wire circuit",
  bistro: "Bistro string",
  "bistro-pole": "Bistro support pole",
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
  uplight: 0,
  ingrade: 0,
  pathlight: 0,
  downlight: 0,
  walllight: 0,
  underwater: 0,
  transformer: 0,
  wire: 0,
  bistro: 24,
  "bistro-pole": 0,
};

const ROOFLINE_TARGET: DrawTarget = { field: "roofline" };

/** Product id for the non-measuring outline, used by tests and the palette. */
export const PERMANENT_COSMETIC_PRODUCT_ID = "permanent-cosmetic";

/**
 * Diagram parts for permanent lighting: what the install *looks* like and how
 * it is wired, as opposed to what is billed.
 *
 * Every one targets `annotation`, which `designToEstimateInputs` has no branch
 * for, so none of them can add a foot or a unit to a quote. That is the point:
 * a rep drawing the client's whole roofline for symmetry, or running a jumper
 * between two gables, must not change the price.
 *
 * `cosmetic` deliberately shares the real track's render style and spacing so
 * the client sees one continuous, believable result; the difference is
 * commercial, not visual, and lives in the target.
 */
const PERMANENT_DIAGRAM_PRODUCTS: Product[] = [
  {
    id: PERMANENT_COSMETIC_PRODUCT_ID,
    name: "Cosmetic line (not measured)",
    category: "permanent",
    kind: "linear",
    price: 0,
    style: "permanent",
    colors: COLOR_PRESETS["Warm White"],
    spacingIn: DEFAULT_SPACING.permanent,
    sizeFt: 0,
    bulbScale: DEFAULT_BULB_SCALE,
    target: { field: "annotation", annotationType: "cosmetic" },
  },
  {
    id: "permanent-jumper",
    name: "Jumper wire",
    category: "permanent",
    kind: "linear",
    price: 0,
    style: "wire",
    colors: ["#35aee2"],
    spacingIn: 0,
    sizeFt: 0,
    target: { field: "annotation", annotationType: "jumper" },
  },
  {
    id: "permanent-power-supply",
    name: "Power supply",
    category: "permanent",
    kind: "each",
    price: 0,
    style: "transformer",
    colors: [],
    spacingIn: 0,
    sizeFt: 2,
    target: { field: "annotation", annotationType: "power-supply" },
  },
  {
    id: "permanent-controller",
    name: "Controller",
    category: "permanent",
    kind: "each",
    price: 0,
    style: "transformer",
    colors: [],
    spacingIn: 0,
    sizeFt: 1.5,
    target: { field: "annotation", annotationType: "controller" },
  },
];

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
  const base = categoryKey === "trees" ? 12 : categoryKey === "bushes" ? 4 : 3;
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
export function buildCatalog(estimate: LinearFeetEstimateResult | null | undefined): Product[] {
  const perFt = estimate?.christmas.per_ft ?? 0;
  const products = rooflineProducts(perFt);

  // Permanent LED roofline — offered only when the workspace sells permanent
  // lighting (`permanent.enabled`). Like the warm/multicolor C9 pair, it targets
  // the shared roofline `feet`, so it's another *visual* for the one measured
  // roofline; this derived display hint does not drive server package pricing.
  if (estimate?.permanent?.enabled) {
    products.push({
      id: "roofline-permanent",
      name: "Permanent LED Roofline",
      category: "permanent",
      kind: "linear",
      price:
        estimate.permanent.package_feet > 0
          ? estimate.permanent.total / estimate.permanent.package_feet
          : 0,
      style: "permanent",
      colors: COLOR_PRESETS["Warm White"],
      spacingIn: DEFAULT_SPACING.permanent,
      sizeFt: 0,
      bulbScale: DEFAULT_BULB_SCALE,
      target: ROOFLINE_TARGET,
    });

    // Diagram parts. A permanent quote is sold off a picture of the finished
    // install, so the rep needs to show the run that will not be billed (a
    // cosmetic outline for symmetry), the jumper wire between segments, and
    // where the power supply and controller land. All target `annotation`, so
    // they persist with the drawing and never reach a quote quantity.
    products.push(...PERMANENT_DIAGRAM_PRODUCTS);
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

/**
 * Bistro / festoon strands from the price book. Landscape plans can opt into
 * temporary/permanent variants without changing the catalog SKU used by saved
 * legacy runs. Generic layout tools remain available when the price book has no
 * bistro item, but proposal creation blocks those layout-only quantities.
 */
export function buildBistroCatalog(
  items: readonly CatalogItemResponse[] | null | undefined,
  options: { installationVariants?: boolean } = {},
): Product[] {
  const catalogProducts: Product[] = [];
  for (const item of items ?? []) {
    if (!item.is_active || item.kind === "service") continue;
    const attributes = (item.attributes ?? null) as Record<string, unknown> | null;
    const explicitlyBistro =
      attributes?.bistro_product === true ||
      [attributes?.product_type, attributes?.category, item.service_category].some(
        (value) => typeof value === "string" && value.toLowerCase() === "bistro",
      );
    const name = item.name.toLowerCase();
    const bistroLightingName =
      /\b(bistro|festoon)\b/.test(name) || /\bstring(?:-| )?(lights?|lighting)\b/.test(name);
    if (!explicitlyBistro && !bistroLightingName) continue;
    catalogProducts.push({
      id: `bistro-${item.sku ?? item.id}`,
      name: item.name,
      category: "landscape",
      kind: "linear",
      price: item.unit_price,
      style: "bistro",
      colors: COLOR_PRESETS["Warm White"],
      spacingIn: DEFAULT_SPACING.bistro,
      sizeFt: 0,
      sku: item.sku ?? null,
      catalogItemId: item.id,
      catalogSku: item.sku ?? undefined,
      target: { field: "bistro" },
    });
  }
  if (!options.installationVariants) return catalogProducts;

  const variants = catalogProducts.flatMap((product) => {
    const item = items?.find((candidate) => candidate.id === product.catalogItemId);
    const attributes = (item?.attributes ?? null) as Record<string, unknown> | null;
    const configured = attributes?.bistro_installation_type ?? attributes?.installation_type;
    const name = product.name.toLowerCase();
    const explicitInstallation: BistroInstallationType | null =
      configured === "temporary" || configured === "permanent"
        ? configured
        : /\b(temporary|rental|seasonal)\b/.test(name)
          ? "temporary"
          : /\b(permanent|year[- ]round)\b/.test(name)
            ? "permanent"
            : null;
    const installations: BistroInstallationType[] = explicitInstallation
      ? [explicitInstallation]
      : ["temporary", "permanent"];

    return installations.map((installation) => ({
      ...product,
      id: `bistro-${installation}-${product.sku ?? product.catalogItemId}`,
      name: name.includes(installation)
        ? product.name
        : `${installation === "temporary" ? "Temporary" : "Permanent"} ${product.name}`,
      target: { field: "bistro" as const, installation },
    }));
  });

  const layoutProducts: Product[] = (["temporary", "permanent"] as const).map((installation) => ({
    id: `bistro-${installation}-layout`,
    name: `${installation === "temporary" ? "Temporary" : "Permanent"} Bistro Lights`,
    category: "landscape",
    kind: "linear",
    price: 0,
    style: "bistro",
    colors: COLOR_PRESETS["Warm White"],
    spacingIn: DEFAULT_SPACING.bistro,
    sizeFt: 0,
    sku: null,
    paletteHidden: variants.some((product) => product.target.installation === installation),
    target: { field: "bistro", installation },
  }));

  return [
    ...catalogProducts.map((product) => ({ ...product, paletteHidden: true })),
    ...layoutProducts,
    ...variants,
  ];
}

/** Plan marker attached to a Bistro run; the server owns its per-pole rate. */
export const BISTRO_POLE_PRODUCT: Product = {
  id: "bistro-support-pole",
  name: "Bistro support pole",
  category: "landscape",
  kind: "each",
  price: 0,
  style: "bistro-pole",
  colors: ["#f59e0b"],
  spacingIn: 0,
  sizeFt: 1,
  target: { field: "bistroPole" },
};

/** Keep saved bistro geometry visible if its catalog SKU is later archived or removed. */
export function buildSavedBistroFallbacks(
  productIds: Iterable<string>,
  existingProducts: readonly Product[],
): Product[] {
  const knownIds = new Set(existingProducts.map((product) => product.id));
  const fallbacks: Product[] = [];
  for (const id of productIds) {
    if (!id.startsWith("bistro-") || knownIds.has(id)) continue;
    knownIds.add(id);
    const installation: BistroInstallationType | undefined = id.startsWith("bistro-temporary-")
      ? "temporary"
      : id.startsWith("bistro-permanent-")
        ? "permanent"
        : undefined;
    fallbacks.push({
      id,
      name: installation
        ? `Saved ${installation === "temporary" ? "Temporary" : "Permanent"} Bistro Lights`
        : "Saved Bistro Lights",
      category: "landscape",
      kind: "linear",
      price: 0,
      style: "bistro",
      colors: COLOR_PRESETS["Warm White"],
      spacingIn: DEFAULT_SPACING.bistro,
      sizeFt: 0,
      sku: null,
      paletteHidden: true,
      target: { field: "bistro", installation },
    });
  }
  return fallbacks;
}

/** Index a product list by id for O(1) render/hit-test lookups. */
export function indexProducts(products: readonly Product[]): Map<string, Product> {
  return new Map(products.map((p) => [p.id, p]));
}
