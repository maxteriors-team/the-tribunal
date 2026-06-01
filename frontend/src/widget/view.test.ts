import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { derivePrimaryShades } from "@/lib/embed/theme";
import { buildEmbedIframeSrc, buildWidgetMarkup, WIDGET_ELEMENT_IDS } from "@/widget/render";
import { WidgetView } from "@/widget/view";

const DEFAULT_BUTTON_TEXT = "Talk to AI";

/** Mount the widget markup into a real shadow root for the controller to drive. */
function mountView(buttonText = DEFAULT_BUTTON_TEXT): {
  host: HTMLElement;
  shadow: ShadowRoot;
  view: WidgetView;
} {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = buildWidgetMarkup({
    position: "bottom-right",
    buttonText,
    iframeSrc: buildEmbedIframeSrc("https://app.example", "ag_test", "voice", "auto"),
    shades: derivePrimaryShades("#6366f1"),
  });
  return { host, shadow, view: new WidgetView(shadow, buttonText) };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("buildEmbedIframeSrc", () => {
  it("targets the root embed route in voice mode", () => {
    expect(buildEmbedIframeSrc("https://app.example", "ag_1", "voice", "dark")).toBe(
      "https://app.example/embed/ag_1?theme=dark&autostart=true",
    );
  });

  it("targets the /chat route in chat mode", () => {
    expect(buildEmbedIframeSrc("https://app.example", "ag_1", "chat", "auto")).toBe(
      "https://app.example/embed/ag_1/chat?theme=auto&autostart=true",
    );
  });
});

describe("buildWidgetMarkup", () => {
  it("includes the toggle, orb, popup, and themed style block", () => {
    const { shadow } = mountView();
    expect(shadow.getElementById(WIDGET_ELEMENT_IDS.toggle)).not.toBeNull();
    expect(shadow.getElementById(WIDGET_ELEMENT_IDS.orb)).not.toBeNull();
    expect(shadow.getElementById(WIDGET_ELEMENT_IDS.popup)).not.toBeNull();
    expect(shadow.querySelector("iframe")).not.toBeNull();
    expect(shadow.querySelector("style")!.textContent).toContain("#6366f1");
  });

  it("uses the requested position class and button text", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = buildWidgetMarkup({
      position: "top-left",
      buttonText: "Chat now",
      iframeSrc: "https://app.example/embed/ag_x?theme=auto&autostart=true",
      shades: derivePrimaryShades("#ff00aa"),
    });
    expect(shadow.querySelector(".ai-widget-container.top-left")).not.toBeNull();
    expect(shadow.getElementById(WIDGET_ELEMENT_IDS.buttonText)!.textContent).toBe("Chat now");
    expect(shadow.querySelector("style")!.textContent).toContain("#ff00aa");
  });
});

describe("WidgetView.toggle", () => {
  it("opens the popup, swaps the label, and posts start into the iframe", () => {
    const { shadow, view } = mountView();
    const popup = shadow.getElementById(WIDGET_ELEMENT_IDS.popup)!;
    const buttonText = shadow.getElementById(WIDGET_ELEMENT_IDS.buttonText)!;
    const iframe = shadow.querySelector("iframe")!;

    // jsdom iframes expose a contentWindow; spy on its postMessage.
    const messages: unknown[] = [];
    Object.defineProperty(iframe, "contentWindow", {
      configurable: true,
      value: { postMessage: (msg: unknown) => messages.push(msg) },
    });

    expect(view.toggle()).toBe(true);
    expect(view.state.isOpen).toBe(true);
    expect(popup.classList.contains("open")).toBe(true);
    expect(buttonText.textContent).toBe("Close");
    expect(messages).toEqual([{ type: "ai-agent:start" }]);
  });

  it("closes the popup, restores the label, and resets state to idle", () => {
    const { shadow, view } = mountView();
    const popup = shadow.getElementById(WIDGET_ELEMENT_IDS.popup)!;
    const buttonText = shadow.getElementById(WIDGET_ELEMENT_IDS.buttonText)!;
    const button = shadow.getElementById(WIDGET_ELEMENT_IDS.toggle)!;

    view.toggle();
    view.setAgentState("speaking");
    expect(button.classList.contains("state-speaking")).toBe(true);

    expect(view.toggle()).toBe(false);
    expect(popup.classList.contains("open")).toBe(false);
    expect(buttonText.textContent).toBe(DEFAULT_BUTTON_TEXT);
    expect(button.classList.contains("state-speaking")).toBe(false);
    expect(view.state.agentState).toBe("idle");
  });
});

describe("WidgetView.setAgentState", () => {
  it("applies exactly one state class and clears prior ones", () => {
    const { shadow, view } = mountView();
    const button = shadow.getElementById(WIDGET_ELEMENT_IDS.toggle)!;

    view.setAgentState("listening");
    expect(button.classList.contains("state-listening")).toBe(true);

    view.setAgentState("thinking");
    expect(button.classList.contains("state-listening")).toBe(false);
    expect(button.classList.contains("state-thinking")).toBe(true);

    view.setAgentState("idle");
    for (const cls of ["state-idle", "state-listening", "state-thinking", "state-speaking"]) {
      expect(button.classList.contains(cls)).toBe(false);
    }
  });
});

describe("WidgetView.setAudioLevel", () => {
  it("does nothing while the popup is closed", () => {
    const { shadow, view } = mountView();
    const orb = shadow.getElementById(WIDGET_ELEMENT_IDS.orb)!;
    view.setAudioLevel(0.8);
    expect(orb.style.transform).toBe("");
  });

  it("scales the orb when open", () => {
    const { shadow, view } = mountView();
    const orb = shadow.getElementById(WIDGET_ELEMENT_IDS.orb)!;
    const iframe = shadow.querySelector("iframe")!;
    Object.defineProperty(iframe, "contentWindow", {
      configurable: true,
      value: { postMessage: () => {} },
    });

    view.toggle();
    view.setAudioLevel(0.5);
    expect(orb.style.transform).toBe("scale(1.1)");
  });

  it("adds the speaking glow to the button only while speaking", () => {
    const { shadow, view } = mountView();
    const button = shadow.getElementById(WIDGET_ELEMENT_IDS.toggle)!;
    const iframe = shadow.querySelector("iframe")!;
    Object.defineProperty(iframe, "contentWindow", {
      configurable: true,
      value: { postMessage: () => {} },
    });

    view.toggle();
    view.setAudioLevel(0.5);
    expect(button.style.boxShadow).toBe("");

    view.setAgentState("speaking");
    view.setAudioLevel(0.5);
    expect(button.style.boxShadow).toContain("rgba(59, 130, 246");
  });
});
