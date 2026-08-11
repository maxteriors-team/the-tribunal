import type { PublicProposalBranding } from "./proposal";

/**
 * The customer-facing view of an invoice, served from its share token at
 * `/p/invoices/[token]`. Mirrors the backend `PublicInvoice` allowlist: no
 * workspace, contact, Stripe, or provenance fields cross this boundary.
 */
export interface PublicInvoiceLineItem {
  id: string;
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  is_optional: boolean;
  is_selected: boolean;
}

export interface PublicInvoice {
  token: string;
  number: string;
  status: "draft" | "sent" | "paid" | "partial" | "void" | "overdue";
  currency: string;

  line_items: PublicInvoiceLineItem[];
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  /** Already collected — a quote deposit paid earlier lands here. */
  amount_paid: number;
  /** Server-computed remainder. Never derive this on the client. */
  balance_due: number;

  issue_date?: string | null;
  due_date?: string | null;
  is_paid: boolean;
  is_void: boolean;
  is_overdue: boolean;
  /** Something is owed, the invoice is live, and Stripe is configured. */
  is_payable: boolean;

  client_name?: string | null;
  notes?: string | null;
  terms?: string | null;

  branding: PublicProposalBranding;
}

export interface PublicInvoicePaymentCheckout {
  url: string;
  amount: number;
  currency: string;
}

export interface PublicInvoicePaymentStatus {
  is_paid: boolean;
  amount_paid: number;
  balance_due: number;
  currency: string;
}
