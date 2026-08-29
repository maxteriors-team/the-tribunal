/**
 * Design → server-estimate mapper.
 *
 * The canvas produces only geometry (traced runs, placed items) and a photo
 * calibration. This module converts that design into the feet/counts the
 * existing `POST quotes/estimate` endpoint already understands — never any
 * money. Every dollar still comes back from the server.
 *
 * - A run of a `roofline` product → the request's top-level `feet`.
 * - A run of a `christmas` `per_ft` product (mini-lights, garland) →
 *   `christmas_items[category][option]` in linear feet.
 * - A placed `christmas` `each` item (tree, bush, wreath) →
 *   `christmas_items[category][option]` as a +1 count.
 * - A placed `landscape` fixture → a +1 count for that fixture *type*. The
 *   chosen package resolves the type to a real price-book product for server pricing.
 * - A `bistro` run → linear feet for the string-lighting add-on.
 *
 * Scale comes from the design's calibration line; uncalibrated photos fall back
 * to an assumed width so a rep still gets a ballpark before setting the scale.
 */
import type { ChristmasItemsSelection } from "@/types/estimate";

import { distance, polylineLength } from "./geometry";
import type { Design, Product, Run, ScaleSlot } from "./types";

/** When no scale is set we assume the photo spans this many feet across. */
export const ASSUMED_PHOTO_WIDTH_FT = 60;

/**
 * Gable rake correction (Pythagorean).
 *
 * A top-down aerial only ever shows a gable's horizontal *run*; the strand is
 * installed along the sloped *rake*, which is the hypotenuse. For a pitch of
 * `rise/12` the true length is `measured * sqrt(1 + (rise/12)^2)`.
 *
 * Two operator-facing buckets, each pinned to a representative pitch. Eaves and
 * fascia are horizontal, so an unset pitch is the correct 1.0 (no correction) —
 * this only ever grows footage when a rep explicitly marks a run as a gable.
 */
export const ROOF_PITCH_FACTORS = {
  /** 6/12 — typical residential gable. */
  normal: Math.sqrt(1 + (6 / 12) ** 2),
  /** 12/12 — steep gable. */
  steep: Math.sqrt(1 + (12 / 12) ** 2),
} as const satisfies Record<string, number>;

export type RoofPitch = keyof typeof ROOF_PITCH_FACTORS;

/**
 * The measured-to-installed multiplier for one run. Unset (an eave, or a design
 * drawn before pitch existed) means no correction, so saved work never silently
 * reprices.
 */
export function roofPitchFactor(run: Pick<Run, "roofPitch">): number {
  return run.roofPitch ? ROOF_PITCH_FACTORS[run.roofPitch] : 1;
}

export interface DesignScale {
  /** feet per image pixel (0 when the photo width is unknown) */
  ftPerPx: number;
  /** image pixels per foot (for sizing bulbs) */
  pxPerFt: number;
  calibrated: boolean;
}

export function designScale(
  design: Design,
  photoWidth: number,
  scaleSlot: ScaleSlot = 1,
): DesignScale {
  const calibrationScale = (calibration: Design["secondaryCalibration"]): DesignScale | null => {
    if (!calibration || calibration.feet <= 0) return null;
    const px = distance(calibration.a, calibration.b);
    if (px <= 1) return null;
    const ftPerPx = calibration.feet / px;
    return { ftPerPx, pxPerFt: 1 / ftPerPx, calibrated: true };
  };
  const calibrated =
    calibrationScale(scaleSlot === 2 ? design.secondaryCalibration : design.calibration) ??
    (scaleSlot === 2 ? calibrationScale(design.calibration) : null);
  if (calibrated) return calibrated;

  const ftPerPx = photoWidth > 0 ? ASSUMED_PHOTO_WIDTH_FT / photoWidth : 0;
  const pxPerFt =
    ftPerPx > 0 ? 1 / ftPerPx : photoWidth > 0 ? photoWidth / ASSUMED_PHOTO_WIDTH_FT : 1;
  return { ftPerPx, pxPerFt, calibrated: false };
}

/** Resolve a saved run's scale; missing/invalid Scale 2 safely falls back to Scale 1. */
export function runScale(design: Design, run: Run, photoWidth: number): DesignScale {
  return designScale(design, photoWidth, run.scaleSlot ?? 1);
}

