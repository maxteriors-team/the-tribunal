/**
 * Exact wrap geometry for placed trees and bushes.
 *
 * The seasonal price book quotes a tree by size band (small / medium / large),
 * which is fast but blind: a 20 ft spruce and a 12 ft pear can land in the same
 * band and take wildly different amounts of light. This module computes the
 * real wire length a spiral wrap needs, so a rep can price the tree in front of
 * them instead of the nearest band.
 *
 * It is **opt-in per item**. An item without a `wrap` spec keeps band pricing
 * exactly as before. An item with one drops its band count and bills from this
 * math instead — but only once it is genuinely billable: measured, priced, and
 * within the server's limits. `isBilledByWrap` is the single question both
 * paths ask, so a tree is charged exactly once, never twice and never free.
 *
 * Pure geometry — no DOM, no money beyond multiplying the rep's own entered
 * rate. Ported from the standalone Tree Light Quoter calculator.
 */
import type { EstimateCustomLine } from "@/types/estimate";

import type { Design, PlacedItem, Product } from "./types";

const TAU = Math.PI * 2;
const INCHES_PER_FOOT = 12;

/** Shapes that a spiral wrap is computed for. */
export const WRAP_SHAPES = ["evergreen", "deciduous", "trunk", "branch", "bush"] as const;
export type WrapShape = (typeof WRAP_SHAPES)[number];

/** How the lights are sold: by covered length, or by bulb along the wire. */
export const WRAP_LIGHT_TYPES = ["mini", "c7", "c9", "garland"] as const;
export type WrapLightType = (typeof WRAP_LIGHT_TYPES)[number];

/** Bulbs sit at a spacing along the wire; strands and garland cover a length. */
const UNIT_KIND: Record<WrapLightType, "strand" | "bulb" | "section"> = {
  mini: "strand",
  c7: "bulb",
  c9: "bulb",
  garland: "section",
};

export const WRAP_SHAPE_LABELS: Record<WrapShape, string> = {
  evergreen: "Evergreen tree",
  deciduous: "Deciduous tree",
  trunk: "Tree trunk",
  branch: "Branches",
  bush: "Bush",
};

export const WRAP_LIGHT_TYPE_LABELS: Record<WrapLightType, string> = {
  mini: "Mini lights",
  c7: "C7 bulbs",
  c9: "C9 bulbs",
  garland: "Garland",
};

/**
 * The rep's exact-measure entry for one placed item.
 *
 * Every field is a plain number in the unit a rep thinks in (feet, inches), so
 * a saved design stays readable and re-priceable years later. Dimensions the
 * chosen shape does not use are ignored rather than rejected, so switching
 * shape on a half-filled form never throws away typing.
 */
export interface WrapSpec {
  shape: WrapShape;
  lightType: WrapLightType;
  /** Lit height in feet — how far up the item actually gets wrapped. */
  heightFt: number;
  /** Vertical gap between wrap rows, in inches. */
  rowSpacingIn: number;
  /** Canopy or base radius, feet. Evergreen and deciduous only. */
  radiusFt?: number;
  /** Trunk width straight across, inches. Trunk only. */
  trunkWidthIn?: number;
  /** Typical limb thickness, inches. Branch only. */
  branchWidthIn?: number;
  /** How many limbs get wrapped. Branch only. */
  branchCount?: number;
  /** Bush footprint, feet. Bush only. */
  widthFt?: number;
  depthFt?: number;
  /** Feet one mini strand or garland section covers. */
  feetPerUnit?: number;
  /** Bulb spacing along the wire, inches. C7 / C9 only. */
  bulbSpacingIn?: number;
  /** Charge per strand/bulb/section, or per measured foot. */
  pricingMode: "unit" | "foot";
  /** The rep's client-facing rate for one unit, or one foot. */
  unitPrice?: number;
}

export interface WrapResult {
  /** Whole feet of wire the wrap needs — the billable footage. */
  plannedFeet: number;
  /** Wrap rows up the item at the chosen spacing. */
  rowCount: number;
  /** Strands, bulbs, or sections; null until a size is entered. */
  unitCount: number | null;
  unitKind: "strand" | "bulb" | "section";
  /** What the line is billed by: units, or measured feet. */
  billedQuantity: number | null;
  /** Client-facing amount, or null while the rate is missing. */
  price: number | null;
}

