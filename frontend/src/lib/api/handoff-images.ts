import { apiDelete, apiGet, apiPost } from "@/lib/api";

export type HandoffImageContentType = "image/jpeg" | "image/png" | "image/webp";

export interface HandoffImage {
  id: string;
  filename: string;
  content_type: HandoffImageContentType;
  size_bytes: number;
  created_at: string;
}

export interface HandoffImageList {
  images: HandoffImage[];
  max_images: number;
  max_image_bytes: number;
}

const quoteBase = (workspaceId: string, quoteId: string): string =>
  `/api/v1/workspaces/${workspaceId}/quotes/${quoteId}/handoff-images`;

const jobBase = (workspaceId: string, jobId: string): string =>
  `/api/v1/workspaces/${workspaceId}/jobs/${jobId}/handoff-images`;

export function listQuoteHandoffImages(
  workspaceId: string,
  quoteId: string,
): Promise<HandoffImageList> {
  return apiGet<HandoffImageList>(quoteBase(workspaceId, quoteId));
}

export function uploadQuoteHandoffImage(
  workspaceId: string,
  quoteId: string,
  file: File,
): Promise<HandoffImage> {
  const formData = new FormData();
  formData.append("file", file);
  return apiPost<HandoffImage>(quoteBase(workspaceId, quoteId), formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export function deleteQuoteHandoffImage(
  workspaceId: string,
  quoteId: string,
  imageId: string,
): Promise<void> {
  return apiDelete(`${quoteBase(workspaceId, quoteId)}/${imageId}`);
}

export function quoteHandoffImageUrl(
  workspaceId: string,
  quoteId: string,
  imageId: string,
): string {
  return `${quoteBase(workspaceId, quoteId)}/${imageId}/download`;
}

export function listJobHandoffImages(
  workspaceId: string,
  jobId: string,
): Promise<HandoffImageList> {
  return apiGet<HandoffImageList>(jobBase(workspaceId, jobId));
}

export function jobHandoffImageUrl(workspaceId: string, jobId: string, imageId: string): string {
  return `${jobBase(workspaceId, jobId)}/${imageId}/download`;
}
