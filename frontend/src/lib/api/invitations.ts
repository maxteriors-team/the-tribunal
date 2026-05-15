import { apiGet, apiPost, apiDelete } from "@/lib/api";

export interface InvitationResponse {
  id: string;
  workspace_id: string;
  email: string;
  role: string;
  status: string;
  message: string | null;
  invited_by_email: string | null;
  invited_by_name: string | null;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
}

export interface InvitationPublicResponse {
  workspace_name: string;
  workspace_slug: string;
  email: string;
  role: string;
  invited_by_name: string | null;
  expires_at: string;
  is_expired: boolean;
  is_valid: boolean;
}

export interface InvitationAcceptResponse {
  success: boolean;
  message: string;
  workspace_id: string | null;
  workspace_slug: string | null;
}

export interface CreateInvitationRequest {
  email: string;
  role: "admin" | "member";
  message?: string;
}

/**
 * Invitations API.
 *
 * Note: This API is NOT fully migrated to use the factory because:
 * 1. The list endpoint returns an array, not a paginated response
 * 2. The API has mixed scoping - list/create/cancel are workspace-scoped,
 *    but getByToken and accept are public (non-workspace-scoped) endpoints
 *
 * The factory pattern expects paginated list responses and consistent scoping,
 * which this API doesn't have. Keeping the original implementation.
 */
export const invitationsApi = {
  /**
   * List pending invitations for a workspace (admin only)
   * Note: Returns a plain array, not paginated, to match backend API
   */
  list: async (workspaceId: string): Promise<InvitationResponse[]> => {
    return apiGet<InvitationResponse[]>(
      `/api/v1/workspaces/${workspaceId}/invitations`
    );
  },

  /**
   * Create and send an invitation
   */
  create: async (
    workspaceId: string,
    data: CreateInvitationRequest
  ): Promise<InvitationResponse> => {
    return apiPost<InvitationResponse>(
      `/api/v1/workspaces/${workspaceId}/invitations`,
      data
    );
  },

  /**
   * Cancel a pending invitation
   */
  cancel: async (workspaceId: string, invitationId: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/invitations/${invitationId}`);
  },

  /**
   * Get invitation details by token (public endpoint - NOT workspace-scoped)
   */
  getByToken: async (token: string): Promise<InvitationPublicResponse> => {
    return apiGet<InvitationPublicResponse>(
      `/api/v1/invitations/${token}`
    );
  },

  /**
   * Accept an invitation (must be logged in - NOT workspace-scoped)
   */
  accept: async (token: string): Promise<InvitationAcceptResponse> => {
    return apiPost<InvitationAcceptResponse>(
      `/api/v1/invitations/${token}/accept`
    );
  },
};
