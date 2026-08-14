export interface FixtureMarkerColor {
  name: string;
  value: string;
  darkForeground?: boolean;
}

/**
 * Shared plan-marker palette for the landscape drawing toolbar and fixture inspector.
 * Names are part of the accessible control label; values remain stable in saved drafts.
 */
export const FIXTURE_MARKER_COLORS: readonly FixtureMarkerColor[] = [
  { name: "Black", value: "#1f2933" },
  { name: "Yellow", value: "#f2c94c", darkForeground: true },
  { name: "Amber", value: "#f2994a", darkForeground: true },
  { name: "Red", value: "#eb5757" },
  { name: "Blue", value: "#2f80ed" },
  { name: "Green", value: "#27ae60" },
  { name: "White", value: "#ffffff", darkForeground: true },
  { name: "Purple", value: "#9b51e0" },
  { name: "Pink", value: "#d62f6f" },
  { name: "Cyan", value: "#35aee2", darkForeground: true },
  { name: "Brown", value: "#8d6e63" },
  { name: "Lime", value: "#8bc34a", darkForeground: true },
  { name: "Slate", value: "#6b7d86" },
  { name: "Coral", value: "#f26b4f", darkForeground: true },
  { name: "Orange", value: "#ff7a45", darkForeground: true },
  { name: "Teal", value: "#008f85" },
];

export const DEFAULT_FIXTURE_MARKER_COLOR = "#eb5757";
