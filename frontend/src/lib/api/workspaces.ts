import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";

export interface WorkspaceResponse {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceWithMembership {
  workspace: WorkspaceResponse;
  role: "owner" | "admin" | "member";
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
    role: "admin" | "member"
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
