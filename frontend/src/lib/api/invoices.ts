import { apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreateInvoiceRequest,
  Invoice,
  InvoiceLineItemInput,
  InvoicePaymentLink,
  UpdateInvoiceRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

export interface InvoicesListParams {
  page?: number;
  page_size?: number;
  status?: string;
  contact_id?: number;
}

// Base CRUD from the factory (list/get/create/update/delete).
const baseInvoicesApi = createApiClient<
  Invoice,
  CreateInvoiceRequest,
  UpdateInvoiceRequest
>({
  resourcePath: "invoices",
});

const invoicePath = (workspaceId: string, invoiceId: string): string =>
  `/api/v1/workspaces/${workspaceId}/invoices/${invoiceId}`;

export const invoicesApi = {
  list: baseInvoicesApi.list,
  get: baseInvoicesApi.get!,
  create: baseInvoicesApi.create!,
  update: baseInvoicesApi.update!,
  delete: baseInvoicesApi.delete!,

  // Lifecycle transitions
  send: async (workspaceId: string, invoiceId: string): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/send`);
  },

  void: async (workspaceId: string, invoiceId: string): Promise<Invoice> => {
    return apiPost<Invoice>(`${invoicePath(workspaceId, invoiceId)}/void`);
  },

  paymentLink: async (
    workspaceId: string,
    invoiceId: string
  ): Promise<InvoicePaymentLink> => {
    return apiPost<InvoicePaymentLink>(
      `${invoicePath(workspaceId, invoiceId)}/payment-link`
    );
  },

  // Line-item sub-resource (mutations return the full invoice with recomputed totals)
  addLineItem: async (
    workspaceId: string,
    invoiceId: string,
    data: InvoiceLineItemInput
  ): Promise<Invoice> => {
    return apiPost<Invoice>(
      `${invoicePath(workspaceId, invoiceId)}/line-items`,
      data
    );
  },

  updateLineItem: async (
    workspaceId: string,
    invoiceId: string,
    itemId: string,
    data: Partial<InvoiceLineItemInput>
  ): Promise<Invoice> => {
    return apiPut<Invoice>(
      `${invoicePath(workspaceId, invoiceId)}/line-items/${itemId}`,
      data
    );
  },

  removeLineItem: async (
    workspaceId: string,
    invoiceId: string,
    itemId: string
  ): Promise<Invoice> => {
    return apiDelete<Invoice>(
      `${invoicePath(workspaceId, invoiceId)}/line-items/${itemId}`
    );
  },
};
