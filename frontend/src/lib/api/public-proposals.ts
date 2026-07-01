import { apiGet, apiPost } from "@/lib/api";
import type {
  PublicProposal,
  PublicProposalActionResult,
} from "@/types/proposal";

// Public client proposal API (no auth required — keyed on the share token).
export const publicProposalsApi = {
  get: (token: string): Promise<PublicProposal> =>
    apiGet<PublicProposal>(`/api/v1/p/quotes/${token}`),

  approve: (token: string): Promise<PublicProposalActionResult> =>
    apiPost<PublicProposalActionResult>(`/api/v1/p/quotes/${token}/approve`),

  decline: (
    token: string,
    reason?: string,
  ): Promise<PublicProposalActionResult> =>
    apiPost<PublicProposalActionResult>(`/api/v1/p/quotes/${token}/decline`, {
      reason,
    }),
};
