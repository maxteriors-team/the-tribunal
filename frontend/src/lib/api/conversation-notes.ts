import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import type { components } from "@/lib/api/_generated";

/**
 * Notes filed against a conversation, plus the follow-up reminder a rep can
 * hang off one.
 *
 * Hand-written rather than built from `createApiClient`: the resource is nested
 * under a conversation (not directly workspace-scoped), the list endpoint
 * returns a bare array instead of a paginated envelope, and edits are PATCH.
 * Request/response shapes are pulled from `_generated.ts` so they stay checked
 * against the backend contract rather than re-declared by hand.
 */

export type ConversationNote = components["schemas"]["ConversationNoteResponse"];
export type ConversationNoteCreateRequest = components["schemas"]["ConversationNoteCreate"];
export type ConversationNoteUpdateRequest = components["schemas"]["ConversationNoteUpdate"];
export type NoteReminderRequest = components["schemas"]["NoteReminderCreate"];

/** `human` is a rep observation; `quo_summary` preserves imported recap provenance. */
export type ConversationNoteSource = "human" | "quo_summary";

export type NoteReminderStatus = "pending" | "sent" | "acted" | "dismissed" | "snoozed";

function notesUrl(workspaceId: string, conversationId: string, suffix = ""): string {
  return `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/notes${suffix}`;
}

export const conversationNotesApi = {
  /** Oldest first, the way the rail reads them. */
  list: (workspaceId: string, conversationId: string): Promise<ConversationNote[]> =>
    apiGet<ConversationNote[]>(notesUrl(workspaceId, conversationId)),

  create: (
    workspaceId: string,
    conversationId: string,
    data: ConversationNoteCreateRequest,
  ): Promise<ConversationNote> =>
    apiPost<ConversationNote>(notesUrl(workspaceId, conversationId), data),

  /**
   * Author-only server-side: a non-author gets a 404, not a 403, so the UI has
   * to hide the control rather than rely on the error.
   */
  update: (
    workspaceId: string,
    conversationId: string,
    noteId: string,
    data: ConversationNoteUpdateRequest,
  ): Promise<ConversationNote> =>
    apiPatch<ConversationNote>(notesUrl(workspaceId, conversationId, `/${noteId}`), data),

  delete: async (workspaceId: string, conversationId: string, noteId: string): Promise<void> => {
    await apiDelete(notesUrl(workspaceId, conversationId, `/${noteId}`));
  },

  /** `due_at` must be an ISO 8601 instant with an offset, in the future (422 otherwise). */
  setReminder: (
    workspaceId: string,
    conversationId: string,
    noteId: string,
    data: NoteReminderRequest,
  ): Promise<ConversationNote> =>
    apiPut<ConversationNote>(
      notesUrl(workspaceId, conversationId, `/${noteId}/reminder`),
      data,
    ),

  clearReminder: (
    workspaceId: string,
    conversationId: string,
    noteId: string,
  ): Promise<ConversationNote> =>
    apiDelete<ConversationNote>(notesUrl(workspaceId, conversationId, `/${noteId}/reminder`)),
};
