import { describe, expect, it } from "vitest";

import { canonicalizeTermsUrl, TERMS_AND_CONDITIONS_URL } from "./legal";

describe("legal URLs", () => {
  it.each([
    "https://maxteriorslighting.com/terms",
    "https://maxteriorslighting.com/terms/",
    "https://maxteriorslighting.com/terms-conditions/",
    "https://www.maxteriorslighting.com/terms-conditions",
  ])("rewrites a legacy terms URL to the canonical page", (url) => {
    expect(canonicalizeTermsUrl(url)).toBe(TERMS_AND_CONDITIONS_URL);
  });

  it("leaves unrelated URLs unchanged", () => {
    expect(canonicalizeTermsUrl("https://example.com/terms")).toBe("https://example.com/terms");
  });
});
