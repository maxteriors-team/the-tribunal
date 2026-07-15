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

export function loadImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Could not load image"));
    img.src = dataUrl;
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
