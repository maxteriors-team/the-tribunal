/**
 * One distinct icon + tint per seasonal product type, shared by every surface
 * that shows a customer their options (the quote builder rows, the canvas
 * palette). Keeping the mapping here means a wreath reads the same — a gold ring
 * — whether the rep is drawing on a photo or scanning the priced quote, so
 * customers recognize "60 in wreath" vs "large tree" at a glance.
 *
 * Tints are muted festive hues chosen to stay legible on both the light app
 * palette and the wizard's dark, gold-accented surface. They are not brand
 * truth — just consistent, distinguishable type markers.
 */
import {
  Cable,
  CircleDashed,
  Lightbulb,
  Shrub,
  Sparkles,
  Spline,
  TreePine,
  type LucideIcon,
} from "lucide-react";

import type { RenderStyle } from "./types";

export interface SeasonalIconSpec {
  /** Lucide glyph for this product type. */
  Icon: LucideIcon;
  /** Icon stroke color; also drives a translucent tile background. */
  tint: string;
  /** Human label for the type (accessible name / tooltip). */
  label: string;
}

/** Semantic product types a seasonal option can map to. */
type SeasonalKind =
  | "roofline"
  | "mini"
  | "garland"
  | "tree"
  | "bush"
  | "wreath"
  | "permanent";

const SPECS: Record<SeasonalKind, SeasonalIconSpec> = {
  roofline: { Icon: Lightbulb, tint: "#f4a72c", label: "Roofline C9 bulbs" },
  mini: { Icon: Sparkles, tint: "#5aa2ff", label: "Mini lights" },
  garland: { Icon: Spline, tint: "#c8792e", label: "Garland" },
  tree: { Icon: TreePine, tint: "#3fa66a", label: "Tree" },
  bush: { Icon: Shrub, tint: "#8bbf4d", label: "Bush / shrub" },
  wreath: { Icon: CircleDashed, tint: "#d9a441", label: "Wreath" },
  permanent: { Icon: Cable, tint: "#8ea0b5", label: "Permanent track" },
};

const FALLBACK = SPECS.roofline;

/** Map a workspace decor category key (`wreaths`, `trees`, …) to its icon. */
const CATEGORY_KIND: Record<string, SeasonalKind> = {
  trees: "tree",
  bushes: "bush",
  wreaths: "wreath",
  mini_lights: "mini",
  garland: "garland",
  roofline: "roofline",
};

/** Map a canvas render style to its icon. */
const STYLE_KIND: Record<RenderStyle, SeasonalKind> = {
  c9: "roofline",
  mini: "mini",
  garland: "garland",
  stake: "mini",
  wreath: "wreath",
  treewrap: "tree",
  permanent: "permanent",
};

/** Icon spec for a workspace decor category key. Falls back to roofline. */
export function seasonalIconForCategory(categoryKey: string): SeasonalIconSpec {
  return SPECS[CATEGORY_KIND[categoryKey] ?? "roofline"] ?? FALLBACK;
}

/** Icon spec for a canvas render style. Falls back to roofline. */
export function seasonalIconForStyle(style: RenderStyle): SeasonalIconSpec {
  return SPECS[STYLE_KIND[style] ?? "roofline"] ?? FALLBACK;
}

/** A ~13%-alpha version of a tint hex, for icon-tile backgrounds. */
export function tintSurface(tint: string): string {
  return `${tint}22`;
}
