import { describe, expect, it } from "vitest";

import {
  seasonalIconForCategory,
  seasonalIconForStyle,
  tintSurface,
} from "./seasonal-icons";
import type { RenderStyle } from "./types";

// The workspace decor category keys shown on a quote (mirrors the seeded
// christmas catalog) plus the built-in roofline pseudo-category.
const CATEGORY_KEYS = [
  "roofline",
  "wreaths",
  "trees",
  "bushes",
  "garland",
  "mini_lights",
] as const;

const RENDER_STYLES: RenderStyle[] = [
  "c9",
  "mini",
  "garland",
  "stake",
  "wreath",
  "treewrap",
  "permanent",
];

describe("seasonalIconForCategory", () => {
  it("returns a renderable icon, tint, and label for every category", () => {
    for (const key of CATEGORY_KEYS) {
      const spec = seasonalIconForCategory(key);
      expect(["function", "object"]).toContain(typeof spec.Icon);
      expect(spec.tint).toMatch(/^#[0-9a-f]{6}$/i);
      expect(spec.label.length).toBeGreaterThan(0);
    }
  });

  it("gives visually distinct icons and tints across categories", () => {
    const icons = new Set(CATEGORY_KEYS.map((k) => seasonalIconForCategory(k).Icon));
    const tints = new Set(CATEGORY_KEYS.map((k) => seasonalIconForCategory(k).tint));
    // Each of the six customer-facing options must look different at a glance.
    expect(icons.size).toBe(CATEGORY_KEYS.length);
    expect(tints.size).toBe(CATEGORY_KEYS.length);
  });

  it("falls back to the roofline spec for an unknown category", () => {
    expect(seasonalIconForCategory("nope")).toEqual(
      seasonalIconForCategory("roofline"),
    );
  });

  it("maps wreaths and trees to different specs", () => {
    expect(seasonalIconForCategory("wreaths").Icon).not.toBe(
      seasonalIconForCategory("trees").Icon,
    );
  });
});

describe("seasonalIconForStyle", () => {
  it("resolves every render style to a valid spec", () => {
    for (const style of RENDER_STYLES) {
      const spec = seasonalIconForStyle(style);
      expect(["function", "object"]).toContain(typeof spec.Icon);
      expect(spec.tint).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("agrees with the category resolver for shared types (c9 → roofline)", () => {
    expect(seasonalIconForStyle("c9")).toEqual(
      seasonalIconForCategory("roofline"),
    );
    expect(seasonalIconForStyle("treewrap")).toEqual(
      seasonalIconForCategory("trees"),
    );
  });
});

describe("tintSurface", () => {
  it("appends a low-alpha channel to the tint hex", () => {
    expect(tintSurface("#d9a441")).toBe("#d9a44122");
  });
});
