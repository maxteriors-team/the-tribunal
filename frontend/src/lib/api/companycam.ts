import { apiGet } from "@/lib/api";

export interface CompanyCamPhoto {
  id: string;
  thumbnail_url: string;
  web_url: string;
  captured_at?: number | null;
  creator_name?: string | null;
}

export interface CompanyCamProjectPhotos {
  project_id: string;
  project_name: string;
  project_url: string;
  photo_count: number;
  address?: string | null;
  photos: CompanyCamPhoto[];
}

export interface ContactCompanyCamPhotosResponse {
  connected: boolean;
  projects: CompanyCamProjectPhotos[];
}

export function getContactCompanyCamPhotos(
  workspaceId: string,
  contactId: number
): Promise<ContactCompanyCamPhotosResponse> {
  return apiGet<ContactCompanyCamPhotosResponse>(
    `/api/v1/workspaces/${workspaceId}/contacts/${contactId}/companycam-photos`
  );
}
