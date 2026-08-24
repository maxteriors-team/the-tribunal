const MAX_SOURCE_BYTES = 15 * 1024 * 1024;
const MAX_MMS_BYTES = 600 * 1024;
const MAX_EDGE = 1600;
const MIN_EDGE = 480;

export const MMS_IMAGE_ACCEPT = "image/jpeg,image/png,image/gif,image/webp";

export interface OutboundMmsImage {
  dataUrl: string;
  name: string;
  sizeBytes: number;
}

export async function prepareOutboundMmsImage(file: File): Promise<OutboundMmsImage> {
  if (!MMS_IMAGE_ACCEPT.split(",").includes(file.type)) {
    throw new Error("Use a JPEG, PNG, GIF, or WebP image.");
  }
  if (file.size > MAX_SOURCE_BYTES) {
    throw new Error("Choose an image smaller than 15 MB.");
  }

  const image = await loadImage(file);
  if (!image.naturalWidth || !image.naturalHeight) {
    throw new Error("That image could not be read.");
  }
  const initialScale = Math.min(1, MAX_EDGE / Math.max(image.naturalWidth, image.naturalHeight));
  let width = Math.max(1, Math.round(image.naturalWidth * initialScale));
  let height = Math.max(1, Math.round(image.naturalHeight * initialScale));
  let quality = 0.78;

  for (let attempt = 0; attempt < 10; attempt += 1) {
    const blob = await renderJpeg(image, width, height, quality);
    if (blob.size <= MAX_MMS_BYTES) {
      return {
        dataUrl: await blobToDataUrl(blob),
        name: file.name || "photo.jpg",
        sizeBytes: blob.size,
      };
    }

    if (quality > 0.54) {
      quality -= 0.08;
    } else {
      const longestEdge = Math.max(width, height);
      const scale = longestEdge > MIN_EDGE ? Math.max(0.75, MIN_EDGE / longestEdge) : 0.75;
      width = Math.max(1, Math.round(width * scale));
      height = Math.max(1, Math.round(height * scale));
      quality = 0.7;
    }
  }

  throw new Error("That image could not be compressed for MMS.");
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("That image could not be read."));
    };
    image.src = objectUrl;
  });
}

function renderJpeg(
  image: HTMLImageElement,
  width: number,
  height: number,
  quality: number,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Image attachments are not supported in this browser.");

  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("That image could not be compressed for MMS."));
      },
      "image/jpeg",
      quality,
    );
  });
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      typeof reader.result === "string"
        ? resolve(reader.result)
        : reject(new Error("That image could not be read."));
    reader.onerror = () => reject(new Error("That image could not be read."));
    reader.readAsDataURL(blob);
  });
}
