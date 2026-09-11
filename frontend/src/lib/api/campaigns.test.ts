import { describe, expect, it } from "vitest";

import * as campaigns from "./campaigns";

describe("campaign API surface", () => {
  it("does not expose unused generic campaign-contact helpers", () => {
    expect(campaigns).not.toHaveProperty("campaignContactsApi");
  });
});
