// Quote (estimate) types. Mirrors the backend `app/schemas/quote.py` contract.

import type { components } from "@/lib/api/_generated";

import type { FinancingEstimate } from "./financing";

export type QuoteStatus =
  | "draft"
  | "sent"
  | "approved"
  | "declined"
  | "expired";

export interface QuoteLineItem {
  id: string;
  quote_id: string;
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export interface Quote {
  id: string;
  workspace_id: string;
  contact_id?: number | null;
  service_location_id?: string | null;
  opportunity_id?: string | null;
  number: string;
  title?: string | null;
  status: QuoteStatus;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  currency: string;
  /** Server-computed estimate for category-qualified quotes; never an offer. */
  financing?: FinancingEstimate | null;
  /** Optional upfront deposit as a percentage of the total (0–100); null = none. */
  deposit_percentage?: number | null;
  deposit_amount_fixed?: number | null;
  deposit_paid_at?: string | null;
  /** Server-computed effective deposit in major units (fixed wins); null = none. */
  deposit_amount?: number | null;
  /** Server-computed: a deposit is owed and not yet paid. */
  deposit_required?: boolean;
  issue_date?: string | null;
  expiry_date?: string | null;
  sent_at?: string | null;
  approved_at?: string | null;
  declined_at?: string | null;
  decline_reason?: string | null;
  notes?: string | null;
  terms?: string | null;
  converted_job_id?: string | null;
  converted_invoice_id?: string | null;
  /** First time a client opened the public proposal; null = never opened. */
  first_viewed_at?: string | null;
  /** Most recent client open — the "call them now" signal. */
  last_viewed_at?: string | null;
  /** Throttled visit count (repeat opens inside a short window don't count). */
  view_count?: number;
  /** Client-proposal share token; null until the quote is first sent. */
  public_token?: string | null;
  created_at: string;
  updated_at: string;
  /** Present on detail responses (get/create/update, line-item + lifecycle ops). */
  line_items?: QuoteLineItem[];
}

export interface QuoteLineItemInput {
  name: string;
  description?: string;
  quantity?: number;
  unit_price: number;
  discount?: number;
}

export interface CreateQuoteRequest {
  contact_id?: number;
  service_location_id?: string;
  opportunity_id?: string;
  title?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  deposit_percentage?: number;
  issue_date?: string;
  expiry_date?: string;
  notes?: string;
  terms?: string;
  line_items?: QuoteLineItemInput[];
}

export interface UpdateQuoteRequest {
  contact_id?: number;
  service_location_id?: string;
  opportunity_id?: string;
  title?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  deposit_percentage?: number;
  issue_date?: string;
  expiry_date?: string;
  notes?: string;
  terms?: string;
}

export interface QuoteConvertResult {
  quote: Quote;
  job_id: string | null;
  invoice_id: string | null;
}

/**
 * Outcome of emailing or texting a client their proposal link.
 *
 * Taken from the generated OpenAPI schema rather than hand-mirrored: `to` is the
 * destination the server actually resolved (the wizard snapshot's client, the
 * linked contact, or an explicit override), and telling the rep exactly where it
 * went is the whole point of surfacing the result.
 */
export type QuoteDeliverResult = components["schemas"]["QuoteDeliverResult"];
export type QuoteDeliverChannel = QuoteDeliverResult["channel"];
