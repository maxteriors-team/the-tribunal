/**
 * Map a workspace's configured `brand_color` onto the proposal theme's accent
 * variables, so the client page renders in the operator's brand rather than the
 * built-in gold.
 *
 * `proposal-theme.css` declares these on `.proposal-view`; the object returned
 * here is spread onto that element's `style` so it overrides them per render.
 *
 * The page is near-black and the accent paints text as small as 11px, so a dark
 * brand color would be unreadable rather than merely off-key. Instead of
 * discarding such a color, this preserves the operator's hue and lightens it
 * just enough to clear the contrast floor — measured against the real data, the
 * brand colors in use need 11–15% lightening and stay recognizably themselves.
 *
 * Past a cap the result is no longer the brand (a near-black slate lightens into
 * grey mush), so those keep the built-in gold. That is why this returns an empty
 * object rather than a fallback color: it means "leave the theme alone".
 */
import type { CSSProperties } from "react";

/** `.proposal-view` background (`--black` in proposal-theme.css). */
const PAGE_BACKGROUND: RGB = [10, 10, 10];

/**
 * Minimum contrast against the page background.
 *
 * 4.5:1 is the WCAG AA floor for normal-size text, which is what this accent
 * actually paints: 43 rules colour text with it, the smallest at 11px, 13px and
 * 17px. The 3:1 large-text/non-text floor would pass colours that are genuinely
 * hard to read at those sizes.
 */
const MIN_CONTRAST = 4.5;

/**
 * Most a colour may be lightened toward white while still being "their brand".
 *
 * Measured: the two brand colours in use need 0.11 and 0.15, while the
 * uncustomized API default (`#0F172A`) would need 0.42 and land on grey. The cap
 * separates the two cases without hard-coding the sentinel value.
 */
const MAX_LIGHTEN = 0.25;

type RGB = [number, number, number];

function parseHex(value: string): RGB | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim());
  if (!match) return null;
  const hex =
    match[1].length === 3
      ? match[1]
          .split("")
          .map((char) => char + char)
          .join("")
      : match[1];
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16),
  ];
}

const toChannel = (value: number) => Math.max(0, Math.min(255, Math.round(value)));

const toHex = (rgb: RGB) =>
  `#${rgb.map((channel) => toChannel(channel).toString(16).padStart(2, "0")).join("")}`;

/** Blend toward `target` (0 = black, 255 = white) by `amount` (0..1). */
const mix = (rgb: RGB, target: number, amount: number): RGB =>
  rgb.map((channel) => channel + (target - channel) * amount) as RGB;

/** WCAG relative luminance. */
function luminance([r, g, b]: RGB): number {
  const [lr, lg, lb] = [r, g, b].map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function contrast(a: RGB, b: RGB): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/**
 * Lighten `rgb` the least amount that clears {@link MIN_CONTRAST}, or `null`
 * when that needs more than {@link MAX_LIGHTEN}.
 */
function toReadable(rgb: RGB): RGB | null {
  if (contrast(rgb, PAGE_BACKGROUND) >= MIN_CONTRAST) return rgb;
  // 1% steps: fine enough to be visually minimal, cheap enough to just scan.
  for (let step = 1; step <= MAX_LIGHTEN * 100; step += 1) {
    const candidate = mix(rgb, 255, step / 100);
    if (contrast(candidate, PAGE_BACKGROUND) >= MIN_CONTRAST) return candidate;
  }
  return null;
}

/**
 * Accent CSS variables for `brandColor`, or `{}` to keep the theme default when
 * the color is missing, malformed, or too dark to make readable on the page.
 */
export function proposalAccentVars(brandColor: string | null | undefined): CSSProperties {
  const parsed = parseHex(brandColor ?? "");
  const accent = parsed && toReadable(parsed);
  if (!accent) return {};

  const [r, g, b] = accent.map(toChannel) as RGB;
  return {
    "--gold": toHex(accent),
    "--gold-l": toHex(mix(accent, 255, 0.45)),
    "--gold-d": toHex(mix(accent, 0, 0.3)),
    "--gold-g": `rgba(${r}, ${g}, ${b}, 0.1)`,
    "--bdr-g": `rgba(${r}, ${g}, ${b}, 0.3)`,
  } as CSSProperties;
}
