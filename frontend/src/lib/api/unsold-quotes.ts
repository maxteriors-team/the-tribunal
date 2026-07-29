/**
 * Unsold-quote follow-up settings API client.
 *
 * The operator-owned half of the quiet-quote sequence: whether it runs, which
 * days after a quote is issued it nudges, where the high-value line sits, and
 * the quiet-hours window. Read/written as a whole config through the same
 * settings surface as the pricing config and attach rules
 * (`app/api/v1/settings.py`); the cadence itself is enforced server-side by
 * `app.workers.unsold_quote_worker`, so the client never decides what sends.
 *
 * Types come from the spec-typed client, so this file cannot drift from
 * `app/schemas/unsold_quotes.py`.
 */
import { apiClient, type Schemas } from "@/lib/api/_client";

/** The whole config as stored for a workspace (schema defaults when unset). */
export type UnsoldQuoteSettings = Schemas["UnsoldQuoteSettings"];
/** Partial update; only provided keys are written. */
export type UnsoldQuoteSettingsUpdate = Schemas["UnsoldQuoteSettingsUpdate"];
/** One nudge: when it fires, what it leads with, and which copy it uses. */
export type UnsoldQuoteTouch = Schemas["UnsoldQuoteTouch"];
/** Why a touch is reaching out: price validity, seasonal slots, or financing. */
export type UnsoldQuoteHook = UnsoldQuoteTouch["hook"];

const PATH = "/api/v1/settings/workspaces/{workspace_id}/unsold-quotes" as const;

export const unsoldQuotesApi = {
  /** The workspace's unsold-quote config (schema defaults when never set). */
  get: (workspaceId: string): Promise<UnsoldQuoteSettings> =>
    apiClient.get(PATH, { path: { workspace_id: workspaceId } }),

  /** Update the config (shallow top-level merge; a provided key replaces it). */
  update: (
    workspaceId: string,
    data: UnsoldQuoteSettingsUpdate,
  ): Promise<UnsoldQuoteSettings> =>
    apiClient.put(PATH, { path: { workspace_id: workspaceId }, body: data }),
};