/** Every dimension a shape needs, so the UI can ask for exactly those. */
export const WRAP_SHAPE_FIELDS: Record<WrapShape, readonly (keyof WrapSpec)[]> = {
  evergreen: ["radiusFt"],
  deciduous: ["radiusFt"],
  trunk: ["trunkWidthIn"],
  branch: ["branchWidthIn", "branchCount"],
  bush: ["widthFt", "depthFt"],
};

/** Branches and bushes are wrapped by hand with minis; bulb cord is not. */
export const MINI_ONLY_SHAPES: readonly WrapShape[] = ["branch", "bush"];

/**
 * Half-width of a shape at depth `t` (0 at the top, 1 at the base), as a
 * fraction of its widest half-width.
 *
 * One profile, three consumers: the tiles the rep picks from, the live diagram
 * in the panel, and the lights painted on the customer's photo. They must agree
 * — a customer shown a narrow cone should not be quoted a wide one.
 */
export const WRAP_PROFILE: Record<WrapShape, (t: number) => number> = {
  // Cone: widens linearly to the base.
  evergreen: (t) => 0.15 + 0.85 * t,
  // Rounded canopy over a bare trunk: widest mid-height, closed at both ends.
  deciduous: (t) => Math.max(0.12, Math.sin(Math.PI * Math.min(t / 0.78, 1)) * 0.98),
  // A column of near-constant girth, tapering slightly like a real trunk.
  trunk: (t) => 0.34 + 0.1 * t,
  // A limb: narrower than a trunk, wrapped along its length.
  branch: (t) => 0.2 + 0.06 * t,
  // Low, wide, rounded over the top.
  bush: (t) => Math.min(1, 0.55 + 0.75 * Math.sin((Math.PI * t) / 1.35)),
};

/** Where a shape starts vertically: a canopy needs room for its trunk below. */
export const WRAP_TOP_INSET: Record<WrapShape, number> = {
  evergreen: 0,
  deciduous: 0,
  trunk: 0,
  branch: 0,
  bush: 0.18,
};

/**
 * How wide the wrapped area is relative to its lit height, from the rep's own
 * measurements. The canvas needs a ratio rather than feet: the rep already
 * placed and sized the tree on the photo, so the drawing keeps their placement
 * and takes only its silhouette from the measurement.
 */
export function wrapAspect(spec: WrapSpec): number | null {
  const heightFt = positive(spec.heightFt, 300);
  if (heightFt === null) return null;
  switch (spec.shape) {
    case "evergreen":
    case "deciduous": {
      const radiusFt = positive(spec.radiusFt, 100);
      return radiusFt === null ? null : radiusFt / heightFt;
    }
    case "trunk": {
      const widthIn = positive(spec.trunkWidthIn, 600);
      return widthIn === null ? null : widthIn / INCHES_PER_FOOT / 2 / heightFt;
    }
    case "branch": {
      const widthIn = positive(spec.branchWidthIn, 120);
      return widthIn === null ? null : widthIn / INCHES_PER_FOOT / 2 / heightFt;
    }
    case "bush": {
      const widthFt = positive(spec.widthFt, 300);
      return widthFt === null ? null : widthFt / 2 / heightFt;
    }
    default:
      return null;
  }
}

/**
 * The server refuses a line above this quantity (`EstimateCustomLine.quantity`)
 * and rejects the whole request with it, so a measurement this large is shown
 * to the rep but never sent — one absurd tree must not fail the entire estimate.
 */
export const MAX_BILLABLE_QUANTITY = 10_000;

/**
 * Only hand-wrapped seasonal decor is measured; everything else is counted.
 *
 * Both sides of the billing switch ask this one question, so an item can never
 * be skipped from its decor count by one rule and billed by a different one.
 */
export function isWrappable(product: Product): boolean {
  return product.target.field === "christmas" && product.style === "treewrap";
}

function positive(value: number | undefined, max: number): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0 || value > max) {
    return null;
  }
  return value;
}

