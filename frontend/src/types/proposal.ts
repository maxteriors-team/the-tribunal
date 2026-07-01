// Public client-facing proposal types.
// Mirrors backend `app/schemas/proposal.py` (PublicProposal + friends).

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

export interface PublicProposal {
  token: string;
  number: string;
  title?: string | null;
  status: PublicProposalStatus;
  currency: string;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  issue_date?: string | null;
  expiry_date?: string | null;
  is_expired: boolean;
  is_decided: boolean;
  intro?: string | null;
  notes?: string | null;
  terms?: string | null;
  client_name?: string | null;
  line_items: PublicProposalLineItem[];
  branding: PublicProposalBranding;
}

export interface PublicProposalActionResult {
  token: string;
  status: PublicProposalStatus;
  message: string;
}
