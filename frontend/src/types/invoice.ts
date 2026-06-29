// Customer invoice types. Mirrors the backend `app/schemas/invoice.py` contract.

export type InvoiceStatus =
  | "draft"
  | "sent"
  | "paid"
  | "partial"
  | "void"
  | "overdue";

export interface InvoiceLineItem {
  id: string;
  invoice_id: string;
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export interface Invoice {
  id: string;
  workspace_id: string;
  contact_id?: number | null;
  opportunity_id?: string | null;
  number: string;
  status: InvoiceStatus;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  amount_paid: number;
  currency: string;
  issue_date?: string | null;
  due_date?: string | null;
  sent_at?: string | null;
  paid_at?: string | null;
  notes?: string | null;
  terms?: string | null;
  created_at: string;
  updated_at: string;
  /** Present on detail responses (get/create/update, line-item + lifecycle ops). */
  line_items?: InvoiceLineItem[];
}

export interface InvoiceLineItemInput {
  name: string;
  description?: string;
  quantity?: number;
  unit_price: number;
  discount?: number;
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
}

export interface InvoicePaymentLink {
  session_id: string;
  url: string | null;
}