/**
 * Spiral over a cone, evaluated exactly.
 *
 * The path over the radius profile `r(z) = R(1 - z/H)` integrates in closed
 * form, so an evergreen needs no numerical work.
 */
function evergreenLength(heightFt: number, radiusFt: number, spacingFt: number): number {
  const angularRate = TAU / spacingFt;
  const slope = 1 + (radiusFt / heightFt) ** 2;
  const scaledRadius = angularRate * radiusFt;
  const antiderivative =
    (radiusFt * Math.sqrt(slope + scaledRadius ** 2)) / 2 +
    (slope * Math.asinh(scaledRadius / Math.sqrt(slope))) / (2 * angularRate);
  return (heightFt / radiusFt) * antiderivative;
}

/**
 * Spiral over a rounded canopy `r(z) = R*sqrt(1 - (2z/H - 1)^2)`.
 *
 * No closed form, so this is fixed-step Simpson integration. 512 panels over a
 * smooth arc holds far tighter than the photo scale feeding it, and unlike
 * adaptive recursion it cannot fail on an extreme shape.
 *
 * simplification: fixed panel count rather than an adaptive error target. If
 * wrap footage ever has to match a supplier's cut list exactly, swap in
 * adaptive Simpson at 1e-6.
 */
function deciduousLength(heightFt: number, radiusFt: number, spacingFt: number): number {
  const halfHeight = heightFt / 2;
  const angularRate = TAU / spacingFt;
  const integrand = (angle: number) => {
    const heightChange = halfHeight * Math.cos(angle);
    const radiusChange = -radiusFt * Math.sin(angle);
    const rotationChange = radiusFt * Math.cos(angle) * angularRate * heightChange;
    return Math.hypot(radiusChange, rotationChange, heightChange);
  };

  const panels = 512;
  const start = -Math.PI / 2;
  const step = Math.PI / panels;
  let total = integrand(start) + integrand(start + Math.PI);
  for (let i = 1; i < panels; i += 1) {
    total += integrand(start + i * step) * (i % 2 === 0 ? 2 : 4);
  }
  return (total * step) / 3;
}

/**
 * Spiral around any constant-perimeter column, unrolled flat: each turn is the
 * hypotenuse of the perimeter and the vertical rise. Covers trunks, limbs, and
 * the four sides of a bush.
 */
function columnLength(perimeterFt: number, heightFt: number, spacingFt: number): number {
  return (heightFt / spacingFt) * Math.hypot(perimeterFt, spacingFt);
}

/** Raw wire feet for a spec, or null when a required dimension is missing. */
function rawFeet(spec: WrapSpec, heightFt: number, spacingFt: number): number | null {
  switch (spec.shape) {
    case "evergreen":
    case "deciduous": {
      const radiusFt = positive(spec.radiusFt, 100);
      if (radiusFt === null) return null;
      return spec.shape === "evergreen"
        ? evergreenLength(heightFt, radiusFt, spacingFt)
        : deciduousLength(heightFt, radiusFt, spacingFt);
    }
    case "trunk": {
      const widthIn = positive(spec.trunkWidthIn, 600);
      if (widthIn === null) return null;
      return columnLength((Math.PI * widthIn) / INCHES_PER_FOOT, heightFt, spacingFt);
    }
    case "branch": {
      const widthIn = positive(spec.branchWidthIn, 120);
      const count = positive(spec.branchCount, 500);
      if (widthIn === null || count === null || !Number.isInteger(count)) return null;
      // Strands run on from one limb to the next, so footage sums across all
      // branches and rounds up once — not once per branch.
      return count * columnLength((Math.PI * widthIn) / INCHES_PER_FOOT, heightFt, spacingFt);
    }
    case "bush": {
      const widthFt = positive(spec.widthFt, 300);
      const depthFt = positive(spec.depthFt, 300);
      if (widthFt === null || depthFt === null) return null;
      return columnLength(2 * (widthFt + depthFt), heightFt, spacingFt);
    }
    default:
      return null;
  }
}

