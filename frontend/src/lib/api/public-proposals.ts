import { apiGet, apiPost } from "@/lib/api";
import type {
  ProposalPaymentChoice,
  PublicProposal,
  PublicProposalActionResult,
  PublicProposalDepositCheckout,
  PublicProposalDepositStatus,
  PublicProposalPaymentCheckout,
  PublicProposalPaymentStatus,
} from "@/types/proposal";

/** The customer's act of signing, as collected by the accept form. */
export type ProposalSignature = {
  signedName: string;
  econsentAccepted: boolean;
  cancellationAcknowledged: boolean;
};

// Public client proposal API (no auth required — keyed on the share token).
export const publicProposalsApi = {
  get: (token: string): Promise<PublicProposal> =>
    apiGet<PublicProposal>(`/api/v1/p/quotes/${token}`),

  /**
   * Accept the exact rendered proposal version. `selectedTier` only names a
   * package; the server still re-derives every line and amount.
   *
   * `signature` carries the e-signature ceremony. Only the typed name and the
   * two affirmations are sent: the timestamps and the signer's IP are recorded
   * by the server, because evidence the signer could choose is not evidence.
   */
  approve: (
    token: PublicProposal["token"],
    proposalVersion: number,
    selectedTier?: string | null,
    paymentOption?: ProposalPaymentChoice | null,
    signature?: ProposalSignature | null,
  ): Promise<PublicProposalActionResult> =>
    apiPost<PublicProposalActionResult>(`/api/v1/p/quotes/${token}/approve`, {
      proposal_version: proposalVersion,
      selected_tier: selectedTier ?? null,
      payment_option: paymentOption ?? null,
      signed_name: signature?.signedName ?? null,
      econsent_accepted: signature?.econsentAccepted ?? false,
      cancellation_acknowledged: signature?.cancellationAcknowledged ?? false,
    }),

  /**
   * Tell the backend a human opened this proposal, so the operator can call
   * while it is still on the client's screen.
   *
   * A separate beacon rather than a side effect of `get` on purpose: the read
   * stays pure, and React Query's retries/refetches never amplify into writes
   * on an unauthenticated endpoint. Errors are swallowed — analytics must never
   * degrade the page the customer came here to read.
   */
  recordView: async (token: string): Promise<void> => {
    try {
      await apiPost<void>(`/api/v1/p/quotes/${token}/view`);
    } catch {
      // Intentionally silent: a missed view is a missed notification, not a
      // broken proposal.
    }
  },

  decline: (token: string, reason?: string): Promise<PublicProposalActionResult> =>
    apiPost<PublicProposalActionResult>(`/api/v1/p/quotes/${token}/decline`, {
      reason,
    }),

  // Start a Stripe Checkout Session for the proposal's deposit; returns the
  // hosted payment URL for the page to redirect to.
  depositCheckout: (token: string): Promise<PublicProposalDepositCheckout> =>
    apiPost<PublicProposalDepositCheckout>(`/api/v1/p/quotes/${token}/deposit-checkout`),

  // Reconcile the deposit against Stripe on return from checkout (webhook
  // backstop). Marks paid if Stripe confirms it; safe to call repeatedly.
  depositStatus: (token: PublicProposal["token"]): Promise<PublicProposalDepositStatus> =>
    apiPost<PublicProposalDepositStatus>(`/api/v1/p/quotes/${token}/deposit-status`),

  // Start or reuse the one active Stripe Session for the accepted Permanent payment.
  paymentCheckout: (token: PublicProposal["token"]): Promise<PublicProposalPaymentCheckout> =>
    apiPost<PublicProposalPaymentCheckout>(`/api/v1/p/quotes/${token}/payment-checkout`),

  // Reconcile a Permanent proposal payment on hosted-checkout return.
  paymentStatus: (token: PublicProposal["token"]): Promise<PublicProposalPaymentStatus> =>
    apiPost<PublicProposalPaymentStatus>(`/api/v1/p/quotes/${token}/payment-status`),
};
