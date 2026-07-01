import { apiGet, apiPut } from "@/lib/api";

// Mirrors backend `app/schemas/proposal.py::ProposalTemplateSettings`. This is
// the per-workspace branding + boilerplate for client proposals; editing it
// re-renders every proposal with no code change (the self-serve layer).
export interface ProposalTemplateSettings {
  business_name: string | null;
  logo_url: string | null;
  brand_color: string;
  accent_color: string;
  business_address: string | null;
  business_phone: string | null;
  business_email: string | null;
  intro: string | null;
  default_terms: string | null;
  footer: string | null;
}

export interface UpdateProposalTemplateRequest {
  business_name?: string | null;
  logo_url?: string | null;
  brand_color?: string;
  accent_color?: string;
  business_address?: string | null;
  business_phone?: string | null;
  business_email?: string | null;
  intro?: string | null;
  default_terms?: string | null;
  footer?: string | null;
}

export const proposalTemplateApi = {
  get: (workspaceId: string): Promise<ProposalTemplateSettings> =>
    apiGet<ProposalTemplateSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/proposal-template`,
    ),

  update: (
    workspaceId: string,
    data: UpdateProposalTemplateRequest,
  ): Promise<ProposalTemplateSettings> =>
    apiPut<ProposalTemplateSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/proposal-template`,
      data,
    ),
};
