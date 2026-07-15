/**
 * Contacts API client.
 *
 * Proof-of-concept migration to the OpenAPI-typed `apiClient` from
 * `./_client.ts`. Endpoint URLs, path/query params, request bodies, and
 * response shapes are all checked against the generated `Paths` types —
 * if the backend renames or drops a route, `npm run typecheck` fails.
 *
 * The public `contactsApi` surface (method names + argument shapes) is
 * preserved so existing hooks/components don't need to change.
 */

import { apiClient, type Schemas } from "@/lib/api/_client";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";
import type { Contact, ContactStatus, TimelineItem } from "@/types";

export type ContactSortBy =
  | "created_at"
  | "last_conversation"
  | "unread_first"
  | "name_asc"
  | "name_desc"
  | "last_activity_asc"
  | "last_activity_desc";

// ---------------------------------------------------------------------------
// Re-exported schemas (canonical types from the OpenAPI spec).
//
// These replace the hand-rolled interfaces that previously lived in this
// file. Other modules should pull request/response shapes from here so a
// schema change in the backend ripples through automatically.
// ---------------------------------------------------------------------------

export type ContactCreatePayload = Schemas["ContactCreate"];
export type ContactUpdatePayload = Schemas["ContactUpdate"];
export type ContactResponse = Schemas["ContactResponse"];
export type ContactListResponse = Schemas["ContactListResponse"];
/** Back-compat alias — prefer `ContactListResponse`. */
export type ContactsListResponse = ContactListResponse;
export type ContactStatsResponse = Schemas["ContactStatsResponse"];
export type ContactIdsResponse = Schemas["ContactIdsResponse"];
export type ContactEngagementSummary = Schemas["ContactEngagementSummary"];
export type BulkDeleteResponse = Schemas["BulkDeleteResponse"];
export type BulkUpdateStatusResponse = Schemas["BulkStatusUpdateResponse"];
export type AIToggleResponse = Schemas["AIToggleResponse"];

export type ContactAgentAssignResponse = Schemas["ContactAgentAssignResponse"];

// The OpenAPI spec models `ImportResult.errors` and `CSVPreviewResponse
// .contact_fields` as loose `unknown[]`/`{ [k: string]: unknown }[]` — the
// backend hasn't pinned them down yet. We narrow them at the boundary so UI
// code can treat the fields as the structured records they actually are.
export interface ContactFieldDef {
  name: string;
  label: string;
  required: boolean;
}

export type CSVPreviewResult = Omit<Schemas["CSVPreviewResponse"], "contact_fields"> & {
  contact_fields: ContactFieldDef[];
};

export type ImportResult = Omit<Schemas["ImportResult"], "errors"> & {
  errors: ImportErrorDetail[];
};

// ---------------------------------------------------------------------------
// Legacy request types — kept for backwards compatibility with existing
// callers (e.g. forms that don't yet use the schema-derived types).
// New code should prefer `ContactCreatePayload` / `ContactUpdatePayload`.
// ---------------------------------------------------------------------------

export interface ImportantDates {
  birthday?: string;
  anniversary?: string;
  custom?: Array<{ label: string; date: string }>;
}

export interface CreateContactRequest {
  first_name: string;
  last_name?: string;
  email?: string;
  phone_number: string;
  company_name?: string;
  status?: ContactStatus;
  tags?: string[];
  notes?: string;
  source?: string;
  important_dates?: ImportantDates | null;
  address_line1?: string;
  address_line2?: string;
  address_city?: string;
  address_state?: string;
  address_zip?: string;
  // Structured lead-source attribution (see backend LeadAttributionFields).
  first_touch_lead_source_id?: string;
  first_touch_lead_source_campaign_id?: string;
  latest_touch_lead_source_id?: string;
  latest_touch_lead_source_campaign_id?: string;
  attribution_confidence?: number;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  utm_term?: string;
  gclid?: string;
  fbclid?: string;
  landing_page?: string;
  referrer?: string;
}

export interface UpdateContactRequest {
  first_name?: string;
  last_name?: string;
  email?: string;
  phone_number?: string;
  company_name?: string;
  status?: ContactStatus;
  tags?: string[];
  notes?: string;
  important_dates?: ImportantDates | null;
  address_line1?: string;
  address_line2?: string;
  address_city?: string;
  address_state?: string;
  address_zip?: string;
}

export interface ImportErrorDetail {
  row: number;
  field: string | null;
  error: string;
}

export interface ImportOptions {
  skip_duplicates?: boolean;
  default_status?: string;
  source?: string;
  column_mapping?: Record<string, string>;
}

export interface ContactsListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: ContactStatus;
  sort_by?: ContactSortBy;
  tags?: string;
  tags_match?: "any" | "all" | "none";
  lead_score_min?: number;
  lead_score_max?: number;
  is_qualified?: boolean;
  source?: string;
  company_name?: string;
  created_after?: string;
  created_before?: string;
  enrichment_status?: string;
  filters?: string; // JSON FilterDefinition
  [key: string]: unknown;
}

