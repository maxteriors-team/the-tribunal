/**
 * Widget view controller — owns the imperative DOM mutations that respond to
 * widget state changes (open/close, agent state, audio level). It operates over
 * a shadow root populated by {@link buildWidgetMarkup} and keeps no markup of
 * its own, which makes the open/state/audio-level behavior unit-testable in
 * isolation from the custom-element lifecycle.
 */

import type { EmbedAgentState } from "@/lib/embed/messaging";
import { postToFrame } from "@/lib/embed/messaging";

import { WIDGET_ELEMENT_IDS } from "./render";

const STATE_CLASSES = [
  "state-idle",
  "state-listening",
  "state-thinking",
  "state-speaking",
] as const;

export interface WidgetViewState {
  isOpen: boolean;
  agentState: EmbedAgentState;
}

export class WidgetView {
  private isOpen = false;
  private agentState: EmbedAgentState = "idle";

  constructor(
    private readonly root: ShadowRoot,
    /** The label shown on the toggle button when the popup is closed. */
    private readonly defaultButtonText: string,
  ) {}

  get state(): WidgetViewState {
    return { isOpen: this.isOpen, agentState: this.agentState };
  }

  private el(id: string): HTMLElement | null {
    return this.root.getElementById(id);
  }

  /**
   * Toggle the popup open/closed. On open, signals the embedded iframe to start
   * a session; on close, resets the agent state to idle. Returns the new open
   * state.
   */
  toggle(): boolean {
    this.isOpen = !this.isOpen;

    const ids = WIDGET_ELEMENT_IDS;
    const popup = this.el(ids.popup);
    const buttonText = this.el(ids.buttonText);
    const orbGradient = this.el(ids.orbGradient);
    const orbDot = this.el(ids.orbDot);
    const iframe = popup?.querySelector("iframe") ?? null;

    popup?.classList.toggle("open", this.isOpen);
    if (buttonText) {
      buttonText.textContent = this.isOpen ? "Close" : this.defaultButtonText;
    }
    orbGradient?.classList.toggle("animated", this.isOpen);
    orbDot?.classList.toggle("active", this.isOpen);

    if (this.isOpen) {
      postToFrame(iframe, { type: "ai-agent:start" });
    } else {
      this.setAgentState("idle");
    }

    return this.isOpen;
  }

  /** Apply the visual treatment for a coarse agent state to the toggle button. */
  setAgentState(state: EmbedAgentState): void {
    this.agentState = state;
    const button = this.el(WIDGET_ELEMENT_IDS.toggle);
    if (!button) return;

    button.classList.remove(...STATE_CLASSES);
    if (state !== "idle") {
      button.classList.add(`state-${state}`);
    }
  }

  /**
   * Reflect a smoothed audio level (0–1) onto the orb scale and, while the
   * agent is speaking, the button glow. No-op when the popup is closed.
   */
  setAudioLevel(level: number): void {
    if (!this.isOpen) return;

    const orb = this.el(WIDGET_ELEMENT_IDS.orb);
    if (orb) {
      orb.style.transform = `scale(${1 + level * 0.2})`;
    }

    if (this.agentState === "speaking") {
      const button = this.el(WIDGET_ELEMENT_IDS.toggle);
      if (button) {
        const glowSize = 12 + level * 12;
        const glowOpacity = 0.4 + level * 0.4;
        button.style.boxShadow = `0 4px 24px rgba(0, 0, 0, 0.15), 0 0 ${glowSize}px ${glowSize / 2}px rgba(59, 130, 246, ${glowOpacity})`;
      }
    }
  }
}