/**
 * Price one measured item.
 *
 * Returns null only when the spec cannot produce footage at all (a missing or
 * out-of-range dimension). A spec that has geometry but no rate yet still
 * returns footage with a null price, so the rep sees the measurement land
 * before they have decided what to charge.
 */
export function calculateWrap(spec: WrapSpec): WrapResult | null {
  const heightFt = positive(spec.heightFt, 300);
  const rowSpacingIn = positive(spec.rowSpacingIn, 120);
  if (heightFt === null || rowSpacingIn === null) return null;

  const spacingFt = rowSpacingIn / INCHES_PER_FOOT;
  const feet = rawFeet(spec, heightFt, spacingFt);
  if (feet === null || !Number.isFinite(feet) || feet <= 0) return null;

  const plannedFeet = Math.ceil(feet);
  const unitKind = UNIT_KIND[spec.lightType] ?? "strand";

  let unitCount: number | null = null;
  if (unitKind === "bulb") {
    const bulbSpacingIn = positive(spec.bulbSpacingIn, 120);
    unitCount =
      bulbSpacingIn === null ? null : Math.ceil((plannedFeet * INCHES_PER_FOOT) / bulbSpacingIn);
  } else {
    const feetPerUnit = positive(spec.feetPerUnit, 1000);
    unitCount = feetPerUnit === null ? null : Math.ceil(plannedFeet / feetPerUnit);
  }

  const billedQuantity = spec.pricingMode === "foot" ? plannedFeet : unitCount;
  const unitPrice = positive(spec.unitPrice, 1_000_000);
  // Round to whole cents so the line the rep reads is the line the server bills.
  // A quantity past the server's cap prices as null rather than showing an
  // amount that would be refused: the readout then says so instead of promising
  // money that never reaches the quote.
  const price =
    billedQuantity === null || unitPrice === null || billedQuantity > MAX_BILLABLE_QUANTITY
      ? null
      : Math.round(billedQuantity * unitPrice * 100) / 100;

  return {
    plannedFeet,
    rowCount: Math.ceil(heightFt / spacingFt),
    unitCount,
    unitKind,
    billedQuantity,
    price,
  };
}

/** How a measured item reads on the estimate and on the customer's quote. */
export function wrapLineLabel(spec: WrapSpec, result: WrapResult, productName: string): string {
  const shape = WRAP_SHAPE_LABELS[spec.shape];
  const size =
    result.unitCount === null || spec.pricingMode === "foot"
      ? `${result.plannedFeet} ft`
      : `${result.plannedFeet} ft · ${result.unitCount} ${result.unitKind}${
          result.unitCount === 1 ? "" : "s"
        }`;
  // The product name carries the rep's own wording ("Front maple"); the shape
  // and size make the line self-explaining on a printed quote.
  return `${productName || shape} — ${size}`.slice(0, 120);
}

/** A measured item ready to bill: the item, its math, and its label. */
export interface MeasuredWrapLine {
  itemId: string;
  spec: WrapSpec;
  result: WrapResult;
  label: string;
}

/**
 * Every exactly-measured placed item in a design, in canvas order.
 *
 * Items whose product has disappeared from the catalog are skipped rather than
 * billed under a guessed name, and geometry that cannot be computed is dropped
 * — a half-typed form must never reach a customer's total. A `wrap` on decor
 * that is counted rather than wrapped is ignored here for the same reason
 * `designToEstimateInputs` still counts it: a stored document must not move an
 * item onto the seasonal side just by carrying an unexpected field.
 */
export function measuredWrapLines(
  design: Design,
  productById: Map<string, Product>,
): MeasuredWrapLine[] {
  const lines: MeasuredWrapLine[] = [];
  for (const item of design.items) {
    if (!item.wrap) continue;
    const product = productById.get(item.productId);
    if (!product || !isWrappable(product)) continue;
    const result = calculateWrap(item.wrap);
    if (!result) continue;
    lines.push({
      itemId: item.id,
      spec: item.wrap,
      result,
      label: wrapLineLabel(item.wrap, result, product.name),
    });
  }
  return lines;
}

