/**
 * Widget stylesheet.
 *
 * The CSS is authored once with `var(--ai-primary, …)` fallbacks so it reads
 * naturally, then {@link themeWidgetCss} bakes a concrete primary color (and its
 * translucent shades) into the rule text. We bake rather than rely purely on the
 * custom properties because some embedding pages set conflicting globals; the
 * literal values guarantee the orb gradient renders with the configured color.
 */

import type { PrimaryShades } from "@/lib/embed/theme";

export const WIDGET_CSS = `
  .ai-widget-container {
    position: fixed;
    z-index: 9999;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }

  .ai-widget-container.bottom-right {
    bottom: 20px;
    right: 20px;
  }

  .ai-widget-container.bottom-left {
    bottom: 20px;
    left: 20px;
  }

  .ai-widget-container.top-right {
    top: 20px;
    right: 20px;
  }

  .ai-widget-container.top-left {
    top: 20px;
    left: 20px;
  }

  .ai-widget-button {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 20px;
    background: var(--ai-primary, #6366f1);
    color: white;
    border: none;
    border-radius: 50px;
    cursor: pointer;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
    transition: all 0.3s ease;
    font-size: 14px;
    font-weight: 500;
  }

  .ai-widget-button:hover {
    transform: scale(1.05);
    box-shadow: 0 6px 32px rgba(0, 0, 0, 0.2);
  }

  .ai-widget-button:active {
    transform: scale(0.98);
  }

  .ai-widget-button svg {
    width: 18px;
    height: 18px;
  }

  .ai-widget-orb {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    position: relative;
    overflow: hidden;
    transition: transform 0.2s ease;
  }

  .ai-widget-orb-gradient {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: conic-gradient(
      from 180deg,
      var(--ai-primary, #6366f1) 0deg,
      var(--ai-primary-60, #6366f188) 90deg,
      var(--ai-primary-30, #6366f144) 180deg,
      var(--ai-primary-60, #6366f188) 270deg,
      var(--ai-primary, #6366f1) 360deg
    );
    transition: opacity 0.3s ease;
  }

  .ai-widget-orb-gradient.animated {
    animation: ai-spin 3s linear infinite;
  }

  .ai-widget-orb-inner {
    position: absolute;
    inset: 3px;
    border-radius: 50%;
    background: white;
    transition: background-color 0.3s ease;
  }

  .ai-widget-orb-dot {
    position: absolute;
    inset: 6px;
    border-radius: 50%;
    background: var(--ai-primary, #6366f1);
    opacity: 0.4;
    transition: all 0.2s ease;
  }

  .ai-widget-orb-dot.active {
    opacity: 0.8;
    transform: scale(1.1);
  }

  /* State-based styling */
  .ai-widget-button.state-listening {
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15), 0 0 12px 4px rgba(34, 197, 94, 0.4);
  }

  .ai-widget-button.state-listening .ai-widget-orb-dot {
    background: #22c55e;
    opacity: 0.9;
    animation: ai-pulse 1.5s ease-in-out infinite;
  }

  .ai-widget-button.state-thinking {
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15), 0 0 12px 4px rgba(251, 191, 36, 0.4);
  }

  .ai-widget-button.state-thinking .ai-widget-orb-dot {
    background: #fbbf24;
    opacity: 0.9;
    animation: ai-think-pulse 0.8s ease-in-out infinite;
  }

  .ai-widget-button.state-speaking {
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15), 0 0 12px 4px rgba(59, 130, 246, 0.4);
  }

  .ai-widget-button.state-speaking .ai-widget-orb-dot {
    background: #3b82f6;
    opacity: 0.9;
    animation: ai-speak-pulse 0.3s ease-in-out infinite;
  }

  .ai-widget-popup {
    position: absolute;
    bottom: 60px;
    right: 0;
    width: 380px;
    height: 520px;
    background: transparent;
    border-radius: 16px;
    overflow: hidden;
    opacity: 0;
    transform: translateY(20px) scale(0.95);
    transition: all 0.3s ease;
    pointer-events: none;
  }

  .ai-widget-popup.open {
    opacity: 1;
    transform: translateY(0) scale(1);
    pointer-events: auto;
  }

  .ai-widget-popup iframe {
    width: 100%;
    height: 100%;
    border: none;
    border-radius: 16px;
  }

  .ai-widget-branding {
    text-align: center;
    font-size: 11px;
    color: #9ca3af;
    margin-top: 8px;
  }

  .ai-widget-branding a {
    color: var(--ai-primary, #6366f1);
    text-decoration: none;
  }

  @keyframes ai-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @keyframes ai-pulse {
    0%, 100% { transform: scale(1); opacity: 0.9; }
    50% { transform: scale(1.15); opacity: 1; }
  }

  @keyframes ai-think-pulse {
    0%, 100% { transform: scale(1); opacity: 0.7; }
    50% { transform: scale(1.1); opacity: 1; }
  }

  @keyframes ai-speak-pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.2); }
  }

  @media (max-width: 480px) {
    .ai-widget-popup {
      position: fixed;
      inset: 0;
      width: 100%;
      height: 100%;
      border-radius: 0;
      bottom: 0;
      right: 0;
    }
    .ai-widget-popup iframe {
      border-radius: 0;
    }
  }
`;

/**
 * Bake concrete primary-color values into {@link WIDGET_CSS}, replacing the
 * `var(--ai-primary*, …)` fallbacks with the supplied shades.
 */
export function themeWidgetCss(shades: PrimaryShades): string {
  return WIDGET_CSS.replace(/var\(--ai-primary, #6366f1\)/g, shades.primary)
    .replace(/var\(--ai-primary-60, #6366f188\)/g, shades.primary60)
    .replace(/var\(--ai-primary-30, #6366f144\)/g, shades.primary30);
}
