import { describe, expect, it } from "vitest";

import type { PricingSettings } from "@/types/sales-wizard";

import {
  SERVICES,
  clientThemeClass,
  serviceSpec,
  serviceValueProps,
} from "./services";

function pricing(overrides: Record<string, unknown> = {}): PricingSettings {
  return {
    landscape: { perks: ["Lit walkways every night"] },
    permanent: { perks: ["Never hang lights again"] },
    christmas: { perks: ["Takedown and storage included"] },
    tiers: [
      {
        key: "best",
        label: "Best",
        points: ["Color change from your phone", "Aircraft aluminum"],
      },
      { key: "essential", label: "Good", points: ["Key area coverage"] },
    ],
    ...overrides,
  } as unknown as PricingSettings;
}

describe("services", () => {
  it("covers exactly the three services a design can sell", () => {
    expect(SERVICES.map((s) => s.key)).toEqual([
      "landscape",
      "permanent",
      "christmas",
    ]);
  });

  it("gives each service its own headline instead of one generic pitch", () => {
    const headlines = SERVICES.map((s) => serviceSpec(s.key).headline);
    expect(new Set(headlines).size).toBe(3);
  });
});

describe("serviceValueProps", () => {
  it("uses the operator's configured copy per service", () => {
    expect(serviceValueProps("permanent", pricing())).toEqual([
      "Never hang lights again",
    ]);
    expect(serviceValueProps("christmas", pricing())).toEqual([
      "Takedown and storage included",
    ]);
  });

  it("leads landscape with the chosen package's own selling points", () => {
    // A Best customer should read about color change; a Good customer must not.
    expect(serviceValueProps("landscape", pricing(), "best")).toEqual([
      "Color change from your phone",
      "Aircraft aluminum",
      "Lit walkways every night",
    ]);
    expect(serviceValueProps("landscape", pricing(), "essential")).toEqual([
      "Key area coverage",
      "Lit walkways every night",
    ]);
  });

  it("falls back to defaults when a workspace has customized nothing", () => {
    for (const spec of SERVICES) {
      const props = serviceValueProps(spec.key, null);
      expect(props.length).toBeGreaterThan(0);
      expect(props.every((line) => line.trim().length > 0)).toBe(true);
    }
  });

  it("never repeats a line that is both a package point and a service perk", () => {
    const config = pricing({
      landscape: { perks: ["Color change from your phone", "Lit walkways"] },
    });
    const props = serviceValueProps("landscape", config, "best");
    expect(new Set(props).size).toBe(props.length);
  });
});

describe("clientThemeClass", () => {
  it("dresses a Christmas quote in the holiday palette", () => {
    expect(clientThemeClass(["christmas"])).toBe("cmp-festive");
    expect(clientThemeClass(["landscape", "christmas"])).toBe("cmp-festive");
  });

  it("never shows a landscape or permanent buyer a Christmas page", () => {
    // The whole point: someone buying year-round brass landscape lighting gets
    // the neutral premium base, not evergreen and holly.
    expect(clientThemeClass(["landscape"])).toBe("");
    expect(clientThemeClass(["permanent"])).toBe("");
    expect(clientThemeClass(["landscape", "permanent"])).toBe("");
    expect(clientThemeClass([])).toBe("");
  });
});
