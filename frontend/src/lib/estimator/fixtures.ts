/**
 * Landscape fixture **types** — the four things a rep actually draws.
 *
 * A rep standing in a driveway thinks "uplight the columns, path the walk," not
 * "ZDC Modern Color Path Light Black." Drawing by type keeps the palette to four
 * choices; the customer's chosen **package** (Good / Better / Best) then decides
 * which real price-book product each type resolves to, which is what carries the
 * SKU into the quote, inventory, and the technician's parts list.
 *
 * Consequences worth stating plainly:
 * - Switching package re-resolves every drawn fixture. Four uplights become four
 *   of the Best uplight or four of the Good uplight without redrawing anything.
 * - A package that doesn't sell a type (the Good package has no downlight) can't
 *   resolve it. That is surfaced, never silently dropped or substituted.
 *
 * Pure data + string matching: no canvas, no React, no money.
 */
import type { PricingSettings } from "@/types/sales-wizard";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import { COLOR_PRESETS } from "./catalog";
import type { Product, RenderStyle } from "./types";

/** The four landscape fixture types the palette offers. */
export type FixtureType = "uplight" | "ingrade" | "pathlight" | "downlight";

export interface FixtureTypeSpec {
  type: FixtureType;
  label: string;
  /** What the fixture does, for the palette tooltip. */
  blurb: string;
  /** Default throw in feet (beam length, or pool diameter for path lights). */
  sizeFt: number;
}

export const FIXTURE_TYPES: readonly FixtureTypeSpec[] = [
  {
    type: "uplight",
    label: "Uplight",
    blurb: "Grazes a facade, column, or tree from the ground",
    sizeFt: 14,
  },
  {
    type: "ingrade",
    label: "In-grade",
    blurb: "Flush well light — a tight beam with nothing visible by day",
    sizeFt: 16,
  },
  {
    type: "pathlight",
    label: "Path light",
    blurb: "Pools light on a walkway, drive, or bed edge",
    sizeFt: 7,
  },
  {
    type: "downlight",
    label: "Downlight",
    blurb: "Mounted high, washes light down over hardscape or planting",
    sizeFt: 12,
  },
] as const;

/** Each type renders as its own throw shape on the canvas. */
const TYPE_STYLE: Record<FixtureType, RenderStyle> = {
  uplight: "uplight",
  ingrade: "ingrade",
  pathlight: "pathlight",
  downlight: "downlight",
};

const SPEC_BY_TYPE = new Map(FIXTURE_TYPES.map((spec) => [spec.type, spec]));

/** Look up a fixture type's spec (label, blurb, default throw). */
export function fixtureSpec(type: FixtureType): FixtureTypeSpec {
  return SPEC_BY_TYPE.get(type) ?? FIXTURE_TYPES[0];
}

/**
 * Hardware a rep never draws on a photo: transformers, wire, controllers, and
 * billable services. Excluded so the palette only ever resolves to things that
 * make light.
 */
function isDrawableFixture(item: CatalogItemResponse): boolean {
  if (item.attributes?.transformer === true) return false;
  if (item.attributes?.drawable === false) return false;
  if (item.kind === "service") return false;
  return !/\b(transformer|wire|cable|controller|hub|labor|permit|trip)\b/.test(
    item.name.toLowerCase(),
  );
}

/**
 * Classify a price-book fixture into one of the four types.
 *
 * Matching reads the operator's own product names, so no new per-item config is
 * required to adopt this. An explicit `attributes.fixture_type` always wins —
 * the escape hatch for a product named after a model number.
 */
