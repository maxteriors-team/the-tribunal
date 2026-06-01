/**
 * AI Agent Widget - Standalone Web Component
 *
 * This script creates a floating AI agent widget that can be embedded on any website.
 * Supports both voice and chat modes.
 *
 * Usage:
 *   <script src="https://yourapp.com/widget/v1/widget.js" defer></script>
 *   <ai-agent agent-id="ag_xK9mN2pQ" mode="voice"></ai-agent>
 *
 * This file is the custom-element shell. The substance lives in focused modules:
 *   - `./styles`              — CSS text + primary-color baking
 *   - `./render`              — pure shadow-DOM markup + iframe src builder
 *   - `./view`               — imperative open/state/audio-level DOM controller
 *   - `@/lib/embed/messaging` — typed postMessage protocol (origin rationale)
 *   - `@/lib/embed/theme`     — color math + theme-option resolution
 */

import {
  subscribeToEmbedMessages,
  type EmbedMessage,
} from "@/lib/embed/messaging";
import { derivePrimaryShades, DEFAULT_PRIMARY_COLOR } from "@/lib/embed/theme";

import { buildEmbedIframeSrc, buildWidgetMarkup, WIDGET_ELEMENT_IDS } from "./render";
import type { WidgetMode } from "./render";
import { WidgetView } from "./view";

class AIAgentElement extends HTMLElement {
  private shadow: ShadowRoot;
  private agentId: string | null = null;
  private position = "bottom-right";
  private theme = "auto";
  private buttonText = "Talk to AI";
  private baseUrl = "";
  private primaryColor = DEFAULT_PRIMARY_COLOR;
  private mode: WidgetMode = "voice";
  private view: WidgetView | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor() {
    super();
    this.shadow = this.attachShadow({ mode: "open" });
  }

  static get observedAttributes() {
    return [
      "agent-id",
      "position",
      "theme",
      "button-text",
      "base-url",
      "primary-color",
      "mode",
    ];
  }

  attributeChangedCallback(name: string, _oldValue: string, newValue: string) {
    switch (name) {
      case "agent-id":
        this.agentId = newValue;
        break;
      case "position":
        this.position = newValue || "bottom-right";
        break;
      case "theme":
        this.theme = newValue || "auto";
        break;
      case "button-text":
        this.buttonText = newValue || "Talk to AI";
        break;
      case "base-url":
        this.baseUrl = newValue || "";
        break;
      case "primary-color":
        this.primaryColor = newValue || DEFAULT_PRIMARY_COLOR;
        break;
      case "mode":
        this.mode = (newValue as WidgetMode) || "voice";
        break;
    }
    if (this.isConnected) {
      this.render();
    }
  }

  connectedCallback() {
    this.agentId = this.getAttribute("agent-id");
    this.position = this.getAttribute("position") ?? "bottom-right";
    this.theme = this.getAttribute("theme") ?? "auto";
    this.buttonText = this.getAttribute("button-text") ?? "Talk to AI";
    this.baseUrl = this.getAttribute("base-url") ?? this.detectBaseUrl();
    this.primaryColor = this.getAttribute("primary-color") ?? DEFAULT_PRIMARY_COLOR;
    this.mode = (this.getAttribute("mode") as WidgetMode) ?? "voice";

    this.render();

    this.unsubscribe = subscribeToEmbedMessages((message) =>
      this.handleMessage(message),
    );
  }

  disconnectedCallback() {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.view = null;
  }

  private detectBaseUrl(): string {
    const scripts = document.getElementsByTagName("script");
    for (const script of scripts) {
      if (script.src?.includes("widget")) {
        try {
          const url = new URL(script.src);
          return `${url.protocol}//${url.host}`;
        } catch {
          // Ignore parse errors
        }
      }
    }
    return window.location.origin;
  }

  private render() {
    if (!this.agentId) {
      if (process.env.NODE_ENV !== "production") {
        console.error("AIAgent: agent-id attribute is required");
      }
      return;
    }

    const shades = derivePrimaryShades(this.primaryColor);
    const iframeSrc = buildEmbedIframeSrc(
      this.baseUrl,
      this.agentId,
      this.mode,
      this.theme,
    );

    this.shadow.innerHTML = buildWidgetMarkup({
      position: this.position,
      buttonText: this.buttonText,
      iframeSrc,
      shades,
    });

    this.view = new WidgetView(this.shadow, this.buttonText);
    this.shadow
      .getElementById(WIDGET_ELEMENT_IDS.toggle)
      ?.addEventListener("click", () => this.view?.toggle());
  }

  private handleMessage(message: EmbedMessage) {
    if (!this.view) return;

    switch (message.type) {
      case "ai-agent:close":
        if (this.view.state.isOpen) {
          this.view.toggle();
        }
        break;
      case "ai-agent:state":
        this.view.setAgentState(message.state);
        break;
      case "ai-agent:audio-level":
        this.view.setAudioLevel(message.level);
        break;
      // "ai-agent:start" is host → iframe only; ignored here.
    }
  }
}

// Register the custom element
if (!customElements.get("ai-agent")) {
  customElements.define("ai-agent", AIAgentElement);
}

// Export for module usage
export { AIAgentElement };
