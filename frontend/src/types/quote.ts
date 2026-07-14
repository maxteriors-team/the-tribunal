// Quote (estimate) types. Mirrors the backend `app/schemas/quote.py` contract.

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
  /** Optional upfront deposit as a percentage of the total (0–100); null = none. */
  deposit_percentage?: number | null;
  deposit_paid_at?: string | null;
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
