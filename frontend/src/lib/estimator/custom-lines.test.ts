import { describe, expect, it } from "vitest";

import {
  MAX_CUSTOM_LINES,
  newCustomLineDraft,
  toEstimateCustomLines,
  type CustomLineDraft,
} from "./custom-lines";

function draft(over: Partial<CustomLineDraft> = {}): CustomLineDraft {
  return { ...newCustomLineDraft("seasonal"), ...over };
}

describe("toEstimateCustomLines", () => {
  it("converts a complete row into a request line", () => {
    expect(
      toEstimateCustomLines([
        draft({ label: "  Bucket truck day ", quantity: "2", unitPrice: "150" }),
      ]),
    ).toEqual([
      { label: "Bucket truck day", quantity: 2, unit_price: 150, side: "seasonal" },
    ]);
  });

  it("defaults a blank quantity to one", () => {
    const [line] = toEstimateCustomLines([
      draft({ label: "Trip fee", quantity: "", unitPrice: "60" }),
    ]);
    expect(line.quantity).toBe(1);
  });

  it("keeps half-typed rows out of the priced request", () => {
    // The total must not jump around mid-keystroke: a row without a name or a
    // price is still being written, not a $0 line the customer owes.
    expect(
      toEstimateCustomLines([
        draft({ label: "", unitPrice: "150" }),
        draft({ label: "Unpriced", unitPrice: "" }),
        draft({ label: "Nonsense", unitPrice: "abc" }),
        draft({ label: "Negative", unitPrice: "-50" }),
        draft({ label: "Zero qty", quantity: "0", unitPrice: "50" }),
      ]),
    ).toEqual([]);
  });

  it("allows a deliberate $0 line", () => {
    const [line] = toEstimateCustomLines([
      draft({ label: "First-year takedown — included", unitPrice: "0" }),
    ]);
    expect(line.unit_price).toBe(0);
  });

  it("carries the side the rep chose", () => {
    const [line] = toEstimateCustomLines([
      draft({ label: "Remove old clips", unitPrice: "90", side: "permanent" }),
    ]);
    expect(line.side).toBe("permanent");
  });

  it("omits the package key for an all-packages line", () => {
    // No key is what asks the server for today's behavior: the line rides on
    // top of whichever tier the client picks.
    const [line] = toEstimateCustomLines([
      draft({ label: "Trip charge", unitPrice: "75" }),
    ]);
    expect(line.package_key).toBeUndefined();
  });

  it("pins a line to the tier the rep scoped it to", () => {
    const [line] = toEstimateCustomLines([
      draft({
        label: "Bucket truck day",
        unitPrice: "200",
        packageKey: "premier",
      }),
    ]);
    expect(line.package_key).toBe("premier");
  });

  it("drops a package scope from a one-time line", () => {
    // The ladder is seasonal; a permanent line has no card to live inside, and
    // the server would drop it outright rather than bill it globally.
    const [line] = toEstimateCustomLines([
      draft({
        label: "Remove old clips",
        unitPrice: "90",
        side: "permanent",
        packageKey: "premier",
      }),
    ]);
    expect(line.package_key).toBeUndefined();
    expect(line.side).toBe("permanent");
  });

  it("starts a new row unscoped", () => {
    expect(newCustomLineDraft("seasonal").packageKey).toBeNull();
  });

  it("stops at the server's line cap", () => {
    const rows = Array.from({ length: MAX_CUSTOM_LINES + 5 }, (_, i) =>
      draft({ label: `Line ${i}`, unitPrice: "10" }),
    );
    expect(toEstimateCustomLines(rows)).toHaveLength(MAX_CUSTOM_LINES);
  });

  it("gives every new row its own id", () => {
    const ids = new Set([
      newCustomLineDraft("seasonal").id,
      newCustomLineDraft("seasonal").id,
      newCustomLineDraft("permanent").id,
    ]);
    expect(ids.size).toBe(3);
  });
});
