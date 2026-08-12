import { apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreateQuoteRequest,
  Quote,
  QuoteConvertResult,
  QuoteDeliverChannel,
  QuoteDeliverResult,
  QuoteLineItemInput,
  QuoteServiceInput,
  UpdateQuoteRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

export interface QuotesListParams {
  page?: number;
  page_size?: number;
  status?: string;
  contact_id?: number;
  assigned_user_id?: number;
}

// Base CRUD from the factory (list/get/create/update/delete).
const baseQuotesApi = createApiClient<Quote, CreateQuoteRequest, UpdateQuoteRequest>({
  resourcePath: "quotes",
});

const quotePath = (workspaceId: string, quoteId: string): string =>
  `/api/v1/workspaces/${workspaceId}/quotes/${quoteId}`;

export const quotesApi = {
  list: baseQuotesApi.list,
  get: baseQuotesApi.get!,
  create: baseQuotesApi.create!,
  update: baseQuotesApi.update!,
  delete: baseQuotesApi.delete!,

  assign: async (
    workspaceId: string,
    quoteId: string,
    assignedUserId: number | null,
  ): Promise<Quote> => {
    return apiPut<Quote>(`${quotePath(workspaceId, quoteId)}/assignment`, {
      assigned_user_id: assignedUserId,
    });
  },

  // Lifecycle transitions
  send: async (workspaceId: string, quoteId: string): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/send`);
  },

  /**
   * Email or text the client their proposal link.
   *
   * Distinct from `send`, which marks the quote sent and emails **best-effort**
   * — it swallows "there was no address" and reports success either way. This
   * one names the channel and surfaces the server's reason when a rail isn't
   * ready (no client phone, number opted out, Telnyx unconfigured), which is the
   * difference between a rep knowing the customer got it and only hoping so.
   *
   * `to` overrides the destination; omitted, the server falls back to the wizard
   * snapshot's client email/phone, then the linked contact's.
   */
  deliver: async (
    workspaceId: string,
    quoteId: string,
    channel: QuoteDeliverChannel,
    to?: string | null,
  ): Promise<QuoteDeliverResult> => {
    return apiPost<QuoteDeliverResult>(`${quotePath(workspaceId, quoteId)}/deliver`, {
      channel,
      to: to ?? null,
    });
  },

  approve: async (workspaceId: string, quoteId: string): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/approve`);
  },

  decline: async (workspaceId: string, quoteId: string, reason?: string): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/decline`, {
      reason,
    });
  },

  convert: async (
    workspaceId: string,
    quoteId: string,
    options?: {
      create_job?: boolean;
      create_invoice?: boolean;
      // ISO datetimes; supply both to schedule the created job on the calendar.
      scheduled_start?: string | null;
      scheduled_end?: string | null;
      crew_id?: string | null;
      technician_ids?: string[];
      confirm_unpaid_deposit?: boolean;
    },
  ): Promise<QuoteConvertResult> => {
    return apiPost<QuoteConvertResult>(`${quotePath(workspaceId, quoteId)}/convert`, {
      create_job: options?.create_job ?? true,
      create_invoice: options?.create_invoice ?? true,
      scheduled_start: options?.scheduled_start ?? null,
      scheduled_end: options?.scheduled_end ?? null,
      crew_id: options?.crew_id ?? null,
      technician_ids: options?.technician_ids ?? [],
      confirm_unpaid_deposit: options?.confirm_unpaid_deposit ?? false,
    });
  },

  /**
   * Add a service to an existing quote ("they also want the gutters done").
   *
   * Prefer this over `addLineItem` for anything an operator adds after the
   * quote was saved. Nearly every quote is built by the sales wizard, and on
   * those the line items are *derived* from `proposal_document`: a raw line
   * item never appears on the client's proposal and is wiped the next time the
   * quote reprices. This endpoint stores the service wherever it survives on
   * that particular quote and returns the repriced quote.
   *
   * `amount` is the net the business keeps — the server adds the finance buffer
   * on a wizard quote, exactly like the wizard's own add-on row.
   */
  addService: async (
    workspaceId: string,
    quoteId: string,
    data: QuoteServiceInput,
  ): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/services`, data);
  },

  removeService: async (
    workspaceId: string,
    quoteId: string,
    serviceId: string,
  ): Promise<Quote> => {
    return apiDelete<Quote>(`${quotePath(workspaceId, quoteId)}/services/${serviceId}`);
  },

  // Line-item sub-resource (mutations return the full quote with recomputed totals)
  addLineItem: async (
    workspaceId: string,
    quoteId: string,
    data: QuoteLineItemInput,
  ): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/line-items`, data);
  },

  updateLineItem: async (
    workspaceId: string,
    quoteId: string,
    itemId: string,
    data: Partial<QuoteLineItemInput>,
  ): Promise<Quote> => {
    return apiPut<Quote>(`${quotePath(workspaceId, quoteId)}/line-items/${itemId}`, data);
  },

  removeLineItem: async (workspaceId: string, quoteId: string, itemId: string): Promise<Quote> => {
    return apiDelete<Quote>(`${quotePath(workspaceId, quoteId)}/line-items/${itemId}`);
  },
};
