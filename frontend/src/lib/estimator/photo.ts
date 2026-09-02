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
 * Marks a `dataUrl` that is a reference to bucket-stored bytes rather than the
 * bytes themselves. Mirrors `LIGHTING_IMAGE_REF_PREFIX` in
 * `backend/app/schemas/lighting_project.py`.
 */
export const LIGHTING_IMAGE_REF_PREFIX = "lighting-image:";

/**
 * Is this a photo source the app is willing to load?
 *
 * Two shapes are legitimate: bytes inline (a local draft, or a project saved
 * before images moved to the bucket) and a `lighting-image:` reference to a
 * stored object. Anything else — notably a bare `https://` URL — stays
 * rejected: the document is attacker-influencable, and honouring an arbitrary
 * remote URL would let one workspace's drawing pull in someone else's image.
 */
export function isSupportedImageSource(value: string): boolean {
  return value.startsWith("data:image/") || value.startsWith(LIGHTING_IMAGE_REF_PREFIX);
}

/**
 * Freshest signed URL seen for each stored image, keyed by its stable
 * `lighting-image:{key}` reference.
 *
 * Signed URLs expire, but the draft that renders the canvas is seeded once when
 * the designer mounts and is deliberately never reseeded while there are
 * unsaved edits — reseeding runs a full RESET and would discard the operator's
 * work. So refreshed URLs cannot travel inside the draft. They travel here
 * instead: a side channel that `imageSrc` consults first.
 *
 * This is intentionally *not* React state. It must not re-render the canvas, it
 * must not enter the draft (an expiring URL must never be saved), and it must
 * not advance the project version. Keying on the stable reference means a
 * refreshed URL is picked up by the canvas, the proposal export, and the
 * installation plan alike, with no prop threading through the designer.
 */
const refreshedImageUrls = new Map<string, string>();

/** Record freshly signed URLs from a server document. Safe to call repeatedly. */
export function publishRefreshedImageUrls(document: unknown): void {
  for (const [reference, url] of collectResolvedImageUrls(document)) {
    refreshedImageUrls.set(reference, url);
  }
}

/** Test seam: the registry outlives a component, so suites must be able to clear it. */
export function resetRefreshedImageUrls(): void {
  refreshedImageUrls.clear();
}

interface ResolvableImage {
  dataUrl?: unknown;
  resolvedUrl?: unknown;
  imageDataUrl?: unknown;
  resolvedImageUrl?: unknown;
}

/** Pull every (stored reference → signed URL) pair out of a lighting document. */
function collectResolvedImageUrls(document: unknown): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  const shots = (document as { shots?: unknown })?.shots;
  if (!Array.isArray(shots)) return pairs;

  const take = (image: ResolvableImage | undefined, refKey: "dataUrl" | "imageDataUrl") => {
    if (!image) return;
    const reference = image[refKey];
    const url = refKey === "dataUrl" ? image.resolvedUrl : image.resolvedImageUrl;
    if (
      typeof reference === "string" &&
      reference.startsWith(LIGHTING_IMAGE_REF_PREFIX) &&
      typeof url === "string" &&
      url.length > 0
    ) {
      pairs.push([reference, url]);
    }
  };

  for (const entry of shots) {
    const shot = entry as { photo?: ResolvableImage; design?: Record<string, unknown> };
    take(shot?.photo, "dataUrl");
    const design = shot?.design;
    const planImages = design?.planImages;
    if (Array.isArray(planImages)) {
      for (const image of planImages) take(image as ResolvableImage, "dataUrl");
    }
    const annotations = design?.annotations;
    if (Array.isArray(annotations)) {
      for (const image of annotations) take(image as ResolvableImage, "imageDataUrl");
    }
  }
  return pairs;
}

/**
 * The value to hand an `<img>`: the server-signed bucket URL when the image
 * lives in object storage, else the inline data URL. Images saved before the
 * migration — and drafts still in the browser — only have `dataUrl`.
 *
 * A refreshed URL wins over the one the draft was seeded with, because the
 * seeded one expires while the designer stays open.
 */
export function imageSrc(image: {
  dataUrl: string;
  resolvedUrl?: string | null;
}): string {
  return refreshedImageUrls.get(image.dataUrl) ?? image.resolvedUrl ?? image.dataUrl;
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
