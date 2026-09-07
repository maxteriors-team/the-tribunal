/**
 * Map validated workspace primary/accent colors onto the public proposal theme.
 * Raw colors remain available for decorative rules. Text and controls use the
 * accent, then the primary, only after it clears contrast against the real dark
 * background. Unusable text colors leave the theme's safe default untouched.
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

/** Keep the subdued text accent as dark as possible without losing AA contrast. */
function readableDarkAccent(rgb: RGB): RGB {
  for (let step = 30; step >= 0; step -= 1) {
    const candidate = mix(rgb, 0, step / 100);
    if (contrast(candidate, PAGE_BACKGROUND) >= MIN_CONTRAST) return candidate;
  }
  return rgb;
}

/**
 * Validated workspace brand variables. Raw colors are decorative only; readable
 * accent variables paint text, controls, and focus indicators on the dark page.
 */
export function proposalAccentVars(
  primaryColor: string | null | undefined,
  accentColor?: string | null,
): CSSProperties {
  const primary = parseHex(primaryColor ?? "");
  const accent = parseHex(accentColor ?? "");
  const readableAccent = (accent && toReadable(accent)) || (primary && toReadable(primary));
  const variables: Record<string, string> = {};

  if (primary) variables["--brand-primary"] = toHex(primary);
  if (accent) variables["--brand-accent"] = toHex(accent);
  if (readableAccent) {
    const [r, g, b] = readableAccent.map(toChannel) as RGB;
    variables["--gold"] = toHex(readableAccent);
    variables["--gold-l"] = toHex(mix(readableAccent, 255, 0.45));
    variables["--gold-d"] = toHex(readableDarkAccent(readableAccent));
    variables["--gold-g"] = `rgba(${r}, ${g}, ${b}, 0.1)`;
    variables["--bdr-g"] = `rgba(${r}, ${g}, ${b}, 0.3)`;
  }

  return variables as CSSProperties;
}
