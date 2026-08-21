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
 * How a product is rendered on the canvas.
 *
 * The first block is holiday strand/decor work; the second is landscape
 * lighting. The six fixture styles throw visible light, while `transformer` is
 * plan equipment: it gets a drafting symbol but intentionally emits no glow.
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
  | "walllight"
  | "underwater"
  | "transformer"
  | "wire"
  | "bistro";

/** Landscape fixture styles — placed, and rendered as a beam or a light pool. */
export const LANDSCAPE_STYLES = [
  "uplight",
  "ingrade",
  "pathlight",
  "downlight",
  "walllight",
  "underwater",
] as const satisfies readonly RenderStyle[];

/** Drafting symbols that stay visible over the editable plan. */
export const LANDSCAPE_PLAN_STYLES = [
  ...LANDSCAPE_STYLES,
  "transformer",
] as const satisfies readonly RenderStyle[];

/** Whether a style is a light-emitting landscape fixture. */
export function isLandscapeStyle(style: RenderStyle): boolean {
  return (LANDSCAPE_STYLES as readonly RenderStyle[]).includes(style);
}

/** Whether a style has a persistent symbol on the editable drawing sheet. */
export function isLandscapePlanStyle(style: RenderStyle): boolean {
  return (LANDSCAPE_PLAN_STYLES as readonly RenderStyle[]).includes(style);
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
  "walllight",
  "underwater",
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
  walllight: 35,
  underwater: 43,
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
export function beamAngleFor(style: RenderStyle, override?: number | null): number | null {
  if (!hasBeamAngle(style)) return null;
  return clampBeamAngle(override ?? DEFAULT_BEAM_ANGLE_DEG[style]);
}

/**
 * Legacy beam orientation stored by older drawings. The editor no longer
 * exposes an aiming control, but the renderer keeps honoring saved values so
 * opening an existing customer plan does not silently change its appearance.
 */
export function normalizeBeamRotation(deg: number): number {
  if (!Number.isFinite(deg)) return 0;
  return ((((deg + 180) % 360) + 360) % 360) - 180;
}

/** The legacy orientation a saved fixture renders at. */
export function beamRotationFor(override?: number | null): number {
  return normalizeBeamRotation(override ?? 0);
}

/** Fixture symbols resize independently from beam throw and quote quantity. */
export const MIN_FIXTURE_ICON_SCALE = 0.6;
export const MAX_FIXTURE_ICON_SCALE = 1.8;
export const FIXTURE_ICON_SCALE_STEP = 0.2;

export function fixtureIconScaleFor(override?: number | null): number {
  if (!Number.isFinite(override)) return 1;
  return Math.min(Math.max(override ?? 1, MIN_FIXTURE_ICON_SCALE), MAX_FIXTURE_ICON_SCALE);
}

/**
 * Where a drawn product's measured quantity lands in the server estimate
 * request. The canvas only produces feet/counts; every dollar is still computed
 * server-side, so a product just declares its destination:
 *
 * - `roofline` → the request's top-level `feet`.
 * - `christmas` → `christmas_items[category][option]`.
 * - `landscape` → a count of one light fixture type.
 * - `bistro` → linear feet of string lighting.
 * - `annotation` → plan-only equipment such as a transformer. It is persisted
 *   with the drawing but deliberately excluded from quote quantities.
 */
export type DrawTarget =
  | { field: "roofline" }
  | { field: "christmas"; category: string; option: string }
  | { field: "landscape"; fixtureType: string }
  | { field: "bistro" }
  | { field: "annotation"; annotationType: "transformer" | "wire" };

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
  /** Stable live catalog references for newly placed fixtures. */
  catalogItemId?: string;
  catalogSku?: string;
  /**
   * The resolved product's own name (“ZDC Color Uplight”) shown under the type
   * label, so the rep can see what the package actually installs.
   */
  productName?: string | null;
  /** Lamp specification and included accessories from the CRM price-book item. */
  lampLabel?: string | null;
  accessoryLabels?: string[];
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
  /** Internal run type used to weight permanent-lighting markup. */
  permanentComplexity?: "aerial" | "easy" | "standard" | "complex";
  /** Plan-only electrical metadata for a landscape wire circuit. */
  circuitLabel?: string;
  transformerId?: string;
  /** New circuits use 10/2 or 12/2; legacy 8 and 14 values remain readable. */
  wireGauge?: 8 | 10 | 12 | 14;
  sourceVoltage?: number;
  transformerZoneId?: string;
}

export interface PlacedItem {
  id: string;
  productId: string;
  at: Point;
  /** Beam throw or pool diameter in image pixels. */
  sizePx: number;
  /** Drawing-sheet symbol scale; independent from beam throw. */
  iconScale?: number;
  /** Per-fixture beam-spread override. Missing means the fixture type's default lamp. */
  beamAngleDeg?: number;
  /** Legacy saved orientation. New edits keep the fixture on its natural axis. */
  beamRotationDeg?: number;
  /** ID of the plan-only wire circuit that supplies this fixture. */
  circuitId?: string;
  /** Per-fixture construction-plan marker color; never changes light output or price. */
  markerColor?: string;
  /** Stable CRM catalog references; live catalog data remains authoritative. */
  catalogItemId?: string;
  catalogSku?: string;
  lampCatalogItemId?: string;
  accessoryCatalogItemIds?: string[];
  transformerZoneId?: string;
}

