import { describe, expect, it } from "vitest";

import { DEFAULT_WRAP_SPACING_IN, TAPER, WRAP_WASTE_FACTOR, treeWrapStrand } from "./tree-wrap";

/** The formula, written independently of the implementation. */
function expectedFt(heightFt: number, widthFt: number, spacingIn: number): number {
  const spacingFt = spacingIn / 12;
  const turns = Math.floor(heightFt / spacingFt);
  const mean = (widthFt * (1 + TAPER)) / 2;
  return Math.round(turns * Math.hypot(Math.PI * mean, spacingFt) * WRAP_WASTE_FACTOR);
}

describe("treeWrapStrand", () => {
  it("prices a big tree far above a small one", () => {
    const shrub = treeWrapStrand({ heightFt: 6, canopyWidthFt: 3 });
    const oak = treeWrapStrand({ heightFt: 30, canopyWidthFt: 14 });

    // The whole point of measuring: these can no longer bill the same.
    expect(oak.strandFt).toBeGreaterThan(shrub.strandFt * 10);
  });

  it("matches the helix formula", () => {
    expect(treeWrapStrand({ heightFt: 20, canopyWidthFt: 8, spacingIn: 3 }).strandFt).toBe(
      expectedFt(20, 8, 3),
    );
  });

  it("counts the rise of each turn, not just the circumference", () => {
    // On a real tree the rise is negligible — a 3 in climb against a 20 ft
    // circumference vanishes in the rounding. It only becomes observable on
    // something narrow wrapped loosely, which is where this pins it.
    const narrowAndLoose = treeWrapStrand({ heightFt: 20, canopyWidthFt: 0.5, spacingIn: 12 });

    const turns = Math.floor(20 / 1);
    const flat = Math.round(turns * Math.PI * ((0.5 * (1 + TAPER)) / 2) * WRAP_WASTE_FACTOR);
    expect(narrowAndLoose.strandFt).toBeGreaterThan(flat);
  });

  it("tighter spacing costs more strand", () => {
    const dense = treeWrapStrand({ heightFt: 15, canopyWidthFt: 6, spacingIn: 2 });
    const sparse = treeWrapStrand({ heightFt: 15, canopyWidthFt: 6, spacingIn: 6 });

    expect(dense.strandFt).toBeGreaterThan(sparse.strandFt);
    expect(dense.turns).toBeGreaterThan(sparse.turns);
  });

  it("scales with canopy width at a fixed height", () => {
    const narrow = treeWrapStrand({ heightFt: 20, canopyWidthFt: 4 });
    const wide = treeWrapStrand({ heightFt: 20, canopyWidthFt: 8 });

    // Circumference dominates, so doubling the width nearly doubles the strand.
    expect(wide.strandFt / narrow.strandFt).toBeGreaterThan(1.8);
    expect(wide.strandFt / narrow.strandFt).toBeLessThan(2.1);
  });

  it("defaults the spacing when the rep hasn't picked one", () => {
    expect(treeWrapStrand({ heightFt: 12, canopyWidthFt: 5 }).spacingIn).toBe(
      DEFAULT_WRAP_SPACING_IN,
    );
    expect(treeWrapStrand({ heightFt: 12, canopyWidthFt: 5, spacingIn: 0 }).spacingIn).toBe(
      DEFAULT_WRAP_SPACING_IN,
    );
  });

  it("an unmeasured tree contributes nothing instead of guessing", () => {
    // A tree dropped on the photo but never sized must stay visibly unpriced.
    expect(treeWrapStrand({ heightFt: 0, canopyWidthFt: 6 }).strandFt).toBe(0);
    expect(treeWrapStrand({ heightFt: 12, canopyWidthFt: 0 }).strandFt).toBe(0);
    expect(treeWrapStrand({ heightFt: -4, canopyWidthFt: 6 }).strandFt).toBe(0);
  });

  it("a tree shorter than one wrap spacing is not billed a turn", () => {
    const result = treeWrapStrand({ heightFt: 0.1, canopyWidthFt: 2, spacingIn: 6 });

    expect(result.turns).toBe(0);
    expect(result.strandFt).toBe(0);
  });

  it("stays in a believable range for a real medium tree", () => {
    // 15 ft tall, 7 ft canopy, standard 3 in wrap. 60 turns around a mean 5.9 ft
    // width is ~1,227 ft — about 49 of the 25 ft mini-light strands a crew
    // actually buys, which is the right order of magnitude for wrapping a whole
    // canopy. Pinned exactly so a change to the model has to be deliberate.
    const result = treeWrapStrand({ heightFt: 15, canopyWidthFt: 7 });

    expect(result.strandFt).toBe(1227);
    expect(result.strandFt / 25).toBeGreaterThan(20);
    expect(result.strandFt / 25).toBeLessThan(80);
  });

  it("returns whole feet, since strand is bought and billed whole", () => {
    const result = treeWrapStrand({ heightFt: 13.7, canopyWidthFt: 6.3, spacingIn: 3.5 });

    expect(Number.isInteger(result.strandFt)).toBe(true);
    expect(Number.isInteger(result.turns)).toBe(true);
  });
});
