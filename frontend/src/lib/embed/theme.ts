/**
 * Theme helpers for every embed surface — the standalone widget custom element
 * and the React embed routes (`/embed/<publicId>/…`).
 *
 * This is the single home for:
 *  - the light/dark palette (`EmbedTheme`) consumed by the React embed pages,
 *  - agent-state accent colors (`getAgentStateInfo`),
 *  - color math (`hexToHsl`, `derivePrimaryShades`) used to theme the widget orb,
 *  - and theme-option resolution (`parseThemeOption`, `resolveThemeOption`)
 *    shared by the widget and the React `useResolvedTheme` hook.
 */

export type ThemeOption = "light" | "dark" | "auto";
export type ResolvedTheme = "light" | "dark";

export const DEFAULT_PRIMARY_COLOR = "#6366f1";

export interface EmbedTheme {
  isDark: boolean;
  // Surface backgrounds
  pageBg: string;
  panelBg: string;
  panelOverlayBg: string;
  messagesBg: string;
  inputBg: string;
  inputBorder: string;
  bubbleAssistantBg: string;
  bubbleAssistantText: string;
  // Borders
  panelBorder: string;
  // Text
  text: string;
  textMuted: string;
  textOnPrimary: string;
  // Voice-state pill / icons
  iconBg: string;
  iconColor: string;
  // Shadows
  bubbleShadow: string;
}

const LIGHT: EmbedTheme = {
  isDark: false,
  pageBg: "#f9fafb",
  panelBg: "#ffffff",
  panelOverlayBg: "rgba(255, 255, 255, 0.95)",
  messagesBg: "#f9fafb",
  inputBg: "#f3f4f6",
  inputBorder: "#e5e7eb",
  bubbleAssistantBg: "#ffffff",
  bubbleAssistantText: "#1f2937",
  panelBorder: "#e5e7eb",
  text: "#1f2937",
  textMuted: "#6b7280",
  textOnPrimary: "#ffffff",
  iconBg: "#e5e7eb",
  iconColor: "#4b5563",
  bubbleShadow: "0 1px 2px rgba(0,0,0,0.1)",
};

const DARK: EmbedTheme = {
  isDark: true,
  pageBg: "#111827",
  panelBg: "#1f2937",
  panelOverlayBg: "rgba(17, 24, 39, 0.95)",
  messagesBg: "#111827",
  inputBg: "#374151",
  inputBorder: "#4b5563",
  bubbleAssistantBg: "#374151",
  bubbleAssistantText: "#f3f4f6",
  panelBorder: "#374151",
  text: "#f3f4f6",
  textMuted: "#9ca3af",
  textOnPrimary: "#ffffff",
  iconBg: "#374151",
  iconColor: "#d1d5db",
  bubbleShadow: "0 1px 2px rgba(0,0,0,0.3)",
};

export function getEmbedTheme(isDark: boolean): EmbedTheme {
  return isDark ? DARK : LIGHT;
}

/**
 * Agent state colors (status pill / center orb). Used by the visualizer in the
 * root embed page and the header pill in the others.
 */
export interface AgentStateInfo {
  color: string;
  label: string;
}

export function getAgentStateInfo(
  agentState: "idle" | "listening" | "thinking" | "speaking",
  primaryColor: string,
  idleLabel: string = "Ready",
): AgentStateInfo {
  switch (agentState) {
    case "listening":
      return { color: "#22c55e", label: "Listening" };
    case "thinking":
      return { color: "#f59e0b", label: "Thinking" };
    case "speaking":
      return { color: "#3b82f6", label: "Speaking" };
    default:
      return { color: primaryColor, label: idleLabel };
  }
}

export interface Hsl {
  h: number;
  s: number;
  l: number;
}

/**
 * Convert a 6-digit hex color (with or without leading `#`) to HSL. Falls back
 * to a neutral mid-gray for malformed input so the widget never throws while
 * theming.
 */
export function hexToHsl(hex: string): Hsl {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result?.[1] || !result[2] || !result[3]) return { h: 0, s: 0, l: 50 };

  const r = parseInt(result[1], 16) / 255;
  const g = parseInt(result[2], 16) / 255;
  const b = parseInt(result[3], 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r:
        h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        break;
      case g:
        h = ((b - r) / d + 2) / 6;
        break;
      case b:
        h = ((r - g) / d + 4) / 6;
        break;
    }
  }

  return {
    h: Math.round(h * 360),
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
}

export interface PrimaryShades {
  primary: string;
  /** ~53% alpha variant for the conic gradient mid-stop. */
  primary60: string;
  /** ~27% alpha variant for the conic gradient outer-stop. */
  primary30: string;
}

/**
 * Derive the translucent primary-color shades the widget orb's conic gradient
 * needs from a single base hex color.
 */
export function derivePrimaryShades(primaryColor: string): PrimaryShades {
  const hsl = hexToHsl(primaryColor);
  return {
    primary: primaryColor,
    primary60: `hsla(${hsl.h}, ${hsl.s}%, ${hsl.l}%, 0.53)`,
    primary30: `hsla(${hsl.h}, ${hsl.s}%, ${hsl.l}%, 0.27)`,
  };
}

/** Normalize an arbitrary (often query-param) value to a valid `ThemeOption`. */
export function parseThemeOption(value: unknown): ThemeOption {
  return value === "light" || value === "dark" ? value : "auto";
}

/**
 * Resolve a `"light" | "dark" | "auto"` preference into a concrete theme given
 * the current system dark-mode preference. Pure — callers supply `prefersDark`
 * (e.g. from `matchMedia`) so this stays framework- and DOM-agnostic.
 */
export function resolveThemeOption(theme: ThemeOption, prefersDark: boolean): ResolvedTheme {
  if (theme === "auto") return prefersDark ? "dark" : "light";
  return theme;
}
