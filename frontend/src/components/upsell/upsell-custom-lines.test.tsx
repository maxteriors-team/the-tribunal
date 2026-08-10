import { describe, expect, it } from "vitest";

import {
  customLineSubtotal,
  toCustomLineRequest,
  type UpsellCustomLineDraft,
} from "./upsell-custom-lines";

const line = (values: Partial<UpsellCustomLineDraft> = {}): UpsellCustomLineDraft => ({
  id: "line-1",
  name: "Lift rental",
  quantity: "2",
  unitPrice: "75.50",
  ...values,
});

describe("upsell custom line pricing", () => {
  it("normalizes a valid custom line for the API", () => {
    expect(toCustomLineRequest(line({ name: "  Lift rental  " }))).toEqual({
      name: "Lift rental",
      quantity: 2,
      unit_price: 75.5,
    });
  });

  it.each([
    { name: "", quantity: "1", unitPrice: "75" },
    { name: "Lift", quantity: "0", unitPrice: "75" },
    { name: "Lift", quantity: "1", unitPrice: "0" },
    { name: "Lift", quantity: "1001", unitPrice: "75" },
    { name: "Lift", quantity: "1", unitPrice: "100001" },
  ])("rejects incomplete or out-of-bounds input: %o", (draft) => {
    expect(toCustomLineRequest(line(draft))).toBeNull();
  });

  it("totals only complete lines", () => {
    expect(
      customLineSubtotal([
        line(),
        line({ id: "line-2", name: "", unitPrice: "1000" }),
      ]),
    ).toBe(151);
  });
});
