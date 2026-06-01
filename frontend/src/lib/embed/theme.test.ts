import { describe, expect, it } from "vitest";

import {
  DEFAULT_PRIMARY_COLOR,
  derivePrimaryShades,
  getAgentStateInfo,
  getEmbedTheme,
  hexToHsl,
  parseThemeOption,
  resolveThemeOption,
} from "@/lib/embed/theme";

describe("getEmbedTheme", () => {
  it("returns the dark palette when isDark is true", () => {
    const dark = getEmbedTheme(true);
    expect(dark.isDark).toBe(true);
    expect(dark.pageBg).toBe("#111827");
  });

  it("returns the light palette when isDark is false", () => {
    const light = getEmbedTheme(false);
    expect(light.isDark).toBe(false);
    expect(light.pageBg).toBe("#f9fafb");
  });
});

describe("getAgentStateInfo", () => {
  it("maps each active state to its accent color and label", () => {
    expect(getAgentStateInfo("listening", "#000")).toEqual({
      color: "#22c55e",
      label: "Listening",
    });
    expect(getAgentStateInfo("thinking", "#000")).toEqual({
      color: "#f59e0b",
      label: "Thinking",
    });
    expect(getAgentStateInfo("speaking", "#000")).toEqual({
      color: "#3b82f6",
      label: "Speaking",
    });
  });

  it("falls back to the primary color and idle label when idle", () => {
    expect(getAgentStateInfo("idle", "#abcdef")).toEqual({
      color: "#abcdef",
      label: "Ready",
    });
  });

  it("honors a custom idle label", () => {
    expect(getAgentStateInfo("idle", "#abcdef", "Voice active").label).toBe("Voice active");
  });
});

describe("hexToHsl", () => {
  it("converts primary brand color", () => {
    // #6366f1 ≈ hsl(243, 75%, 59%)
    const hsl = hexToHsl(DEFAULT_PRIMARY_COLOR);
    expect(hsl.h).toBeGreaterThanOrEqual(238);
    expect(hsl.h).toBeLessThanOrEqual(248);
    expect(hsl.s).toBeGreaterThan(60);
    expect(hsl.l).toBeGreaterThan(50);
  });

  it("handles colors without a leading hash", () => {
    expect(hexToHsl("ffffff")).toEqual({ h: 0, s: 0, l: 100 });
    expect(hexToHsl("000000")).toEqual({ h: 0, s: 0, l: 0 });
  });

  it("returns a neutral gray for malformed input", () => {
    expect(hexToHsl("not-a-color")).toEqual({ h: 0, s: 0, l: 50 });
    expect(hexToHsl("#fff")).toEqual({ h: 0, s: 0, l: 50 });
  });
});

describe("derivePrimaryShades", () => {
  it("returns the base color and two translucent hsla variants", () => {
    const shades = derivePrimaryShades(DEFAULT_PRIMARY_COLOR);
    expect(shades.primary).toBe(DEFAULT_PRIMARY_COLOR);
    expect(shades.primary60).toMatch(/^hsla\(\d+, \d+%, \d+%, 0\.53\)$/);
    expect(shades.primary30).toMatch(/^hsla\(\d+, \d+%, \d+%, 0\.27\)$/);
  });
});

describe("parseThemeOption", () => {
  it("passes through explicit light and dark", () => {
    expect(parseThemeOption("light")).toBe("light");
    expect(parseThemeOption("dark")).toBe("dark");
  });

  it("falls back to auto for anything else", () => {
    expect(parseThemeOption("auto")).toBe("auto");
    expect(parseThemeOption(null)).toBe("auto");
    expect(parseThemeOption(undefined)).toBe("auto");
    expect(parseThemeOption("rainbow")).toBe("auto");
  });
});

describe("resolveThemeOption", () => {
  it("returns the explicit option regardless of system preference", () => {
    expect(resolveThemeOption("light", true)).toBe("light");
    expect(resolveThemeOption("dark", false)).toBe("dark");
  });

  it("resolves auto from the system dark preference", () => {
    expect(resolveThemeOption("auto", true)).toBe("dark");
    expect(resolveThemeOption("auto", false)).toBe("light");
  });
});
