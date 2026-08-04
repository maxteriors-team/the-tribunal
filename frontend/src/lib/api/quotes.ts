import { apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreateQuoteRequest,
  Quote,
  QuoteConvertResult,
  QuoteDeliverChannel,
  QuoteDeliverResult,
  QuoteLineItemInput,
  UpdateQuoteRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

export interface QuotesListParams {
  page?: number;
  page_size?: number;
  status?: string;
  contact_id?: number;
}

// Base CRUD from the factory (list/get/create/update/delete).
const baseQuotesApi = createApiClient<
  Quote,
  CreateQuoteRequest,
  UpdateQuoteRequest
>({
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
    return apiPost<QuoteDeliverResult>(
      `${quotePath(workspaceId, quoteId)}/deliver`,
      { channel, to: to ?? null },
    );
  },

  approve: async (workspaceId: string, quoteId: string): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/approve`);
  },

  decline: async (
    workspaceId: string,
    quoteId: string,
    reason?: string
  ): Promise<Quote> => {
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
    }
  ): Promise<QuoteConvertResult> => {
    return apiPost<QuoteConvertResult>(
      `${quotePath(workspaceId, quoteId)}/convert`,
      {
        create_job: options?.create_job ?? true,
        create_invoice: options?.create_invoice ?? true,
        scheduled_start: options?.scheduled_start ?? null,
        scheduled_end: options?.scheduled_end ?? null,
      }
    );
  },

  // Line-item sub-resource (mutations return the full quote with recomputed totals)
  addLineItem: async (
    workspaceId: string,
    quoteId: string,
    data: QuoteLineItemInput
  ): Promise<Quote> => {
    return apiPost<Quote>(`${quotePath(workspaceId, quoteId)}/line-items`, data);
  },

  updateLineItem: async (
    workspaceId: string,
    quoteId: string,
    itemId: string,
    data: Partial<QuoteLineItemInput>
  ): Promise<Quote> => {
    return apiPut<Quote>(
      `${quotePath(workspaceId, quoteId)}/line-items/${itemId}`,
      data
    );
  },

  removeLineItem: async (
    workspaceId: string,
    quoteId: string,
    itemId: string
  ): Promise<Quote> => {
    return apiDelete<Quote>(
      `${quotePath(workspaceId, quoteId)}/line-items/${itemId}`
    );
  },
};
