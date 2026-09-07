// Public client-facing proposal types.
// Mirrors backend `app/schemas/proposal.py` (PublicProposal + friends).

import type { FinancingEstimate } from "./financing";

export interface PublicProposalLineItem {
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
}

export interface PublicProposalBranding {
  business_name: string;
  logo_url?: string | null;
  brand_color: string;
  accent_color: string;
  business_address?: string | null;
  business_phone?: string | null;
  business_email?: string | null;
  footer?: string | null;
}

export type PublicProposalStatus =
  | "sent"
  | "approved"
  | "declined"
  | "expired";

export type ProposalPaymentChoice = "fifty_percent_down" | "pay_in_full";

export interface PublicProposalPaymentAmounts {
  fifty_percent_down_amount: number;
  completion_balance: number;
  pay_in_full_amount: number;
}

/**
 * One package the client can choose between before accepting. Every figure is
 * priced by the server from the saved snapshot — the page renders them, it
 * never computes them.
 */
export interface PublicProposalPackage {
  key: string;
  label: string;
  name?: string | null;
  /** All-in total for this package, including charges that ride along. */
  total: number;
  /** Legacy deposit amount for non-Permanent proposals. */
  deposit_amount?: number | null;
  /** Exact server-priced Permanent payment choices for this package. */
  payment_options?: PublicProposalPaymentAmounts | null;
  /** The package the quote currently sits on (the rep's pick). */
  is_selected: boolean;
}

export interface PublicProposalPriceRange {
  /** Exact quote total accepted and charged if the customer approves. */
  low: number;
  /** Upper ballpark amount; any increase still requires a separate quote. */
  high: number;
}

export interface PublicProposal {
  token: string;
  number: string;
  title?: string | null;
  status: PublicProposalStatus;
  /** Monotonic customer-facing terms version submitted with acceptance. */
  proposal_version: number;
  currency: string;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  /** Informational financing estimate; never an approval choice. */
  financing?: FinancingEstimate | null;
  payment_options?: PublicProposalPaymentAmounts | null;
  proposal_payment_choice?: ProposalPaymentChoice | null;
  proposal_payment_amount?: number | null;
  proposal_payment_paid: boolean;
  proposal_payment_required: boolean;
  issue_date?: string | null;
  expiry_date?: string | null;
  is_expired: boolean;
  is_decided: boolean;
  intro?: string | null;
  notes?: string | null;
  terms?: string | null;
  client_name?: string | null;
  /** Optional upfront deposit the client can pay online to accept the quote. */
  deposit_percentage?: number | null;
  deposit_amount?: number | null;
  deposit_paid: boolean;
  /** True when a deposit is owed and not yet paid (drives the client CTA). */
  deposit_required?: boolean;
  /** Default-off ballpark display; acceptance and payment still use `low`. */
  price_range?: PublicProposalPriceRange | null;
  /**
   * Packages the client may pick between. Empty when there's nothing to choose
   * (a plain quote, or a proposal offering a single priced package).
   */
  packages?: PublicProposalPackage[];
  line_items: PublicProposalLineItem[];
  branding: PublicProposalBranding;
  /** Sales-wizard snapshot (multi-tier presentation); null for plain quotes. */
  proposal_document?: Record<string, unknown> | null;
}

export interface PublicProposalDepositCheckout {
  url: string;
  amount: number;
  currency: string;
}

export interface PublicProposalPaymentCheckout {
  url: string;
  amount: number;
  currency: string;
  payment_choice: ProposalPaymentChoice;
}

export interface PublicProposalActionResult {
  token: string;
  status: PublicProposalStatus;
  message: string;
  proposal_payment_choice?: ProposalPaymentChoice | null;
  proposal_payment_required: boolean;
  proposal_payment_amount?: number | null;
  deposit_required?: boolean;
  deposit_amount?: number | null;
}

export interface PublicProposalDepositStatus {
  deposit_paid: boolean;
  deposit_amount?: number | null;
  currency: string;
}

export interface PublicProposalPaymentStatus {
  payment_paid: boolean;
  payment_required: boolean;
  payment_amount: number;
  completion_balance: number;
  currency: string;
  payment_choice: ProposalPaymentChoice;
}
