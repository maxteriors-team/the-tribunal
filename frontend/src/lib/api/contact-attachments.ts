import { apiDelete, apiGet, apiPost } from "@/lib/api";

export interface ContactAttachment {
  id: string;
  contact_id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface ContactAttachmentList {
  attachments: ContactAttachment[];
}

const base = (workspaceId: string, contactId: number) =>
  `/api/v1/workspaces/${workspaceId}/contacts/${contactId}/attachments`;

export function listContactAttachments(
  workspaceId: string,
  contactId: number
): Promise<ContactAttachmentList> {
  return apiGet<ContactAttachmentList>(base(workspaceId, contactId));
}

export function uploadContactAttachment(
  workspaceId: string,
  contactId: number,
  file: File
): Promise<ContactAttachment> {
  const formData = new FormData();
  formData.append("file", file);
  return apiPost<ContactAttachment>(base(workspaceId, contactId), formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export function deleteContactAttachment(
  workspaceId: string,
  contactId: number,
  attachmentId: string
): Promise<void> {
  return apiDelete(`${base(workspaceId, contactId)}/${attachmentId}`);
}

/**
 * Same-origin download URL (auth rides on the httpOnly cookie through the
 * Next.js proxy), usable directly as `img src` / `href`.
 */
export function contactAttachmentDownloadUrl(
  workspaceId: string,
  contactId: number,
  attachmentId: string
): string {
  return `${base(workspaceId, contactId)}/${attachmentId}/download`;
}
