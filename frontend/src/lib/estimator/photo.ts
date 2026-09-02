/**
 * Photo helpers for the light designer.
 *
 * `loadImage` decodes a data URL into an `HTMLImageElement` for the canvas to
 * draw; `fileToPhoto` reads an uploaded file into a `PhotoInfo` (data URL plus
 * intrinsic dimensions). Both are Promise-based so the canvas can await a
 * decoded image before its first paint. Kept tiny and dependency-free so a
 * later AI-render export (Phase 2) can reuse `loadImage`.
 */
import type { PhotoInfo } from "./types";

/**
 * The value to hand an `<img>`: the server-signed bucket URL when the image
 * lives in object storage, else the inline data URL. Images saved before the
 * migration — and drafts still in the browser — only have `dataUrl`.
 */
export function imageSrc(image: {
  dataUrl: string;
  resolvedUrl?: string | null;
}): string {
  return image.resolvedUrl ?? image.dataUrl;
}

export function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Could not load image"));
    // Bucket-hosted images are cross-origin, and drawing one onto a canvas
    // without this taints it — `toDataURL()` in export.ts would then throw and
    // silently break proposal export. Must be set before `src`. The bucket
    // answers with Access-Control-Allow-Origin (scripts/ops/set_bucket_cors.py).
    if (!src.startsWith("data:")) img.crossOrigin = "anonymous";
    img.src = src;
  });
}

export async function fileToPhoto(file: File): Promise<PhotoInfo> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
  const img = await loadImage(dataUrl);
  return { dataUrl, width: img.naturalWidth, height: img.naturalHeight };
}
