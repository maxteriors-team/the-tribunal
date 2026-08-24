import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { prepareOutboundMmsImage } from "./image-upload";

class LoadedImage {
  naturalWidth = 2400;
  naturalHeight = 1200;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  set src(_value: string) {
    queueMicrotask(() => this.onload?.());
  }
}

describe("prepareOutboundMmsImage", () => {
  beforeEach(() => {
    vi.stubGlobal("Image", LoadedImage);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:photo"),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      fillStyle: "",
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("re-encodes a large photo below the carrier-safe size", async () => {
    const renderSizes: Array<{ width: number; height: number }> = [];
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (
      this: HTMLCanvasElement,
      callback,
    ) {
      renderSizes.push({ width: this.width, height: this.height });
      const size = renderSizes.length === 1 ? 700 * 1024 : 500 * 1024;
      callback(new Blob([new Uint8Array(size)], { type: "image/jpeg" }));
    });

    const image = await prepareOutboundMmsImage(
      new File(["source"], "driveway.png", { type: "image/png" }),
    );

    expect(renderSizes).toEqual([
      { width: 1600, height: 800 },
      { width: 1600, height: 800 },
    ]);
    expect(image.dataUrl).toMatch(/^data:image\/jpeg;base64,/);
    expect(image.sizeBytes).toBe(500 * 1024);
  });

  it("rejects unsupported files before decoding them", async () => {
    await expect(
      prepareOutboundMmsImage(new File(["source"], "notes.txt", { type: "text/plain" })),
    ).rejects.toThrow("Use a JPEG, PNG, GIF, or WebP image");
  });
});
