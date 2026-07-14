import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import type { components } from "@/lib/api/_generated";

/**
 * Business locations = the company's own physical branches / business units
 * (ServiceTitan-style), NOT a customer's job site (that is a "service
 * location"). Staff, jobs, and appointments can later be tagged to a branch so
 * the dashboard can filter and roll up by location.
 */
export type BusinessLocation =
  components["schemas"]["BusinessLocationResponse"];
export type BusinessLocationCreateRequest =
  components["schemas"]["BusinessLocationCreate"];
export type BusinessLocationUpdateRequest =
  components["schemas"]["BusinessLocationUpdate"];
export type BusinessLocationListResponse =
  components["schemas"]["BusinessLocationListResponse"];

const base = (workspaceId: string) =>
  `/api/v1/workspaces/${workspaceId}/business-locations`;

export const businessLocationsApi = {
  list: async (
    workspaceId: string,
    params?: { is_active?: boolean },
  ): Promise<BusinessLocationListResponse> => {
    const query =
      params?.is_active !== undefined ? `?is_active=${params.is_active}` : "";
    return apiGet<BusinessLocationListResponse>(`${base(workspaceId)}${query}`);
  },

  get: async (workspaceId: string, id: string): Promise<BusinessLocation> => {
    return apiGet<BusinessLocation>(`${base(workspaceId)}/${id}`);
  },

  create: async (
    workspaceId: string,
    data: BusinessLocationCreateRequest,
  ): Promise<BusinessLocation> => {
    return apiPost<BusinessLocation>(base(workspaceId), data);
  },

  update: async (
    workspaceId: string,
    id: string,
    data: BusinessLocationUpdateRequest,
  ): Promise<BusinessLocation> => {
    return apiPut<BusinessLocation>(`${base(workspaceId)}/${id}`, data);
  },

  delete: async (workspaceId: string, id: string): Promise<void> => {
    await apiDelete(`${base(workspaceId)}/${id}`);
  },
};
