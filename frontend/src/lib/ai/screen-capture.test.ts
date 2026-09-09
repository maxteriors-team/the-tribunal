import { afterEach, describe, expect, it, vi } from "vitest";

import {
  captureScreenFrame,
  encodeFrame,
  fitWithin,
  FRAME_TIMEOUT_MS,
} from "@/lib/ai/screen-capture";

const setDisplayMedia = (impl: (() => Promise<MediaStream>) | undefined) => {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: impl ? { getDisplayMedia: impl } : {},
  });
};

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setDisplayMedia(undefined);
});

describe("fitWithin", () => {
  it("scales a large screen down to the long edge", () => {
    expect(fitWithin(3840, 2160, 1600)).toEqual({ width: 1600, height: 900 });
    expect(fitWithin(1080, 1920, 1600)).toEqual({ width: 900, height: 1600 });
  });

  it("never upscales a small window", () => {
    expect(fitWithin(800, 600, 1600)).toEqual({ width: 800, height: 600 });
  });

  it("survives a zero-sized frame", () => {
    expect(fitWithin(0, 0, 1600)).toEqual({ width: 0, height: 0 });
  });
});

describe("encodeFrame", () => {
  it("prefers PNG so UI text stays legible", () => {
    const toDataURL = vi.fn(() => "data:image/png;base64,AAAA");
    expect(encodeFrame({ toDataURL })).toEqual({ dataUrl: "data:image/png;base64,AAAA" });
    expect(toDataURL).toHaveBeenCalledTimes(1);
  });

  it("falls back to JPEG when the PNG exceeds the inline image cap", () => {
    const huge = `data:image/png;base64,${"A".repeat(8 * 1024 * 1024)}`;
    const toDataURL = vi.fn((type: string) =>
      type === "image/png" ? huge : "data:image/jpeg;base64,BBBB",
    );

    expect(encodeFrame({ toDataURL })).toEqual({ dataUrl: "data:image/jpeg;base64,BBBB" });
  });

  it("reports a helpful error when even a compressed frame is too large", () => {
    const huge = `data:image/jpeg;base64,${"A".repeat(8 * 1024 * 1024)}`;
    const toDataURL = vi.fn((type: string) =>
      type === "image/png" ? `data:image/png;base64,${"A".repeat(8 * 1024 * 1024)}` : huge,
    );

    expect(encodeFrame({ toDataURL }).error).toMatch(/single window/);
  });
});

describe("captureScreenFrame", () => {
  it("explains itself when the browser cannot share a screen", async () => {
    setDisplayMedia(undefined);
    const result = await captureScreenFrame();
    expect(result.error).toMatch(/can't share a screen/);
  });

  it("treats a dismissed picker as a cancellation, not a failure", async () => {
    setDisplayMedia(() => Promise.reject(new DOMException("Permission denied", "NotAllowedError")));

    const result = await captureScreenFrame();

    expect(result).toEqual({ cancelled: true });
  });

  it("gives up on a stream that never yields a frame, and stops its tracks", async () => {
    const track = { stop: vi.fn(), kind: "video" };
    const stream = { getTracks: () => [track] } as unknown as MediaStream;
    setDisplayMedia(() => Promise.resolve(stream));
    vi.useFakeTimers();

    // jsdom never fires `loadedmetadata` for a synthetic stream, so this
    // exercises the timeout guard: no hang, and the share indicator is released.
    const pending = captureScreenFrame();
    await vi.advanceTimersByTimeAsync(FRAME_TIMEOUT_MS + 1_000);
    const result = await pending;

    expect(result.error).toMatch(/Timed out/);
    expect(track.stop).toHaveBeenCalledTimes(1);
  });
});
