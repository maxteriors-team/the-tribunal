/**
 * Client-side image downscaling for proposal mockups.
 *
 * Mockups are stored inline in the proposal snapshot as data URLs (this
 * deployment has no object storage), so keeping them small matters: we cap the
 * longest edge and re-encode as JPEG before they ever leave the browser. A
 * 1600px q0.78 photo lands around 250–500 KB — sharp on screen and in print,
 * light enough that several fit comfortably in one saved quote.
 */

const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.78;

/** Read a File into an HTMLImageElement via an object URL (revoked after load). */
function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read that image"));
    };
    img.src = url;
  });
}

/**
 * Downscale an uploaded image so its longest edge is at most `MAX_EDGE`, then
 * encode it as a JPEG data URL. Images already within bounds are re-encoded
 * (never upscaled). Throws if the file is not a decodable image.
 */
export async function fileToResizedDataUrl(file: File): Promise<string> {
  const img = await loadImage(file);
  const { width, height } = img;
  const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas not supported in this browser");
  ctx.drawImage(img, 0, 0, w, h);

  const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  if (!dataUrl.startsWith("data:image/")) {
    throw new Error("Could not encode that image");
  }
  return dataUrl;
}
