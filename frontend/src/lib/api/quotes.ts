import { apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreateQuoteRequest,
  Quote,
  QuoteConvertResult,
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
    options?: { create_job?: boolean; create_invoice?: boolean }
  ): Promise<QuoteConvertResult> => {
    return apiPost<QuoteConvertResult>(
      `${quotePath(workspaceId, quoteId)}/convert`,
      {
        create_job: options?.create_job ?? true,
        create_invoice: options?.create_invoice ?? true,
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
