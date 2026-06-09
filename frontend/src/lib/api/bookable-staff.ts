import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

export type AssignmentStrategy = "single" | "round_robin" | "skill_based";

export interface BookableStaff {
  id: string;
  workspace_id: string;
  agent_id: string | null;
  name: string;
  email: string | null;
  calcom_event_type_id: number | null;
  skills: string[];
  is_active: boolean;
  priority: number;
  assignment_count: number;
  last_assigned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BookableStaffList {
  items: BookableStaff[];
  total: number;
}

export interface CreateBookableStaffRequest {
  name: string;
  email?: string | null;
  calcom_event_type_id?: number | null;
  skills?: string[];
  is_active?: boolean;
  priority?: number;
}

export interface UpdateBookableStaffRequest {
  name?: string;
  email?: string | null;
  calcom_event_type_id?: number | null;
  skills?: string[];
  is_active?: boolean;
  priority?: number;
}

const basePath = (workspaceId: string, agentId: string) =>
  `/api/v1/workspaces/${workspaceId}/agents/${agentId}/staff`;

export const bookableStaffApi = {
  list: (workspaceId: string, agentId: string) =>
    apiGet<BookableStaffList>(basePath(workspaceId, agentId)),

  create: (workspaceId: string, agentId: string, body: CreateBookableStaffRequest) =>
    apiPost<BookableStaff>(basePath(workspaceId, agentId), body),

  update: (
    workspaceId: string,
    agentId: string,
    staffId: string,
    body: UpdateBookableStaffRequest,
  ) => apiPut<BookableStaff>(`${basePath(workspaceId, agentId)}/${staffId}`, body),

  remove: (workspaceId: string, agentId: string, staffId: string) =>
    apiDelete(`${basePath(workspaceId, agentId)}/${staffId}`),
};
