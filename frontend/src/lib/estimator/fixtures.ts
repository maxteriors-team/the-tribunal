/**
 * Landscape fixture **types** — the six things a rep actually draws.
 *
 * A rep standing in a driveway thinks "uplight the columns, path the walk, wall
 * lights at the steps," not a manufacturer configuration string. Drawing by
 * type keeps the palette concise; the customer's chosen **package** then decides
 * which real price-book product each type resolves to, which is what carries the
 * SKU into the quote, inventory, and the technician's parts list.
 *
 * Consequences worth stating plainly:
 * - Switching package re-resolves every drawn fixture. Four uplights become four
 *   of the Best uplight or four of the Good uplight without redrawing anything.
 * - A package that doesn't sell a type can't resolve it. That is surfaced, never
 *   silently dropped or substituted.
 *
 * Pure data + string matching: no canvas, no React, no money.
 */
import type { PricingSettings } from "@/types/sales-wizard";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import { COLOR_PRESETS } from "./catalog";
import type { Product, RenderStyle } from "./types";

/** The six landscape fixture types the palette offers. */
export type FixtureType =
  | "uplight"
  | "ingrade"
  | "pathlight"
  | "downlight"
  | "walllight"
  | "underwater";

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
  {
    type: "walllight",
    label: "Wall light",
    blurb: "Recessed into a wall or step for glare-free transition lighting",
    sizeFt: 8,
  },
  {
    type: "underwater",
    label: "Underwater",
    blurb: "Submersible accent for ponds, fountains, and water features",
    sizeFt: 10,
  },
] as const;

/** Each type renders as its own throw shape on the canvas. */
const TYPE_STYLE: Record<FixtureType, RenderStyle> = {
  uplight: "uplight",
  ingrade: "ingrade",
  pathlight: "pathlight",
  downlight: "downlight",
  walllight: "walllight",
  underwater: "underwater",
};

const SPEC_BY_TYPE = new Map(FIXTURE_TYPES.map((spec) => [spec.type, spec]));

/** Look up a fixture type's spec (label, blurb, default throw). */
export function fixtureSpec(type: FixtureType): FixtureTypeSpec {
  return SPEC_BY_TYPE.get(type) ?? FIXTURE_TYPES[0];
}

/** Identify the package's transformer without mistaking wire or labor for one. */
function isTransformer(item: CatalogItemResponse): boolean {
  return item.attributes?.transformer === true || /\btransformer\b/.test(item.name.toLowerCase());
}

/** Hardware that is not one of the six light-emitting fixture types. */
function isDrawableFixture(item: CatalogItemResponse): boolean {
  if (isTransformer(item)) return false;
  if (item.attributes?.drawable === false) return false;
  if (item.kind === "service") return false;
  return !/\b(wire|cable|controller|hub|labor|permit|trip)\b/.test(item.name.toLowerCase());
}

/**
 * Classify a price-book fixture into one of the six types.
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
  if (/\b(underwater|submersible|pond|fountain)\b/.test(name)) return "underwater";
  if (/\b(wall\s?light|walllight|core[-\s]?drill)\b/.test(name)) return "walllight";
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

export interface ResolvedTransformer {
  item: CatalogItemResponse | null;
  itemId: string | null;
}

export type FixtureResolution = Record<FixtureType, ResolvedFixture>;

export const LANDSCAPE_WIRE_PRODUCT_ID = "landscape-wire";
export const LANDSCAPE_WIRE_GAUGES = [12, 10] as const;

export type QuotedLandscapeWireGauge = (typeof LANDSCAPE_WIRE_GAUGES)[number];

export function landscapeWireLabel(gauge: 8 | 10 | 12 | 14): string {
  return gauge === 10 || gauge === 12 ? `${gauge}/2 AWG` : `${gauge} AWG`;
}

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

  const tier = (pricing?.tiers ?? []).find((t) => t.key === tierKey) ?? (pricing?.tiers ?? [])[0];
  const orderedIds = (tier?.sections ?? []).flatMap((section) => section.item_ids ?? []);

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

/** Resolve the plan's transformer to the product sold by the selected package. */
export function resolveTierTransformer(
  pricing: PricingSettings | null | undefined,
  catalog: readonly CatalogItemResponse[] | null | undefined,
  tierKey: string | null | undefined,
): ResolvedTransformer {
  const byKey = new Map<string, CatalogItemResponse>();
  for (const item of catalog ?? []) {
    if (item.sku) byKey.set(item.sku, item);
    byKey.set(item.id, item);
  }
  const tier =
    (pricing?.tiers ?? []).find((candidate) => candidate.key === tierKey) ??
    (pricing?.tiers ?? [])[0];
  const orderedIds = (tier?.sections ?? []).flatMap((section) => section.item_ids ?? []);
  const item = orderedIds
    .map((id) => byKey.get(id))
    .find((candidate) => candidate?.is_active && isTransformer(candidate));
  return { item: item ?? null, itemId: item ? itemKey(item) : null };
}

