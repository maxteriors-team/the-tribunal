import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EMBED_AGENT_STATES,
  isEmbedAgentState,
  parseEmbedMessage,
  postToFrame,
  postToParent,
  subscribeToEmbedMessages,
  type EmbedMessage,
} from "@/lib/embed/messaging";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("isEmbedAgentState", () => {
  it("accepts the four known states", () => {
    for (const state of EMBED_AGENT_STATES) {
      expect(isEmbedAgentState(state)).toBe(true);
    }
  });

  it("rejects unknown strings and non-strings", () => {
    expect(isEmbedAgentState("bogus")).toBe(false);
    expect(isEmbedAgentState("")).toBe(false);
    expect(isEmbedAgentState(undefined)).toBe(false);
    expect(isEmbedAgentState(3)).toBe(false);
    expect(isEmbedAgentState(null)).toBe(false);
  });
});

describe("parseEmbedMessage", () => {
  it("parses start and close lifecycle messages", () => {
    expect(parseEmbedMessage({ type: "ai-agent:start" })).toEqual({
      type: "ai-agent:start",
    });
    expect(parseEmbedMessage({ type: "ai-agent:close" })).toEqual({
      type: "ai-agent:close",
    });
  });

  it("parses a valid state message", () => {
    expect(parseEmbedMessage({ type: "ai-agent:state", state: "listening" })).toEqual({
      type: "ai-agent:state",
      state: "listening",
    });
  });

  it("rejects a state message with an unknown state", () => {
    expect(parseEmbedMessage({ type: "ai-agent:state", state: "dancing" })).toBeNull();
    expect(parseEmbedMessage({ type: "ai-agent:state" })).toBeNull();
  });

  it("parses a finite audio-level message", () => {
    expect(parseEmbedMessage({ type: "ai-agent:audio-level", level: 0.42 })).toEqual({
      type: "ai-agent:audio-level",
      level: 0.42,
    });
  });

  it("rejects a non-finite or missing audio level", () => {
    expect(parseEmbedMessage({ type: "ai-agent:audio-level", level: Infinity })).toBeNull();
    expect(parseEmbedMessage({ type: "ai-agent:audio-level", level: "loud" })).toBeNull();
    expect(parseEmbedMessage({ type: "ai-agent:audio-level" })).toBeNull();
  });

  it("ignores foreign and malformed payloads", () => {
    expect(parseEmbedMessage(null)).toBeNull();
    expect(parseEmbedMessage(undefined)).toBeNull();
    expect(parseEmbedMessage("ai-agent:start")).toBeNull();
    expect(parseEmbedMessage(42)).toBeNull();
    expect(parseEmbedMessage({})).toBeNull();
    expect(parseEmbedMessage({ type: "other:event" })).toBeNull();
    expect(parseEmbedMessage({ source: "react-devtools" })).toBeNull();
  });
});

describe("postToParent", () => {
  it("returns false and does not post when not framed", () => {
    // jsdom's window.parent === window by default (top-level).
    const post = vi.fn();
    const fakeWindow = {
      parent: undefined as unknown as Window,
    } as unknown as Window;
    (fakeWindow as { parent: Window }).parent = fakeWindow;
    (fakeWindow.parent as unknown as { postMessage: typeof post }).postMessage = post;

    const sent = postToParent({ type: "ai-agent:close" }, "*", fakeWindow);

    expect(sent).toBe(false);
    expect(post).not.toHaveBeenCalled();
  });

  it("posts to the parent with the default '*' target origin when framed", () => {
    const post = vi.fn();
    const parent = { postMessage: post } as unknown as Window;
    const fakeWindow = { parent } as unknown as Window;

    const message: EmbedMessage = { type: "ai-agent:state", state: "speaking" };
    const sent = postToParent(message, undefined, fakeWindow);

    expect(sent).toBe(true);
    expect(post).toHaveBeenCalledWith(message, "*");
  });

  it("forwards an explicit target origin", () => {
    const post = vi.fn();
    const parent = { postMessage: post } as unknown as Window;
    const fakeWindow = { parent } as unknown as Window;

    postToParent({ type: "ai-agent:close" }, "https://host.example", fakeWindow);

    expect(post).toHaveBeenCalledWith({ type: "ai-agent:close" }, "https://host.example");
  });
});

describe("postToFrame", () => {
  it("returns false when the frame has no content window", () => {
    expect(postToFrame(null, { type: "ai-agent:start" })).toBe(false);
    expect(
      postToFrame({ contentWindow: null } as unknown as HTMLIFrameElement, {
        type: "ai-agent:start",
      }),
    ).toBe(false);
  });

  it("posts into the frame's content window with default origin", () => {
    const post = vi.fn();
    const frame = {
      contentWindow: { postMessage: post },
    } as unknown as HTMLIFrameElement;

    const sent = postToFrame(frame, { type: "ai-agent:start" });

    expect(sent).toBe(true);
    expect(post).toHaveBeenCalledWith({ type: "ai-agent:start" }, "*");
  });
});

describe("subscribeToEmbedMessages", () => {
  it("invokes the handler only for valid messages and returns an unsubscribe", () => {
    const handler = vi.fn();
    const unsubscribe = subscribeToEmbedMessages(handler);

    window.dispatchEvent(new MessageEvent("message", { data: { type: "ai-agent:close" } }));
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0]![0]).toEqual({ type: "ai-agent:close" });

    // Foreign payload — ignored.
    window.dispatchEvent(new MessageEvent("message", { data: { type: "noise" } }));
    expect(handler).toHaveBeenCalledTimes(1);

    unsubscribe();
    window.dispatchEvent(new MessageEvent("message", { data: { type: "ai-agent:close" } }));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("passes the original MessageEvent as the second argument", () => {
    const handler = vi.fn();
    const unsubscribe = subscribeToEmbedMessages(handler);

    const event = new MessageEvent("message", {
      data: { type: "ai-agent:state", state: "thinking" },
    });
    window.dispatchEvent(event);

    expect(handler).toHaveBeenCalledWith({ type: "ai-agent:state", state: "thinking" }, event);
    unsubscribe();
  });

  it("drops messages from origins outside the allow-list", () => {
    const handler = vi.fn();
    const unsubscribe = subscribeToEmbedMessages(handler, {
      allowedOrigins: ["https://trusted.example"],
    });

    // jsdom dispatches MessageEvents with origin "" by default, which is not
    // in the allow-list, so the handler must not fire.
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "ai-agent:close" },
        origin: "https://evil.example",
      }),
    );
    expect(handler).not.toHaveBeenCalled();

    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "ai-agent:close" },
        origin: "https://trusted.example",
      }),
    );
    expect(handler).toHaveBeenCalledTimes(1);

    unsubscribe();
  });
});