/** The estimate inputs a design contributes: roofline feet + decor selection. */
export interface DesignEstimateInputs {
  feet: number;
  christmas_items: ChristmasItemsSelection;
  /** Placed landscape fixtures, counted by fixture type (uplight, path…). */
  fixtures: Record<string, number>;
  /** Linear feet of bistro / festoon string lighting traced on the photo. */
  bistro_feet: number;
}

/**
 * Tally a design into the estimate request's measured inputs. Linear runs are
 * converted to feet via each run's scale and rounded to whole feet (rooflines
 * and garland are quoted in whole feet); placed items count as one each.
 */
export function designToEstimateInputs(
  design: Design,
  productById: Map<string, Product>,
  photoWidth: number,
): DesignEstimateInputs {
  let rooflineFt = 0;
  let bistroFt = 0;
  const raw: ChristmasItemsSelection = {};
  const landscape: Record<string, number> = {};
  const addChristmas = (category: string, option: string, value: number) => {
    const bucket = raw[category] ?? (raw[category] = {});
    bucket[option] = (bucket[option] ?? 0) + value;
  };

  for (const run of design.runs) {
    const product = productById.get(run.productId);
    if (!product) continue;
    const ft = polylineLength(run.points) * runScale(design, run, photoWidth).ftPerPx;
    if (ft <= 0) continue;
    if (product.target.field === "roofline") {
      // Only the roofline is pitch-corrected: bistro spans and christmas decor
      // are not installed along a roof rake.
      rooflineFt += ft * roofPitchFactor(run);
    } else if (product.target.field === "bistro") {
      bistroFt += ft;
    } else if (product.target.field === "christmas") {
      addChristmas(product.target.category, product.target.option, ft);
    }
  }

  for (const item of design.items) {
    const product = productById.get(item.productId);
    if (!product) continue;
    if (product.target.field === "christmas") {
      addChristmas(product.target.category, product.target.option, 1);
    } else if (product.target.field === "landscape") {
      const type = product.target.fixtureType;
      landscape[type] = (landscape[type] ?? 0) + 1;
    }
  }

  // Round every bucket to a whole unit: feet round to whole feet, counts are
  // already integers (a per-category unit is uniform, so no bucket mixes them).
  // Drop zeros so a sub-foot stray run doesn't add an empty line.
  const christmas_items: ChristmasItemsSelection = {};
  for (const [category, options] of Object.entries(raw)) {
    for (const [option, value] of Object.entries(options)) {
      const rounded = Math.round(value);
      if (rounded > 0) {
        (christmas_items[category] ??= {})[option] = rounded;
      }
    }
  }

  return {
    feet: Math.round(rooflineFt),
    christmas_items,
    fixtures: landscape,
    bistro_feet: Math.round(bistroFt),
  };
}

/**
 * Total the inputs from several photos of the same job.
 *
 * A rep designs the front of the house on one photo and the back on another;
 * the quote has to carry both. Each photo is measured on its own calibration
 * before it gets here, so the totals are a straight sum — the only shared unit
 * is feet/counts, never pixels.
 */
export function sumEstimateInputs(parts: DesignEstimateInputs[]): DesignEstimateInputs {
  const total: DesignEstimateInputs = {
    feet: 0,
    christmas_items: {},
    fixtures: {},
    bistro_feet: 0,
  };
  for (const part of parts) {
    total.feet += part.feet;
    total.bistro_feet += part.bistro_feet;
    for (const [type, count] of Object.entries(part.fixtures)) {
      total.fixtures[type] = (total.fixtures[type] ?? 0) + count;
    }
    for (const [category, options] of Object.entries(part.christmas_items)) {
      const bucket = (total.christmas_items[category] ??= {});
      for (const [option, value] of Object.entries(options)) {
        bucket[option] = (bucket[option] ?? 0) + value;
      }
    }
  }
  return total;
}

/** True when the design has anything drawn or placed. */
export function hasDesign(design: Design): boolean {
  return design.runs.length > 0 || design.items.length > 0;
}

/** Human-readable feet for canvas hints: sub-10ft keeps a decimal, else whole. */
export function formatFeet(ft: number): string {
  if (!Number.isFinite(ft)) return "—";
  return ft < 10 ? `${ft.toFixed(1)} ft` : `${Math.round(ft)} ft`;
}