/**
 * Switch a measurement to another shape, keeping the picture alive.
 *
 * A rep changes shape mid-conversation — "actually that one's more of a bush".
 * Naively that blanks the new shape's dimensions, so the price disappears and
 * the customer's photo drops back to a generic cone while they are looking at
 * it. This carries across the dimensions that genuinely mean the same thing
 * (canopy radius is half a bush's width, a limb and a trunk are both a girth),
 * and leaves anything without a real equivalent for the rep to type rather than
 * inventing a number.
 *
 * Existing values are never overwritten: switching away and back returns the
 * rep to exactly what they measured.
 */
export function switchWrapShape(spec: WrapSpec, shape: WrapShape): WrapSpec {
  const next: WrapSpec = {
    ...spec,
    shape,
    // Bulb cord is not hand-wrapped on limbs or bushes; move the rep to minis
    // rather than leaving an uninstallable combination selected.
    lightType:
      MINI_ONLY_SHAPES.includes(shape) && (spec.lightType === "c7" || spec.lightType === "c9")
        ? "mini"
        : spec.lightType,
  };

  const halfWidthFt = spec.radiusFt ?? (spec.widthFt !== undefined ? spec.widthFt / 2 : undefined);
  const girthIn = spec.trunkWidthIn ?? spec.branchWidthIn;

  if ((shape === "evergreen" || shape === "deciduous") && next.radiusFt === undefined) {
    next.radiusFt = halfWidthFt;
  }
  if (shape === "bush") {
    next.widthFt ??= halfWidthFt === undefined ? undefined : halfWidthFt * 2;
    next.depthFt ??= halfWidthFt === undefined ? undefined : halfWidthFt * 2;
  }
  if (shape === "trunk") next.trunkWidthIn ??= girthIn;
  if (shape === "branch") {
    next.branchWidthIn ??= girthIn;
    // One limb is the honest default: it is the smallest real job, so a rep who
    // does not notice the field is under-quoted rather than over-quoted.
    next.branchCount ??= 1;
  }
  return next;
}

/** True when this placed item is priced by exact wrap math instead of a band. */
export function isMeasured(item: PlacedItem): boolean {
  return item.wrap !== undefined && calculateWrap(item.wrap) !== null;
}

/**
 * True only when this item will actually bill as its own wrap line.
 *
 * This is the question `designToEstimateInputs` must ask before dropping an
 * item's decor count, and it is deliberately stricter than `isMeasured`: a tree
 * that is measured but not *billable* — no rate typed yet, or a quantity past
 * the server's cap — stays on band pricing rather than falling off the quote
 * between the two paths. A rep who mis-measures gets the old price, never a
 * free tree.
 */
export function isBilledByWrap(item: PlacedItem, product: Product): boolean {
  if (!item.wrap || !isWrappable(product)) return false;
  const result = calculateWrap(item.wrap);
  return result !== null && result.billedQuantity !== null && result.price !== null;
}

/**
 * Measured trees as seasonal estimate lines.
 *
 * These ride the existing custom-line path, so no new pricing field, endpoint,
 * or migration is needed — the server prices them exactly like a bucket-truck
 * fee. A measured-but-unpriced tree is left out: the rep still sees its footage
 * on the canvas, but an unpriced line must never land on a customer total.
 *
 * The server caps a request at 20 lines. Measured trees are the rep's own
 * typing, so they are not silently dropped here; the caller merges them with
 * hand-entered lines and surfaces the cap.
 *
 * Anything skipped here is still counted by its size band, so a tree is always
 * billed exactly one way — never twice, and never not at all.
 */
export function wrapEstimateLines(
  design: Design,
  productById: Map<string, Product>,
): EstimateCustomLine[] {
  const lines: EstimateCustomLine[] = [];
  for (const { label, spec, result } of measuredWrapLines(design, productById)) {
    // `price === null` already covers a missing rate and a quantity past the
    // server's cap. Both keep their band price instead (see `isBilledByWrap`).
    if (result.billedQuantity === null || result.price === null || spec.unitPrice === undefined) {
      continue;
    }
    lines.push({
      label,
      quantity: result.billedQuantity,
      unit_price: spec.unitPrice,
      side: "seasonal",
    });
  }
  return lines;
}
