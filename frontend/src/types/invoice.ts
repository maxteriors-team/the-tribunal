// Customer invoice types. Mirrors the backend `app/schemas/invoice.py` contract.

export type InvoiceStatus = "draft" | "sent" | "paid" | "partial" | "void" | "overdue";
export type InvoicePaymentMethod = "card" | "cash" | "check";
export type InvoicePaymentRecordMethod = InvoicePaymentMethod | "other";
export type ManualInvoicePaymentMethod = "cash" | "check";

export type InvoiceReceiptDeliveryStatus = "pending" | "sent" | "needs_attention" | "skipped";

export interface InvoiceReceiptDelivery {
  status: InvoiceReceiptDeliveryStatus;
  recipient?: string | null;
  timestamp?: string | null;
  /** Sanitized operator next step; never a raw provider error. */
  reason?: string | null;
}

export interface InvoiceLineItem {
  id: string;
  invoice_id: string;
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  is_optional: boolean;
  is_selected: boolean;
  created_at: string;
  updated_at: string;
}

export interface InvoicePayment {
  id: string;
  payment_method: InvoicePaymentRecordMethod;
  amount: number;
  reference?: string | null;
  recorded_by_id?: number | null;
  received_at: string;
}

export interface Invoice {
  id: string;
  workspace_id: string;
  contact_id?: number | null;
  /** Bill-to contact's display name. Null when the invoice has no contact. */
  contact_name?: string | null;
  opportunity_id?: string | null;
  number: string;
  status: InvoiceStatus;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  amount_paid: number;
  currency: string;
  payment_method?: InvoicePaymentMethod | null;
  payment_recorded_by_id?: number | null;
  manual_payment_amount?: number | null;
  manual_payment_reference?: string | null;
  issue_date?: string | null;
  due_date?: string | null;
  sent_at?: string | null;
  paid_at?: string | null;
  notes?: string | null;
  terms?: string | null;
  created_at: string;
  updated_at: string;
  receipt_delivery: InvoiceReceiptDelivery;
  payments?: InvoicePayment[];
  /** Present on detail responses (get/create/update, line-item + lifecycle ops). */
  line_items?: InvoiceLineItem[];
}

export interface InvoiceManualPaymentInput {
  payment_method: ManualInvoicePaymentMethod;
  amount: number;
  reference?: string | null;
  idempotency_key: string;
}

export interface InvoiceLineItemInput {
  name: string;
  description?: string | null;
  quantity?: number;
  unit_price: number;
  discount?: number;
  is_optional?: boolean;
}

/**
 * Every client-settable line field required for whole-set replacement.
 * Keeping these required prevents an editor from silently applying API defaults
 * to fields it loaded but failed to send back.
 */
export interface InvoiceLineItemReplacementInput {
  name: string;
  description: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  is_optional: boolean;
}

export interface CreateInvoiceRequest {
  contact_id?: number;
  opportunity_id?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  issue_date?: string;
  due_date?: string;
  notes?: string;
  terms?: string;
  line_items?: InvoiceLineItemInput[];
}

export interface UpdateInvoiceRequest {
  contact_id?: number;
  opportunity_id?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  issue_date?: string;
  due_date?: string;
  notes?: string;
  terms?: string;
  /**
   * Replaces the entire line-item set in one transaction. Omit to leave line
   * items untouched; every supported line field is required here because omitted
   * fields would be reset to API defaults during replacement.
   */
  line_items?: InvoiceLineItemReplacementInput[];
}

export interface InvoicePaymentLink {
  session_id: string;
  url: string | null;
}

/**
 * What actually happened when an invoice was sent. `skipped_no_email` means the
 * invoice moved to `sent` but reached nobody — no bill-to contact, or a contact
 * with no email on file — so the UI must warn instead of reporting success.
 */
export type InvoiceDeliveryStatus = "emailed" | "skipped_no_email" | "failed";

/** Outcome of sending an invoice on a specific channel. */
export interface InvoiceDeliverResult {
  ok: boolean;
  channel: "email" | "sms";
  to: string;
}

export interface InvoiceSendResult extends Invoice {
  delivery: InvoiceDeliveryStatus;
  delivered_to?: string | null;
}
