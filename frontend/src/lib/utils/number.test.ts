import { describe, expect, it } from "vitest";

import { formatCurrency, formatNumber, formatPercent } from "./number";

describe("number utils", () => {
  describe("formatNumber", () => {
    it("groups thousands with commas", () => {
      expect(formatNumber(1234567)).toBe("1,234,567");
    });

    it("preserves decimal places", () => {
      expect(formatNumber(1234.56)).toBe("1,234.56");
    });

    it("handles zero and negatives", () => {
      expect(formatNumber(0)).toBe("0");
      expect(formatNumber(-1500)).toBe("-1,500");
    });

    it("returns an em-dash for non-finite values", () => {
      expect(formatNumber(Number.NaN)).toBe("—");
      expect(formatNumber(Number.POSITIVE_INFINITY)).toBe("—");
    });
  });

  describe("formatCurrency", () => {
    it("defaults to USD", () => {
      expect(formatCurrency(1234.5)).toBe("$1,234.50");
    });

    it("respects an explicit currency", () => {
      // EUR formatting in en-US locale: "€1,234.50"
      expect(formatCurrency(1234.5, "EUR")).toBe("€1,234.50");
    });

    it("formats zero with two fractional digits", () => {
      expect(formatCurrency(0)).toBe("$0.00");
    });

    it("returns an em-dash for non-finite values", () => {
      expect(formatCurrency(Number.NaN)).toBe("—");
    });
  });

  describe("formatPercent", () => {
    it("treats input as a 0..1 fraction", () => {
      expect(formatPercent(0.1234)).toBe("12.34%");
    });

    it("renders whole percents without trailing decimals", () => {
      expect(formatPercent(0.5)).toBe("50%");
    });

    it("formats zero", () => {
      expect(formatPercent(0)).toBe("0%");
    });

    it("returns an em-dash for non-finite values", () => {
      expect(formatPercent(Number.NaN)).toBe("—");
    });
  });
});