function catalogWireGauge(item: CatalogItemResponse): QuotedLandscapeWireGauge | null {
  const attributeGauge = item.attributes?.wire_gauge ?? item.attributes?.gauge;
  const numericGauge =
    typeof attributeGauge === "number"
      ? attributeGauge
      : typeof attributeGauge === "string"
        ? Number.parseInt(attributeGauge, 10)
        : Number.NaN;
  if (numericGauge === 10 || numericGauge === 12) return numericGauge;

  const searchable = `${item.name} ${item.sku ?? ""}`;
  for (const gauge of LANDSCAPE_WIRE_GAUGES) {
    const cableSize = new RegExp(`\\b${gauge}\\s*(?:/|x|-)\\s*2\\b`, "i");
    if (cableSize.test(searchable) && /\b(?:wire|cable)\b/i.test(searchable)) return gauge;
  }
  return null;
}

/** Resolve a per-foot 12/2 or 10/2 wire item carried by one proposal tier. */
export function resolveTierWire(
  pricing: PricingSettings | null | undefined,
  catalog: readonly CatalogItemResponse[] | null | undefined,
  tierKey: string | null | undefined,
  gauge: QuotedLandscapeWireGauge,
): CatalogItemResponse | null {
  const byKey = new Map<string, CatalogItemResponse>();
  for (const item of catalog ?? []) {
    if (item.sku) byKey.set(item.sku, item);
    byKey.set(item.id, item);
  }
  const tier =
    (pricing?.tiers ?? []).find((candidate) => candidate.key === tierKey) ??
    (pricing?.tiers ?? [])[0];
  const orderedIds = (tier?.sections ?? []).flatMap((section) => section.item_ids ?? []);
  return (
    orderedIds
      .map((id) => byKey.get(id))
      .find((item) => item?.is_active && catalogWireGauge(item) === gauge) ?? null
  );
}

function isLampComponent(
  component: NonNullable<CatalogItemResponse["components"]>[number],
): boolean {
  return /(^|\b)(lamp|bulb|mr\d{2}|led)(\b|$)/i.test(
    `${component.sku ?? ""} ${component.description ?? ""}`,
  );
}

function isSelfComponent(
  item: CatalogItemResponse | null,
  component: NonNullable<CatalogItemResponse["components"]>[number],
): boolean {
  const itemSku = item?.sku?.trim().toLowerCase();
  const componentSku = component.sku?.trim().toLowerCase();
  return Boolean(itemSku && componentSku && itemSku === componentSku);
}

function fixtureLampLabel(item: CatalogItemResponse | null): string | null {
  const attributes = item?.attributes ?? {};
  const lamp = attributes.lamp ?? attributes.lamp_type ?? attributes.color_temperature;
  if (typeof lamp === "string" && lamp.trim()) return lamp.trim();
  const component = (item?.components ?? []).find(
    (candidate) => !isSelfComponent(item, candidate) && isLampComponent(candidate),
  );
  return component?.description?.trim() || component?.sku?.trim() || null;
}

function fixtureAccessoryLabels(item: CatalogItemResponse | null): string[] {
  return (item?.components ?? []).flatMap((component) => {
    if (isSelfComponent(item, component) || isLampComponent(component)) return [];
    const description = component.description?.trim();
    const sku = component.sku?.trim();
    const label = description || sku;
    return label ? [label] : [];
  });
}

/** Whether the workspace has any landscape fixtures to draw at all. */
export function hasLandscapeFixtures(resolution: FixtureResolution): boolean {
  return FIXTURE_TYPES.some((spec) => resolution[spec.type].item !== null);
}

/**
 * The landscape palette: six light-emitting fixture types plus a transformer
 * plan symbol. Prices are display hints only; transformer placement is an
 * annotation and does not alter quote quantities.
 */
export function buildFixturePalette(
  resolution: FixtureResolution,
  transformer: ResolvedTransformer = { item: null, itemId: null },
): Product[] {
  const fixtures = FIXTURE_TYPES.map((spec) => {
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
      productName: resolved.item?.name ?? null,
      sku: resolved.itemId,
      catalogItemId: resolved.item?.id,
      catalogSku: resolved.item?.sku ?? undefined,
      lampLabel: fixtureLampLabel(resolved.item),
      accessoryLabels: fixtureAccessoryLabels(resolved.item),
      target: { field: "landscape" as const, fixtureType: spec.type },
    };
  });
  return [
    ...fixtures,
    {
      id: "fixture-transformer",
      name: "Transformer",
      category: "landscape" as const,
      kind: "each" as const,
      price: transformer.item?.unit_price ?? 0,
      style: "transformer" as const,
      colors: [],
      spacingIn: 0,
      sizeFt: 3,
      productName: transformer.item?.name ?? null,
      sku: transformer.itemId,
      catalogItemId: transformer.item?.id,
      catalogSku: transformer.item?.sku ?? undefined,
      lampLabel: null,
      accessoryLabels: fixtureAccessoryLabels(transformer.item),
      target: { field: "annotation" as const, annotationType: "transformer" as const },
    },
    {
      id: LANDSCAPE_WIRE_PRODUCT_ID,
      name: "Wire circuit",
      category: "landscape" as const,
      kind: "linear" as const,
      price: 0,
      style: "wire" as const,
      colors: ["#35aee2"],
      spacingIn: 0,
      sizeFt: 0,
      productName: null,
      sku: null,
      lampLabel: null,
      accessoryLabels: [],
      target: { field: "annotation" as const, annotationType: "wire" as const },
    },
  ];
}
