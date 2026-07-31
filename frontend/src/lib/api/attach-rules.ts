/**
 * Attach-rule settings API client.
 *
 * The operator-owned cross-sell prompt: which primary service asks for which
 * add-on, and how hard. Read/written as a whole config through the same
 * settings surface as the pricing config (`app/api/v1/settings.py`), and
 * enforced server-side on the quote save path — the client never decides
 * whether a prompt fires.
 */
import { apiGet, apiPut } from "@/lib/api";
import type {
  AttachRulesSettings,
  AttachRulesSettingsUpdate,
} from "@/types/sales-wizard";

const base = (workspaceId: string) =>
  `/api/v1/settings/workspaces/${workspaceId}/attach-rules`;

export const attachRulesApi = {
  /** The workspace's attach-rule config (schema defaults when never set). */
  get: (workspaceId: string): Promise<AttachRulesSettings> =>
    apiGet<AttachRulesSettings>(base(workspaceId)),

  /** Update the config (shallow top-level merge; a provided key replaces it). */
  update: (
    workspaceId: string,
    data: AttachRulesSettingsUpdate,
  ): Promise<AttachRulesSettings> =>
    apiPut<AttachRulesSettings>(base(workspaceId), data),
};
