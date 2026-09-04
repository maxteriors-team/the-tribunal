import { describe, expect, it } from "vitest";

import { proposalAccentVars } from "./proposal-brand";

/** The `--gold` value applied for `brandColor`, or undefined when untouched. */
function accentColor(brandColor: string): string | undefined {
  return (proposalAccentVars(brandColor) as Record<string, string>)["--gold"];
}

describe("proposalAccentVars", () => {
  it("passes through a brand color that is already readable, unchanged", () => {
    // Maxteriors amber, sampled from the logo: 11:1, needs no adjustment.
    expect(proposalAccentVars("#FCB400")).toEqual({
      "--gold": "#fcb400",
      "--gold-l": "#fdd673",
      "--gold-d": "#b07e00",
      "--gold-g": "rgba(252, 180, 0, 0.1)",
      "--bdr-g": "rgba(252, 180, 0, 0.3)",
    });
  });

  it("keeps a dim brand color's hue, lightening it only until it is readable", () => {
    // The green 76 real workspaces use. At 3.73:1 it is too dim for the 11px
    // text this accent paints, but discarding it would strip their branding
    // entirely — so it is lightened the minimum needed (~16%) and stays green.
    const green = accentColor("#0A7C3A");
    expect(green).toBe("#31915a");

    // Still recognizably the same hue: green dominant, red still lowest.
    const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt((green ?? "").slice(i, i + 2), 16));
    expect(g).toBeGreaterThan(r);
    expect(g).toBeGreaterThan(b);
  });

  it("keeps the theme default for the near-black API default brand color", () => {
    // Every workspace that never customized branding reads back `#0F172A`. It
    // would need 42% lightening to be readable and would land on grey, so it is
    // left alone rather than invented into a color nobody chose.
    expect(proposalAccentVars("#0F172A")).toEqual({});
  });

  it("keeps the theme default for any color too dark to rescue", () => {
    // Each needs more than the lightening cap and would end up grey, not brand.
    // `#304854` is the logo's own dark teal (2.06:1, needs 28%): a real brand
    // color that still cannot serve as an accent on a near-black page, which is
    // exactly the case the cap exists to catch.
    for (const tooDark of ["#000000", "#1a1a1a", "#111111", "#304854", "#8B0000"]) {
      expect(proposalAccentVars(tooDark)).toEqual({});
    }
  });

  it("applies light and mid-tone colors that need no or little help", () => {
    for (const readable of ["#d4af5a", "#ffffff", "#FCB400", "#2563EB", "#7C3AED"]) {
      expect(accentColor(readable)).toBeDefined();
    }
  });

  it("guarantees every applied accent clears the readability floor", () => {
    // The property that actually matters, independent of any single value:
    // whatever this returns must be readable on the near-black page.
    const luminance = (rgb: number[]) => {
      const [r, g, b] = rgb.map((channel) => {
        const c = channel / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const surfaceLuminance = luminance([24, 24, 24]);

    for (const candidate of ["#0A7C3A", "#7C3AED", "#2563EB", "#FCB400", "#d4af5a", "#8B0000"]) {
      const applied = proposalAccentVars(candidate) as Record<string, string>;
      for (const variable of ["--gold", "--gold-d"]) {
        const color = applied[variable];
        if (!color) continue;
        const rgb = [1, 3, 5].map((i) => Number.parseInt(color.slice(i, i + 2), 16));
        const ratio =
          (Math.max(luminance(rgb), surfaceLuminance) + 0.05) /
          (Math.min(luminance(rgb), surfaceLuminance) + 0.05);
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("ignores a missing or malformed color instead of throwing", () => {
    for (const bad of [null, undefined, "", "   ", "not-a-color", "#12", "#1234567"]) {
      expect(proposalAccentVars(bad)).toEqual({});
    }
  });

  it("accepts shorthand hex and is case-insensitive", () => {
    expect(proposalAccentVars("#FC0")["--gold" as keyof object]).toBe("#ffcc00");
    expect(proposalAccentVars("#fcb400")).toEqual(proposalAccentVars("#FCB400"));
  });
});
