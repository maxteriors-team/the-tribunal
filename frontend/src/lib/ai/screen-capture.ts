/**
 * Single-frame screen capture for the CRM Assistant.
 *
 * The browser's own picker is the consent gate: the user chooses exactly which
 * screen/window/tab is shared. We grab **one** frame and stop every track
 * immediately, so nothing keeps recording after the snapshot — and the result
 * is handed to the existing image-attachment path, visible in the composer
 * before it is sent anywhere.
 */

import { MAX_IMAGE_BYTES } from "@/lib/ai/image-upload";
import { stopMediaStream } from "@/lib/embed/session";

/** Screenshots are read for text, so cap the long edge rather than the area. */
const MAX_EDGE_PX = 1600;
/** A stream that never produces a frame must not wedge the button forever. */
export const FRAME_TIMEOUT_MS = 10_000;

export interface ScreenCaptureResult {
  dataUrl?: string;
  /** Set when capture failed or the user cancelled the picker. */
  error?: string;
  /** True when the user dismissed the picker — not worth surfacing as an error. */
  cancelled?: boolean;
}

/** Scale `width`/`height` down to fit `maxEdge`, never up. */
export function fitWithin(
  width: number,
  height: number,
  maxEdge: number = MAX_EDGE_PX,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxEdge || longest === 0) {
    return { width: Math.round(width), height: Math.round(height) };
  }
  const scale = maxEdge / longest;
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

const dataUrlBytes = (dataUrl: string) => Math.ceil((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75);

/**
 * PNG keeps UI text crisp, but a dense screenshot can blow the 5 MB inline
 * limit, so fall back to JPEG before giving up.
 */
export function encodeFrame(canvas: Pick<HTMLCanvasElement, "toDataURL">): ScreenCaptureResult {
  for (const [type, quality] of [
    ["image/png", undefined],
    ["image/jpeg", 0.85],
    ["image/jpeg", 0.6],
  ] as const) {
    const dataUrl = canvas.toDataURL(type, quality);
    if (dataUrl.startsWith(`data:${type}`) && dataUrlBytes(dataUrl) <= MAX_IMAGE_BYTES) {
      return { dataUrl };
    }
  }
  return { error: "That screen is too detailed to send. Try sharing a single window instead." };
}

/** Play the stream into an offscreen video just long enough to read one frame. */
async function drawFirstFrame(stream: MediaStream): Promise<HTMLCanvasElement> {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;

  try {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Timed out reading the screen.")), FRAME_TIMEOUT_MS);
      video.onloadedmetadata = () => {
        clearTimeout(timer);
        resolve();
      };
      video.onerror = () => {
        clearTimeout(timer);
        reject(new Error("Could not read the shared screen."));
      };
    });
    await video.play();

    const { width, height } = fitWithin(video.videoWidth, video.videoHeight);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser can't render the screenshot.");
    context.drawImage(video, 0, 0, width, height);
    return canvas;
  } finally {
    video.pause();
    video.srcObject = null;
  }
}

/**
 * Prompt for screen sharing and return one frame as a data URL.
 * Tracks are always stopped, including on failure.
 */
export async function captureScreenFrame(): Promise<ScreenCaptureResult> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getDisplayMedia) {
    return { error: "This browser can't share a screen. Attach a screenshot image instead." };
  }

  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const canvas = await drawFirstFrame(stream);
    return encodeFrame(canvas);
  } catch (error) {
    // The picker's "Cancel" rejects with NotAllowedError — an intent, not a fault.
    if (error instanceof DOMException && error.name === "NotAllowedError") {
      return { cancelled: true };
    }
    return { error: error instanceof Error ? error.message : "Screen capture failed." };
  } finally {
    stopMediaStream(stream);
  }
}
