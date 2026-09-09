/**
 * How much light strand a wrapped tree actually needs.
 *
 * A tree placed on the photo used to count as "1 tree" at a flat rate, so a 6 ft
 * shrub and a 30 ft oak billed the same. This turns the two things a rep can
 * genuinely see in a photo — how tall the wrap goes and how wide the canopy is —
 * into feet of strand, which the workspace already prices per foot.
 *
 * The model, stated plainly so nobody has to reverse-engineer it from the
 * arithmetic: the wrapped part of the tree is treated as a **tapered column**,
 * `canopyWidthFt` across at the bottom and narrowing to {@link TAPER} of that at
 * the top. The strand spirals up it at a fixed vertical `spacingIn`. Each full
 * turn is the hypotenuse of (circumference at that height, one spacing of rise),
 * which is the exact length of one turn of a helix — not the circumference
 * alone, which would under-count every wrap.
 *
 * Deliberately pure and canvas-free: the same numbers drive the price, the
 * readout the rep sees, and the rows of bulbs drawn on the tree, so those three
 * can never disagree. Everything is in feet except `spacingIn`, which reps quote
 * in inches ("3-inch wrap").
 */

/**
 * Width at the top of the wrap as a fraction of the canopy width.
 *
 * Matches the taper the canvas has always drawn (`topW/botW` in the treewrap
 * renderer), so the measured price and the picture describe the same tree.
 */
export const TAPER = 0.69;

/** Vertical gap between spirals when the rep hasn't chosen one. */
export const DEFAULT_WRAP_SPACING_IN = 3;

/** Spacing choices offered in the palette, in inches. Tighter = denser = pricier. */
export const WRAP_SPACING_OPTIONS: Record<string, number> = {
  "Dense (2 in)": 2,
  "Standard (3 in)": 3,
  "Open (4 in)": 4,
  "Sparse (6 in)": 6,
};

/**
 * Slack for the spiral, the drop to the outlet, and the fact that nobody wraps a
 * tree as tightly as geometry says. Applied once at the end so the raw helix
 * math stays inspectable.
 */
export const WRAP_WASTE_FACTOR = 1.1;

export interface TreeWrapInput {
  /** How far up the tree the wrap goes, in feet. */
  heightFt: number;
  /** Canopy width at the bottom of the wrap, in feet. */
  canopyWidthFt: number;
  /** Vertical gap between spirals, in inches. */
  spacingIn?: number;
}

export interface TreeWrapResult {
  /** Feet of strand to buy and bill. Rounded to a whole foot. */
  strandFt: number;
  /** How many times the strand goes around the tree. Rounded down. */
  turns: number;
  /** Spacing actually used, after defaulting. */
  spacingIn: number;
}

const EMPTY: TreeWrapResult = { strandFt: 0, turns: 0, spacingIn: DEFAULT_WRAP_SPACING_IN };

/**
 * Feet of strand for one wrapped tree.
 *
 * Returns zeros for anything not yet measured (a tree dropped on the photo but
 * never sized) rather than guessing, so an unmeasured tree contributes nothing
 * and stays visibly unpriced instead of quietly inventing footage.
 */
export function treeWrapStrand(input: TreeWrapInput): TreeWrapResult {
  const spacingIn =
    input.spacingIn && input.spacingIn > 0 ? input.spacingIn : DEFAULT_WRAP_SPACING_IN;
  const { heightFt, canopyWidthFt } = input;
  if (!(heightFt > 0) || !(canopyWidthFt > 0)) return { ...EMPTY, spacingIn };

  const spacingFt = spacingIn / 12;
  // A partial turn still costs a full pass up the tree in practice, but counting
  // it as a whole turn over-bills short shrubs; floor and let the waste factor
  // carry the remainder.
  const turns = Math.floor(heightFt / spacingFt);
  if (turns <= 0) return { ...EMPTY, spacingIn };

  // Mean width of the tapered column — the average turn's circumference.
  const meanWidthFt = (canopyWidthFt * (1 + TAPER)) / 2;
  const circumferenceFt = Math.PI * meanWidthFt;
  // One turn of a helix: around by the circumference, up by one spacing.
  const perTurnFt = Math.hypot(circumferenceFt, spacingFt);

  return {
    strandFt: Math.round(turns * perTurnFt * WRAP_WASTE_FACTOR),
    turns,
    spacingIn,
  };
}
