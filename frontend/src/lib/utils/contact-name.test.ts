import { describe, expect, it } from "vitest";

import { contactDisplayName } from "./contact-name";

describe("contactDisplayName", () => {
  it("joins first and last name", () => {
    expect(
      contactDisplayName({ first_name: "Ada", last_name: "Lovelace" }),
    ).toBe("Ada Lovelace");
  });

  it("uses the first name alone when there is no last name", () => {
    expect(contactDisplayName({ first_name: "Ada", last_name: null })).toBe("Ada");
  });

  it("falls back to the phone number for nameless provider-created contacts", () => {
    expect(
      contactDisplayName({ first_name: "", phone_number: "+14155552671" }),
    ).toBe("+1 (415) 555-2671");
  });

  it("treats whitespace-only names as missing", () => {
    expect(
      contactDisplayName({ first_name: "  ", last_name: " ", phone_number: "5551234567" }),
    ).toBe("(555) 123-4567");
  });

  it("falls back to Unknown only when there is no name and no phone", () => {
    expect(contactDisplayName({ first_name: "", phone_number: null })).toBe("Unknown");
  });
});
