import { apiGet, apiPost } from "@/lib/api";
import type {
  PublicProposal,
  PublicProposalActionResult,
  PublicProposalDepositCheckout,
  PublicProposalDepositStatus,
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

  // Start a Stripe Checkout Session for the proposal's deposit; returns the
  // hosted payment URL for the page to redirect to.
  depositCheckout: (token: string): Promise<PublicProposalDepositCheckout> =>
    apiPost<PublicProposalDepositCheckout>(
      `/api/v1/p/quotes/${token}/deposit-checkout`,
    ),

  // Reconcile the deposit against Stripe on return from checkout (webhook
  // backstop). Marks paid if Stripe confirms it; safe to call repeatedly.
  depositStatus: (token: string): Promise<PublicProposalDepositStatus> =>
    apiPost<PublicProposalDepositStatus>(
      `/api/v1/p/quotes/${token}/deposit-status`,
    ),
};
