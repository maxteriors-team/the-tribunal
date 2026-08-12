import { apiGet, apiPatch, apiPost } from "@/lib/api";
import type { components, operations } from "@/lib/api/_generated";

export type LandscapeDraftDocument = components["schemas"]["LandscapeDraftDocument"];
export type LightingProjectCreate = components["schemas"]["LightingProjectCreate"];
export type LightingProjectDetail = Omit<
  components["schemas"]["LightingProjectDetail"],
  "installation_shot_id"
> & { installation_shot_id?: string | null };
export type LightingProjectSummary = Omit<LightingProjectDetail, "document" | "created_by_id">;
export type LightingProjectUpdate = components["schemas"]["LightingProjectUpdate"];
export type PaginatedLightingProjects = Omit<
  components["schemas"]["PaginatedLightingProjects"],
  "items"
> & { items: LightingProjectDetail[] };
export type LightingProjectListParams = NonNullable<
  operations["list_lighting_projects_api_v1_workspaces__workspace_id__lighting_projects_get"]["parameters"]["query"]
>;

const collectionPath = (workspaceId: string): string =>
  `/api/v1/workspaces/${workspaceId}/lighting-projects`;

const detailPath = (workspaceId: string, projectId: string): string =>
  `${collectionPath(workspaceId)}/${projectId}`;

export const lightingProjectsApi = {
  list: (
    workspaceId: string,
    params: LightingProjectListParams = {},
  ): Promise<PaginatedLightingProjects> =>
    apiGet<PaginatedLightingProjects>(collectionPath(workspaceId), { params }),

  create: (workspaceId: string, payload: LightingProjectCreate): Promise<LightingProjectDetail> =>
    apiPost<LightingProjectDetail>(collectionPath(workspaceId), payload),

  get: (workspaceId: string, projectId: string): Promise<LightingProjectDetail> =>
    apiGet<LightingProjectDetail>(detailPath(workspaceId, projectId)),

  update: (
    workspaceId: string,
    projectId: string,
    payload: LightingProjectUpdate,
  ): Promise<LightingProjectDetail> =>
    apiPatch<LightingProjectDetail>(detailPath(workspaceId, projectId), payload),
};
