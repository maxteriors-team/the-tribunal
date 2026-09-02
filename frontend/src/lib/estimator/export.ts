/**
 * Flatten a light design over its photo into a single JPEG.
 *
 * Draws the exact glow engine the on-screen editor uses (`drawScene`) onto an
 * offscreen canvas at the photo's native aspect — chrome off, dusk on — then
 * exports a bounded-width JPEG data URL. Used for the AI render upload and for
 * the composite saved onto a proposal, so the customer sees exactly what the
 * rep drew: the design, never any price or measurement.
 *
 * Bounded to `maxWidth` (default 1280px) so the upload stays light; the AI model
 * doesn't need full resolution and smaller payloads render faster and cheaper.
 */
import { designScale } from "./design";
import { imageSrc, loadImage } from "./photo";
import { DEFAULT_DUSK, drawScene } from "./render";
import type { Design, PhotoInfo, Product } from "./types";

export interface ExportOptions {
  maxWidth?: number;
  /** How dark the scene reads, 0 (daylight) to `MAX_DUSK`. */
  dusk?: number;
  /** JPEG quality 0–1. */
  quality?: number;
}

/**
 * Render `design` over `photo` and return a `data:image/jpeg;base64,...` URL.
 * Runs on an offscreen canvas, so it never disturbs the live editor canvas.
 */
export async function exportDesignJpeg(
  photo: PhotoInfo,
  design: Design,
  productById: Map<string, Product>,
  options: ExportOptions = {},
): Promise<string> {
  const { maxWidth = 1280, dusk = DEFAULT_DUSK, quality = 0.9 } = options;

  const img = await loadImage(imageSrc(photo));
  const nw = img.naturalWidth || photo.width;
  const nh = img.naturalHeight || photo.height;

  const scale = nw > maxWidth ? maxWidth / nw : 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(nw * scale));
  canvas.height = Math.max(1, Math.round(nh * scale));

  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not get a 2D canvas context for export.");

  // drawScene draws in image-space pixels; scale the whole scene down uniformly.
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  const { pxPerFt } = designScale(design, nw);
  drawScene(ctx, img, design, productById, pxPerFt, {
    viewScale: scale,
    dusk,
    showChrome: false,
  });

  return canvas.toDataURL("image/jpeg", quality);
}