export interface ContactIdsParams {
  search?: string;
  status?: ContactStatus;
  tags?: string;
  tags_match?: "any" | "all" | "none";
  lead_score_min?: number;
  lead_score_max?: number;
  is_qualified?: boolean;
  source?: string;
  company_name?: string;
  created_after?: string;
  created_before?: string;
  enrichment_status?: string;
  filters?: string;
}

// ---------------------------------------------------------------------------
// Generic CRUD via the existing factory (preserves `.list/.get/.create/...`).
// The factory still uses the untyped axios instance internally; the typed
// surface area below covers the bespoke endpoints.
// ---------------------------------------------------------------------------

const baseApi = createApiClient<Contact, CreateContactRequest, UpdateContactRequest>({
  resourcePath: "contacts",
}) as FullApiClient<Contact, CreateContactRequest, UpdateContactRequest>;

export const contactsApi = {
  ...baseApi,

  listIds: async (workspaceId: string, params: ContactIdsParams = {}): Promise<ContactIdsResponse> => {
    return apiClient.get("/api/v1/workspaces/{workspace_id}/contacts/ids", {
      path: { workspace_id: workspaceId },
      query: params,
    });
  },

  getStats: async (workspaceId: string): Promise<ContactStatsResponse> => {
    return apiClient.get("/api/v1/workspaces/{workspace_id}/contacts/stats", {
      path: { workspace_id: workspaceId },
    });
  },

  bulkDelete: async (workspaceId: string, ids: number[]): Promise<BulkDeleteResponse> => {
    return apiClient.post("/api/v1/workspaces/{workspace_id}/contacts/bulk-delete", {
      path: { workspace_id: workspaceId },
      body: { ids },
    });
  },

  bulkUpdateStatus: async (
    workspaceId: string,
    ids: number[],
    status: ContactStatus,
  ): Promise<BulkUpdateStatusResponse> => {
    return apiClient.post("/api/v1/workspaces/{workspace_id}/contacts/bulk-update-status", {
      path: { workspace_id: workspaceId },
      body: { ids, status },
    });
  },

  getTimeline: async (
    workspaceId: string,
    contactId: number,
    limit: number = 100,
  ): Promise<TimelineItem[]> => {
    const response = await apiClient.get(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/timeline",
      {
        path: { workspace_id: workspaceId, contact_id: contactId },
        query: { limit },
      },
    );
    // The OpenAPI schema models timeline items as a loose object; the
    // frontend type `TimelineItem` is the canonical consumer-facing shape.
    return response as unknown as TimelineItem[];
  },

  getEngagementSummary: async (
    workspaceId: string,
    contactId: number,
  ): Promise<ContactEngagementSummary> => {
    return apiClient.get(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/engagement-summary",
      {
        path: { workspace_id: workspaceId, contact_id: contactId },
      },
    );
  },

  toggleAI: async (
    workspaceId: string,
    contactId: number,
    enabled: boolean,
  ): Promise<AIToggleResponse> => {
    return apiClient.post(
      "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/ai/toggle",
      {
        path: { workspace_id: workspaceId, contact_id: contactId },
        body: { enabled },
      },
    );
  },

  assignAgent: async (
    workspaceId: string,
    contactId: number,
    agentId: string | null,
  ): Promise<ContactAgentAssignResponse> => {
    return apiClient.post("/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/agent", {
      path: { workspace_id: workspaceId, contact_id: contactId },
      body: { agent_id: agentId },
    });
  },

  previewCSV: async (workspaceId: string, file: File): Promise<CSVPreviewResult> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await apiClient.post(
      "/api/v1/workspaces/{workspace_id}/contacts/import/preview",
      {
        path: { workspace_id: workspaceId },
        config: {
          data: formData,
          headers: { "Content-Type": "multipart/form-data" },
        },
      },
    );
    return response as unknown as CSVPreviewResult;
  },

  importCSV: async (
    workspaceId: string,
    file: File,
    options: ImportOptions = {},
  ): Promise<ImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    if (options.skip_duplicates !== undefined) {
      formData.append("skip_duplicates", String(options.skip_duplicates));
    }
    if (options.default_status) {
      formData.append("default_status", options.default_status);
    }
    if (options.source) {
      formData.append("source", options.source);
    }
    if (options.column_mapping) {
      formData.append("column_mapping", JSON.stringify(options.column_mapping));
    }

    const response = await apiClient.post(
      "/api/v1/workspaces/{workspace_id}/contacts/import",
      {
        path: { workspace_id: workspaceId },
        config: {
          data: formData,
          headers: { "Content-Type": "multipart/form-data" },
        },
      },
    );
    return response as unknown as ImportResult;
  },
};
