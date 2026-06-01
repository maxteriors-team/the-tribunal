/**
 * Embed messaging protocol — a thin, typed wrapper around the `postMessage`
 * channel that connects the embeddable widget to the agent UI it hosts.
 *
 * ── Topology ──────────────────────────────────────────────────────────────
 * The `<ai-agent>` custom element runs on the *host* page (an arbitrary
 * customer-controlled domain). It renders the live agent UI inside a
 * cross-origin `<iframe>` that points at our own embed routes
 * (`/embed/<publicId>/…`). The two windows never share a DOM or globals; they
 * coordinate exclusively through `window.postMessage`.
 *
 *   host page  ──(ai-agent:start)──▶  iframe (embed route)
 *   host page  ◀─(state / audio-level / close)──  iframe
 *
 * ── Why we send with `targetOrigin: "*"` ──────────────────────────────────
 * `postMessage`'s second argument restricts *which origin is allowed to
 * receive* the message. We deliberately broadcast with `"*"` because neither
 * side can statically know the other's origin:
 *
 *   • The widget is embedded on customer domains we do not control or know in
 *     advance, so the iframe cannot pin the parent's origin.
 *   • Our embed routes are served from several deploy origins (production,
 *     Vercel previews, custom domains), so the host page cannot pin ours.
 *
 * Crucially, every message on this channel is a *non-sensitive UI lifecycle
 * signal* — open/close intent, coarse agent state, and a smoothed audio level.
 * No tokens, transcripts, PII, or secrets ever cross it (those go over
 * authenticated `fetch` calls instead). Broadcasting these signals is therefore
 * safe even if another frame observes them.
 *
 * Receiving is where we stay strict: {@link subscribeToEmbedMessages} validates
 * every inbound payload by *shape* and can additionally restrict by an
 * allow-list of origins, so a hostile frame cannot drive our UI with malformed
 * or unexpected messages.
 */

/** Coarse agent lifecycle state shared across the widget and embed surfaces. */
export type EmbedAgentState = "idle" | "listening" | "thinking" | "speaking";

/** Namespace prefix shared by every message type on this channel. */
export const EMBED_MESSAGE_NAMESPACE = "ai-agent" as const;

export const EMBED_AGENT_STATES: readonly EmbedAgentState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
];

/**
 * Discriminated union of every message exchanged between the host widget and
 * the embedded agent UI. The `type` field is the discriminant.
 */
export type EmbedMessage =
  /** host → iframe: begin a session (sent when the widget popup opens). */
  | { type: "ai-agent:start" }
  /** iframe → host: the agent UI asked to be closed. */
  | { type: "ai-agent:close" }
  /** iframe → host: the agent moved to a new lifecycle state. */
  | { type: "ai-agent:state"; state: EmbedAgentState }
  /** iframe → host: smoothed microphone/output level in the range [0, 1]. */
  | { type: "ai-agent:audio-level"; level: number };

export type EmbedMessageType = EmbedMessage["type"];

/** Type guard for the coarse agent-state enum. */
export function isEmbedAgentState(value: unknown): value is EmbedAgentState {
  return typeof value === "string" && (EMBED_AGENT_STATES as readonly string[]).includes(value);
}

/**
 * Validate and narrow an unknown `MessageEvent.data` payload into a typed
 * {@link EmbedMessage}. Returns `null` for anything that is not a well-formed
 * message on this channel, so callers can safely ignore foreign chatter (React
 * DevTools, other embeds, browser extensions, etc.).
 */
export function parseEmbedMessage(data: unknown): EmbedMessage | null {
  if (!data || typeof data !== "object") return null;

  const type = (data as { type?: unknown }).type;
  if (typeof type !== "string") return null;

  switch (type) {
    case "ai-agent:start":
      return { type };
    case "ai-agent:close":
      return { type };
    case "ai-agent:state": {
      const state = (data as { state?: unknown }).state;
      return isEmbedAgentState(state) ? { type, state } : null;
    }
    case "ai-agent:audio-level": {
      const level = (data as { level?: unknown }).level;
      return typeof level === "number" && Number.isFinite(level) ? { type, level } : null;
    }
    default:
      return null;
  }
}

/**
 * Post a message to the parent window (iframe → host). No-op (returns `false`)
 * when we are not actually framed, which keeps the embed routes usable as plain
 * standalone pages.
 *
 * @param targetOrigin See the module header for why this defaults to `"*"`.
 */
export function postToParent(
  message: EmbedMessage,
  targetOrigin: string = "*",
  win: Window = window,
): boolean {
  if (win.parent === win) return false;
  win.parent.postMessage(message, targetOrigin);
  return true;
}

/**
 * Post a message into an embedded iframe (host → iframe). No-op (returns
 * `false`) when the frame has no live content window yet.
 *
 * @param targetOrigin See the module header for why this defaults to `"*"`.
 */
export function postToFrame(
  frame: HTMLIFrameElement | null | undefined,
  message: EmbedMessage,
  targetOrigin: string = "*",
): boolean {
  const target = frame?.contentWindow;
  if (!target) return false;
  target.postMessage(message, targetOrigin);
  return true;
}

export interface SubscribeOptions {
  /**
   * When provided, inbound messages whose `event.origin` is not in this list
   * are dropped before validation. Leave unset to accept any origin (the
   * default, since host/iframe origins are not known ahead of time) — payloads
   * are still validated by shape regardless.
   */
  allowedOrigins?: readonly string[];
  /** Window to attach the listener to. Defaults to the global `window`. */
  target?: Window;
}

/**
 * Subscribe to validated embed messages on `window`'s `message` event.
 *
 * The supplied handler only fires for payloads that pass
 * {@link parseEmbedMessage}; everything else is ignored. Returns an
 * unsubscribe function suitable for direct use as a React effect cleanup.
 */
export function subscribeToEmbedMessages(
  handler: (message: EmbedMessage, event: MessageEvent) => void,
  options: SubscribeOptions = {},
): () => void {
  const { allowedOrigins, target = window } = options;

  const listener = (event: MessageEvent) => {
    if (allowedOrigins && allowedOrigins.length > 0 && !allowedOrigins.includes(event.origin)) {
      return;
    }

    const message = parseEmbedMessage(event.data);
    if (message) handler(message, event);
  };

  target.addEventListener("message", listener);
  return () => target.removeEventListener("message", listener);
}