export interface Calibration {
  a: Point;
  b: Point;
  feet: number;
}

/** A movable image inset placed over the editable construction plan. */
export interface PlanImage {
  id: string;
  dataUrl: string;
  name: string;
  /** Image center in property-photo coordinates. */
  at: Point;
  widthPx: number;
  heightPx: number;
}

export type LandscapePaperSize = "tabloid" | "super-b" | "letter" | "arch-c" | "arch-d" | "ansi-d";
export type LandscapeWorkflowTab =
  | "drawing"
  | "schedule"
  | "bom"
  | "electrical"
  | "proposal"
  | "precon";
export type LandscapePlanFit = "contain" | "cover";

export interface LandscapeRevisionRow {
  id: string;
  number: string;
  description: string;
  date: string;
  author: string;
}

export interface LandscapeAnnotation {
  id: string;
  type: "note" | "line" | "tree" | "photo" | "revision";
  at: Point;
  end?: Point;
  text?: string;
  sizePx?: number;
  rotationDeg?: number;
  imageDataUrl?: string;
}

export interface LandscapeMeasurementLine {
  id: string;
  a: Point;
  b: Point;
  label?: string;
  visible?: boolean;
}

export interface LandscapeHighlightStroke {
  id: string;
  points: Point[];
  color: string;
  widthPx: number;
}

export interface LandscapeArrow {
  id: string;
  a: Point;
  b: Point;
  label?: string;
}

export interface LandscapeSheetMetadata {
  label?: string;
  drawingTitle?: string;
  drawingNumber?: string;
  proposalZoneId?: string;
  revisions?: LandscapeRevisionRow[];
}

export interface LandscapeLegendSettings {
  visible: boolean;
  position: Point;
  scale: number;
}

export interface LandscapeBomLineItem {
  id: string;
  description: string;
  sku: string;
  quantity: number;
  unit: "each" | "ft";
}

export interface LandscapeProcurementState {
  catalogItemId?: string | null;
  catalogSku?: string | null;
  description?: string;
  manufacturer?: string;
  supplier?: string;
  neededQuantity?: number;
  orderedQuantity: number;
  receivedQuantity: number;
  unitCost?: number | null;
  supplierNote: string;
}

export interface LandscapeProposalZone {
  id: string;
  name: string;
  description: string;
  shotIds: string[];
}

export interface LandscapePaymentMilestone {
  id: string;
  label: string;
  percent: number;
}

export interface LandscapeProposalEnhancement {
  id: string;
  catalogItemId: string;
  catalogSku?: string;
  quantity: number;
  note: string;
}

export interface LandscapeProposalLineItem {
  id: string;
  description: string;
  amount: number;
}

export interface LandscapeProposalSettings {
  selectedTierKey: string | null;
  selectedCarePlanKey: string | null;
  designIntent: string;
  showCombinedTotal: boolean;
  showFixtureDetails: boolean;
  zones: LandscapeProposalZone[];
  paymentMilestones: LandscapePaymentMilestone[];
  electricalResponsibility: string;
  enhancements: LandscapeProposalEnhancement[];
  additionalLineItems?: LandscapeProposalLineItem[];
  commitments: string[];
  signatureName: string;
  signatureDate: string | null;
}

export type LandscapePreconResponseValue = "yes" | "no" | "na" | null;

export interface LandscapePreconResponse {
  itemId: string;
  value: LandscapePreconResponseValue;
  comment: string;
}

export interface LandscapePreconState {
  responses: LandscapePreconResponse[];
  leadInstaller: string;
  notes: string;
}

export interface Design {
  calibration: Calibration | null;
  runs: Run[];
  items: PlacedItem[];
  /** Optional so drawings saved before image insets continue to load unchanged. */
  planImages?: PlanImage[];
  annotations?: LandscapeAnnotation[];
  measurements?: LandscapeMeasurementLine[];
  highlights?: LandscapeHighlightStroke[];
  arrows?: LandscapeArrow[];
}

export type Tool =
  | { type: "select" }
  | { type: "calibrate" }
  | { type: "draw"; productId: string }
  | { type: "place"; productId: string }
  | { type: "highlight" };

export type Selection = { kind: "run" | "item" | "planImage"; id: string } | null;

/** A loaded house photo: its data URL plus intrinsic pixel dimensions. */
export interface PhotoInfo {
  dataUrl: string;
  width: number;
  height: number;
}

/** One saved photo/design pair in a multi-elevation lighting project. */
export interface DesignerShot {
  id: string;
  photo: PhotoInfo;
  design: Design;
  dusk: number;
  /** Drawing-sheet title, revision, and proposal-zone metadata. */
  sheet?: LandscapeSheetMetadata;
}
