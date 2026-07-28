import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type { AssignableRole } from "@/lib/workspace-roles";

export interface WorkspaceResponse {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  is_active: boolean;
  /**
   * When the operator finished the onboarding wizard; `null` if they never did.
   * The only trustworthy "is this workspace configured?" signal — see
   * `useSetupStatus`.
   */
  onboarding_completed_at: string | null;
  created_at: string;
  updated_at: string;
  /** The caller's role in this workspace; populated on per-workspace reads. */
  role?: string | null;
}

export interface WorkspaceWithMembership {
  workspace: WorkspaceResponse;
  role: string;
  is_default: boolean;
}

export interface CreateWorkspaceRequest {
  name: string;
  slug: string;
  description?: string;
  settings?: Record<string, unknown>;
}

export interface UpdateWorkspaceRequest {
  name?: string;
  description?: string;
  settings?: Record<string, unknown>;
}

export const workspacesApi = {
  list: async (): Promise<WorkspaceWithMembership[]> => {
    return apiGet<WorkspaceWithMembership[]>("/api/v1/workspaces");
  },

  get: async (workspaceId: string): Promise<WorkspaceResponse> => {
    return apiGet<WorkspaceResponse>(`/api/v1/workspaces/${workspaceId}`);
  },

  create: async (data: CreateWorkspaceRequest): Promise<WorkspaceResponse> => {
    return apiPost<WorkspaceResponse>("/api/v1/workspaces", data);
  },

  update: async (workspaceId: string, data: UpdateWorkspaceRequest): Promise<WorkspaceResponse> => {
    return apiPut<WorkspaceResponse>(`/api/v1/workspaces/${workspaceId}`, data);
  },

  delete: async (workspaceId: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}`);
  },

  setDefault: async (workspaceId: string): Promise<WorkspaceWithMembership> => {
    return apiPost<WorkspaceWithMembership>(
      `/api/v1/workspaces/${workspaceId}/set-default`
    );
  },

  updateMemberRole: async (
    workspaceId: string,
    userId: number,
    role: AssignableRole
  ): Promise<{ user_id: number; role: string; message: string }> => {
    return apiPut<{ user_id: number; role: string; message: string }>(
      `/api/v1/workspaces/${workspaceId}/members/${userId}/role`,
      { role }
    );
  },

  removeMember: async (workspaceId: string, userId: number): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/members/${userId}`);
  },
};
