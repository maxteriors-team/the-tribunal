import { apiGet } from "@/lib/api";

/** Lifecycle of a reactivation drip sequence (`DripCampaignStatus`). */
export type DripCampaignStatus = "draft" | "active" | "paused" | "completed";

/**
 * A multi-step reactivation drip. Only the fields the automation builder needs
 * to name and gate a `start_drip_campaign` action are modelled here; the full
 * shape lives in `backend/app/schemas/drip_campaign.py`.
 */
export interface DripCampaign {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  status: DripCampaignStatus;
  total_enrolled: number;
  started_at: string | null;
  created_at: string;
}

export const dripCampaignsApi = {
  list: async (workspaceId: string): Promise<DripCampaign[]> => {
    return apiGet<DripCampaign[]>(
      `/api/v1/workspaces/${workspaceId}/drip-campaigns`
    );
  },
};