export function classifyFixture(item: {
  name: string;
  attributes?: Record<string, unknown> | null;
}): FixtureType | null {
  const explicit = item.attributes?.fixture_type;
  if (typeof explicit === "string" && SPEC_BY_TYPE.has(explicit as FixtureType)) {
    return explicit as FixtureType;
  }
  const name = item.name.toLowerCase();
  // In-grade first: a "well light" is an in-ground fixture that also aims up,
  // so it must not be swept into the generic uplight bucket.
  if (/\b(in-?grade|well)\b/.test(name)) return "ingrade";
  // "Path light" and "Pathway Light" are both path lights.
  if (/\bpath(?:way)?\b/.test(name)) return "pathlight";
  if (/\b(down\s?light|downlight|wash|flood|hardscape|step)\b/.test(name)) {
    return "downlight";
  }
  if (/\b(up\s?light|uplight|accent|spot|narrow|bullet|graze)\b/.test(name)) {
    return "uplight";
  }
  return null;
}

/** The price-book product a type resolves to inside one package. */
export interface ResolvedFixture {
  type: FixtureType;
  /** Price-book item, or null when this package doesn't sell the type. */
  item: CatalogItemResponse | null;
  /** Stable key the wizard and fulfillment sheet use (the item's SKU). */
  itemId: string | null;
}

export type FixtureResolution = Record<FixtureType, ResolvedFixture>;

/** Stable id the wizard keys quantities on (mirrors `QuoteService`'s lookup). */
function itemKey(item: CatalogItemResponse): string {
  return item.sku || item.id;
}

/**
 * Resolve every fixture type against one package's product list.
 *
 * The tier's `sections[].item_ids` are the SKUs that package includes, in the
 * operator's own order — so the first drawable match for a type is that
 * package's representative product for it. A type with no match resolves to
 * null rather than borrowing a product from another package.
 */
export function resolveTierFixtures(
  pricing: PricingSettings | null | undefined,
  catalog: readonly CatalogItemResponse[] | null | undefined,
  tierKey: string | null | undefined,
): FixtureResolution {
  const byKey = new Map<string, CatalogItemResponse>();
  for (const item of catalog ?? []) {
    if (item.sku) byKey.set(item.sku, item);
    byKey.set(item.id, item);
  }

  const tier =
    (pricing?.tiers ?? []).find((t) => t.key === tierKey) ??
    (pricing?.tiers ?? [])[0];
  const orderedIds = (tier?.sections ?? []).flatMap(
    (section) => section.item_ids ?? [],
  );

  const resolution = Object.fromEntries(
    FIXTURE_TYPES.map((spec) => [
      spec.type,
      { type: spec.type, item: null, itemId: null } as ResolvedFixture,
    ]),
  ) as FixtureResolution;

  for (const id of orderedIds) {
    const item = byKey.get(id);
    if (!item || !item.is_active || !isDrawableFixture(item)) continue;
    const type = classifyFixture(item);
    if (!type || resolution[type].item) continue;
    resolution[type] = { type, item, itemId: itemKey(item) };
  }
  return resolution;
}

/** Whether the workspace has any landscape fixtures to draw at all. */
export function hasLandscapeFixtures(resolution: FixtureResolution): boolean {
  return FIXTURE_TYPES.some((spec) => resolution[spec.type].item !== null);
}

/**
 * The landscape half of the drawable palette: one entry per fixture type,
 * annotated with the product the current package resolves it to. Prices are the
 * catalog's net rate for display only — the server still prices the quote.
 */
export function buildFixturePalette(resolution: FixtureResolution): Product[] {
  return FIXTURE_TYPES.map((spec) => {
    const resolved = resolution[spec.type];
    return {
      id: `fixture-${spec.type}`,
      name: spec.label,
      category: "landscape" as const,
      kind: "each" as const,
      price: resolved.item?.unit_price ?? 0,
      style: TYPE_STYLE[spec.type],
      colors: COLOR_PRESETS["Warm White"],
      spacingIn: 0,
      sizeFt: spec.sizeFt,
      // The product this package actually installs for the type, so the rep can
      // see (and the crew can pull) the real SKU behind a drawn light.
      productName: resolved.item?.name ?? null,
      sku: resolved.itemId,
      target: { field: "landscape" as const, fixtureType: spec.type },
    };
  });
}
