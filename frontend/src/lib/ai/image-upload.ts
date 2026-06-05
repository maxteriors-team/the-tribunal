/**
 * Client-side helpers for attaching an image to an AI conversation.
 *
 * Mirrors the backend allowlist/size cap in
 * `backend/app/services/ai/image_input.py` so the UI rejects bad files before
 * a round-trip. The image is read into a base64 data URL and sent inline; it is
 * never uploaded to the unauthenticated /static dir.
 */

export const MAX_IMAGE_BYTES = 5 * 1024 * 1024; // 5 MB

export const ALLOWED_IMAGE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
] as const;

/** `accept` attribute value for image file inputs. */
export const IMAGE_ACCEPT_ATTR = ALLOWED_IMAGE_TYPES.join(",");

export interface ReadImageResult {
  dataUrl?: string;
  error?: string;
}

/** Validate type/size and read a file into a base64 data URL. */
export async function readImageFile(file: File): Promise<ReadImageResult> {
  if (!ALLOWED_IMAGE_TYPES.includes(file.type as (typeof ALLOWED_IMAGE_TYPES)[number])) {
    return { error: "Unsupported image type. Use JPEG, PNG, WebP, or GIF." };
  }
  if (file.size > MAX_IMAGE_BYTES) {
    return { error: "Image is too large (max 5 MB)." };
  }

  try {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
      reader.readAsDataURL(file);
    });
    return { dataUrl };
  } catch {
    return { error: "Could not read the image file." };
  }
}
