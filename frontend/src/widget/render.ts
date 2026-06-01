/**
 * Widget render layer — pure functions that build the shadow-DOM markup for the
 * `<ai-agent>` element. No state or event wiring lives here; the element wires
 * listeners after injecting this markup, and the {@link WidgetView} controller
 * mutates it in response to state changes.
 */

import type { PrimaryShades } from "@/lib/embed/theme";

import { themeWidgetCss } from "./styles";

export type WidgetMode = "voice" | "chat";

/** Stable element ids used by the markup and the state controller. */
export const WIDGET_ELEMENT_IDS = {
  popup: "popup",
  toggle: "toggle",
  buttonText: "button-text",
  orb: "orb",
  orbGradient: "orb-gradient",
  orbDot: "orb-dot",
} as const;

/**
 * Build the embed iframe URL for a given agent. Voice mode targets the root
 * embed route; chat mode targets the `/chat` sub-route. The iframe always
 * autostarts so opening the popup begins a session.
 */
export function buildEmbedIframeSrc(
  baseUrl: string,
  agentId: string,
  mode: WidgetMode,
  theme: string,
): string {
  const embedPath = mode === "chat" ? `/embed/${agentId}/chat` : `/embed/${agentId}`;
  return `${baseUrl}${embedPath}?theme=${theme}&autostart=true`;
}

export interface WidgetMarkupConfig {
  position: string;
  buttonText: string;
  iframeSrc: string;
  shades: PrimaryShades;
}

/**
 * Produce the full inner HTML for the widget's shadow root, including the
 * scoped `<style>` block (host custom properties + themed rules) and the
 * button/orb/popup structure.
 */
export function buildWidgetMarkup(config: WidgetMarkupConfig): string {
  const { position, buttonText, iframeSrc, shades } = config;
  const ids = WIDGET_ELEMENT_IDS;

  return `
      <style>
        :host {
          --ai-primary: ${shades.primary};
          --ai-primary-60: ${shades.primary60};
          --ai-primary-30: ${shades.primary30};
        }
        ${themeWidgetCss(shades)}
      </style>
      <div class="ai-widget-container ${position}">
        <div class="ai-widget-popup" id="${ids.popup}">
          <iframe
            src="${iframeSrc}"
            allow="microphone"
            title="AI Agent"
          ></iframe>
        </div>
        <div class="ai-widget-button-wrapper">
          <button class="ai-widget-button" id="${ids.toggle}">
            <div class="ai-widget-orb" id="${ids.orb}">
              <div class="ai-widget-orb-gradient" id="${ids.orbGradient}"></div>
              <div class="ai-widget-orb-inner"></div>
              <div class="ai-widget-orb-dot" id="${ids.orbDot}"></div>
            </div>
            <span id="${ids.buttonText}">${buttonText}</span>
          </button>
        </div>
      </div>
    `;
}
