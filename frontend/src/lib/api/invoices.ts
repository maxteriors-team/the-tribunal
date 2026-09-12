import { api, apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreateInvoiceRequest,
  Invoice,
  InvoiceLineItemInput,
  InvoiceDeliverResult,
  InvoiceManualPaymentInput,
  InvoicePaymentLink,
  InvoiceSendResult,
  UpdateInvoiceRequest,
} from "@/types";
import type { PaginatedResponse } from "@/types/api";

import { createApiClient } from "./create-api-client";

export interface InvoicesListParams {
  page?: number;
  page_size?: number;
  status?: string;
  contact_id?: number;
  /**
   * Only invoices that still owe money. Selects on outstanding amounts rather
   * than on `status`, which the backend refreshes only when an invoice is
   * edited and so goes stale on exactly the overdue ones that matter most.
   */
  unpaid_only?: boolean;
}

// Base CRUD from the factory (list/get/create/update/delete).
const baseInvoicesApi = createApiClient<Invoice, CreateInvoiceRequest, UpdateInvoiceRequest>({
  resourcePath: "invoices",
});

const invoicePath = (workspaceId: string, invoiceId: string): string =>
  `/api/v1/workspaces/${workspaceId}/invoices/${invoiceId}`;

/**
 * Invoice page plus the book-wide amount outstanding.
 *
 * `outstanding_total` covers every invoice matching the filter, not just this
 * page, so "how much are we owed" does not shrink as the operator pages through.
 */
export interface PaginatedInvoices extends PaginatedResponse<Invoice> {
  /** Optional so existing fixtures and cached pages stay valid; treat as 0. */
  outstanding_total?: number;
}

export const invoicesApi = {
  // Wrapped rather than taken from the factory: the invoice list carries the
  // book-wide `outstanding_total` alongside the page, which the generic client
  // shape does not model.
  list: async (
    workspaceId: string,
    params: InvoicesListParams = {},
  ): Promise<PaginatedInvoices> => {
    const response = await api.get<PaginatedInvoices>(
      `/api/v1/workspaces/${workspaceId}/invoices`,
      { params },
    );
    return response.data;
  },
  get: baseInvoicesApi.get!,
  create: baseInvoicesApi.create!,
  update: baseInvoicesApi.update!,
  delete: baseInvoicesApi.delete!,

  // Lifecycle transitions
  // Returns the invoice plus `delivery`, so callers can tell the operator
  // whether the customer was actually emailed.
  send: async (workspaceId: string, invoiceId: string): Promise<InvoiceSendResult> => {
    return apiPost<InvoiceSendResult>(`${invoicePath(workspaceId, invoiceId)}/send`);
  },

  recordManualPayment: async (
    workspaceId: string,
    invoiceId: string,
    payment: InvoiceManualPaymentInput,
  ): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/payments/manual`, payment);
  },

  retryReceipt: async (workspaceId: string, invoiceId: string): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/receipt/retry`);
  },

  // Send the customer their invoice link on a chosen channel. Unlike `send`,
  // a failed delivery throws (the operator picked a channel and a recipient),
  // so callers surface the message instead of reading a status field.
  deliver: async (
    workspaceId: string,
    invoiceId: string,
    body: { channel: "email" | "sms"; to?: string },
  ): Promise<InvoiceDeliverResult> => {
    return apiPost<InvoiceDeliverResult>(`${invoicePath(workspaceId, invoiceId)}/deliver`, body);
  },

  void: async (workspaceId: string, invoiceId: string): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/void`);
  },

  paymentLink: async (workspaceId: string, invoiceId: string): Promise<InvoicePaymentLink> => {
    return apiPost<InvoicePaymentLink>(`${invoicePath(workspaceId, invoiceId)}/payment-link`);
  },

  // Line-item sub-resource (mutations return the full invoice with recomputed totals)
  addLineItem: async (
    workspaceId: string,
    invoiceId: string,
    data: InvoiceLineItemInput,
  ): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/line-items`, data);
  },

  updateLineItem: async (
    workspaceId: string,
    invoiceId: string,
    itemId: string,
    data: Partial<InvoiceLineItemInput>,
  ): Promise<Invoice> => {
    return apiPut<Invoice>(`${invoicePath(workspaceId, invoiceId)}/line-items/${itemId}`, data);
  },

  removeLineItem: async (
    workspaceId: string,
    invoiceId: string,
    itemId: string,
  ): Promise<Invoice> => {
    return apiDelete<Invoice>(`${invoicePath(workspaceId, invoiceId)}/line-items/${itemId}`);
  },
};
