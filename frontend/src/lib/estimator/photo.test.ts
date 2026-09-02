import { describe, expect, it } from "vitest";

import { imageSrc, loadImage } from "./photo";

describe("imageSrc", () => {
  it("prefers the server-signed URL when the image lives in the bucket", () => {
    expect(
      imageSrc({ dataUrl: "lighting-image:workspaces/w/x.png", resolvedUrl: "https://b/signed" }),
    ).toBe("https://b/signed");
  });

  it("falls back to the inline data URL for unmigrated projects and local drafts", () => {
    expect(imageSrc({ dataUrl: "data:image/png;base64,AAAA" })).toBe("data:image/png;base64,AAAA");
    expect(imageSrc({ dataUrl: "data:image/png;base64,AAAA", resolvedUrl: null })).toBe(
      "data:image/png;base64,AAAA",
    );
  });
});

describe("loadImage", () => {
  /**
   * Drawing a cross-origin image onto a canvas without this taints it, and the
   * `toDataURL()` in export.ts then throws — silently breaking proposal export.
   */
  it("requests CORS for bucket URLs and sets it before src", () => {
    const assigned: string[] = [];
    class SpyImage {
      crossOrigin: string | null = null;
      #src = "";
      set src(value: string) {
        assigned.push(`crossOrigin=${this.crossOrigin}`);
        this.#src = value;
      }
      get src() {
        return this.#src;
      }
    }
    const original = globalThis.Image;
    globalThis.Image = SpyImage as unknown as typeof Image;
    try {
      void loadImage("https://bucket.example/signed");
      expect(assigned).toEqual(["crossOrigin=anonymous"]);

      assigned.length = 0;
      void loadImage("data:image/png;base64,AAAA");
      expect(assigned).toEqual(["crossOrigin=null"]);
    } finally {
      globalThis.Image = original;
    }
  });
});
