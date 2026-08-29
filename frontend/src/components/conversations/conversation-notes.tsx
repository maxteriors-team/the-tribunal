"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Pencil, Sparkles, StickyNote, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationNotesApi, type ConversationNote } from "@/lib/api/conversation-notes";
import { conversationsApi } from "@/lib/api/conversations";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { formatDateTime, formatRelative, toIsoWithOffset } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useAuth } from "@/providers/auth-provider";

/** Server-side cap. Enforced here too so a long paste fails at the keyboard, not on submit. */
const MAX_NOTE_LENGTH = 5000;
/** Only surface the counter when the limit is actually within reach. */
const COUNTER_VISIBLE_FROM = 200;

interface ConversationNotesProps {
  workspaceId: string;
  conversationId: string;
  /**
   * The signed-in user. The API is author-only for edits, deletes and
   * reminders — and answers a non-author with 404 — so controls are hidden
   * rather than shown and then rejected.
   */
  currentUserId: number | null;
  className?: string;
}

function isQuoSummary(note: ConversationNote): boolean {
  return note.source === "quo_summary";
}

function authorLabel(note: ConversationNote): string {
  if (isQuoSummary(note)) return "Quo";
  return note.author_name?.trim() || "Teammate";
}

/**
 * The conversation's notes rail.
 *
 * Two kinds of note share the list: what a rep typed, and Quo's AI recap of a
 * call. They are badged apart on purpose — a recap read as a colleague's
 * first-hand observation is how a rep ends up repeating a machine's guess to a
 * customer.
 */
export function ConversationNotes({
  workspaceId,
  conversationId,
  currentUserId,
  className,
}: ConversationNotesProps) {
  const queryClient = useQueryClient();

  const [draft, setDraft] = useState("");
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [reminderNoteId, setReminderNoteId] = useState<string | null>(null);
  const [reminderDraft, setReminderDraft] = useState("");
  const [reminderError, setReminderError] = useState<string | null>(null);

  const closeReminderEditor = () => {
    setReminderNoteId(null);
    setReminderDraft("");
    setReminderError(null);
  };

  const notesQuery = useQuery({
    queryKey: queryKeys.conversations.notes(workspaceId, conversationId),
    queryFn: () => conversationNotesApi.list(workspaceId, conversationId),
    enabled: !!workspaceId && !!conversationId,
  });

  const invalidateNotes = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.conversations.notes(workspaceId, conversationId),
    });
  };

  const createMutation = useMutation({
    mutationFn: (body: string) =>
      conversationNotesApi.create(workspaceId, conversationId, { body }),
    onSuccess: () => {
      setDraft("");
      toast.success("Note added");
      invalidateNotes();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to add note")),
  });

  const updateMutation = useMutation({
    mutationFn: (input: { noteId: string; body: string }) =>
      conversationNotesApi.update(workspaceId, conversationId, input.noteId, {
        body: input.body,
      }),
    onSuccess: () => {
      setEditingNoteId(null);
      setEditDraft("");
      toast.success("Note updated");
      invalidateNotes();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to update note")),
  });

  const deleteMutation = useMutation({
    mutationFn: (noteId: string) =>
      conversationNotesApi.delete(workspaceId, conversationId, noteId),
    onSuccess: () => {
      toast.success("Note deleted");
      invalidateNotes();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete note")),
  });

  const setReminderMutation = useMutation({
    mutationFn: (input: { noteId: string; dueAt: string }) =>
      conversationNotesApi.setReminder(workspaceId, conversationId, input.noteId, {
        due_at: input.dueAt,
      }),
    onSuccess: () => {
      closeReminderEditor();
      toast.success("Reminder set");
      invalidateNotes();
    },
    onError: (err: unknown) => {
      // The server re-checks that the due date is in the future; show its words
      // inline instead of leaving the picker looking like it worked.
      const message = getApiErrorMessage(err, "Failed to set reminder");
      setReminderError(message);
      toast.error(message);
    },
  });

  const clearReminderMutation = useMutation({
    mutationFn: (noteId: string) =>
      conversationNotesApi.clearReminder(workspaceId, conversationId, noteId),
    onSuccess: () => {
      toast.success("Reminder cleared");
      invalidateNotes();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to clear reminder")),
  });

  const notes = notesQuery.data ?? [];
  const remaining = MAX_NOTE_LENGTH - draft.length;

  const submitDraft = () => {
    const body = draft.trim();
    if (!body || createMutation.isPending) return;
    createMutation.mutate(body);
  };

  const startEditing = (note: ConversationNote) => {
    setEditingNoteId(note.id);
    setEditDraft(note.body);
  };

  const submitEdit = (noteId: string) => {
    const body = editDraft.trim();
    if (!body || updateMutation.isPending) return;
    updateMutation.mutate({ noteId, body });
  };

  const openReminderEditor = (note: ConversationNote) => {
    setReminderNoteId(note.id);
    setReminderDraft("");
    setReminderError(null);
  };

  const submitReminder = (noteId: string) => {
    if (setReminderMutation.isPending) return;
    if (!reminderDraft) {
      setReminderError("Pick a date and time.");
      return;
    }
    const dueAt = new Date(reminderDraft);
    if (Number.isNaN(dueAt.getTime())) {
      setReminderError("That date isn't valid.");
      return;
    }
    // The API rejects a past due date with a 422; catching it here keeps the
    // rep from watching a round trip fail for something the browser knows.
    if (dueAt.getTime() <= Date.now()) {
      setReminderError("Pick a time in the future.");
      return;
    }
    setReminderError(null);
    setReminderMutation.mutate({ noteId, dueAt: toIsoWithOffset(dueAt) });
  };

  return (
    <div
      className={cn("flex h-full flex-col overflow-hidden bg-background", className)}
      data-slot="conversation-notes"
    >
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <StickyNote className="h-4 w-4 text-muted-foreground" />
        <h2 className="font-semibold">Notes</h2>
        {notes.length > 0 ? (
          <span className="text-xs text-muted-foreground">{notes.length}</span>
        ) : null}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {notesQuery.isPending ? (
          <PageLoadingState className="min-h-[160px]" message="Loading notes…" />
        ) : notesQuery.isError ? (
          <PageErrorState
            className="min-h-[160px]"
            message="We couldn't load the notes for this conversation."
            onRetry={() => void notesQuery.refetch()}
          />
        ) : notes.length === 0 ? (
          <PageEmptyState
            className="min-h-[160px]"
            icon={<StickyNote className="size-8" />}
            title="No notes yet"
            description="Anything you jot here stays with the conversation."
          />
        ) : (
          <ul className="space-y-2 p-3">
            {notes.map((note) => {
              const quoSummary = isQuoSummary(note);
              // Quo recaps have no author, so `null === null` would otherwise
              // hand every rep edit rights over the AI's notes.
              const isOwnNote =
                !quoSummary && currentUserId !== null && note.author_user_id === currentUserId;
              const isEditing = editingNoteId === note.id;
              const isSettingReminder = reminderNoteId === note.id;

              return (
                <li key={note.id} className="rounded-md border p-3" data-testid={`note-${note.id}`}>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-sm font-medium">{authorLabel(note)}</span>
                    {quoSummary ? (
                      <Badge variant="secondary" className="gap-1">
                        <Sparkles aria-hidden="true" />
                        Quo summary
                      </Badge>
                    ) : null}
                    <span
                      className="ml-auto text-xs text-muted-foreground"
                      title={formatDateTime(note.created_at)}
                    >
                      {formatRelative(note.created_at)}
                    </span>
                  </div>

                  {isEditing ? (
                    <div className="mt-2 space-y-2">
                      <Label htmlFor={`note-${note.id}-edit`} className="sr-only">
                        Edit note
                      </Label>
                      <Textarea
                        id={`note-${note.id}-edit`}
                        value={editDraft}
                        maxLength={MAX_NOTE_LENGTH}
                        onChange={(event) => setEditDraft(event.target.value)}
                        rows={3}
                      />
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditingNoteId(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => submitEdit(note.id)}
                          disabled={!editDraft.trim() || updateMutation.isPending}
                        >
                          {updateMutation.isPending ? "Saving…" : "Save"}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-1 whitespace-pre-wrap text-sm">{note.body}</p>
                  )}

                  {note.reminder_at ? (
                    <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Bell className="size-3" aria-hidden="true" />
                      <span>Reminder set for {formatDateTime(note.reminder_at)}</span>
                      {note.reminder_status && note.reminder_status !== "pending" ? (
                        <Badge variant="outline" className="text-[10px]">
                          {note.reminder_status}
                        </Badge>
                      ) : null}
                    </p>
                  ) : null}

                  {isOwnNote && isSettingReminder ? (
                    <div className="mt-2 space-y-2">
                      <Label htmlFor={`note-${note.id}-reminder`} className="text-xs">
                        Remind me at
                      </Label>
                      <Input
                        id={`note-${note.id}-reminder`}
                        type="datetime-local"
                        className="h-8"
                        value={reminderDraft}
                        onChange={(event) => {
                          setReminderDraft(event.target.value);
                          setReminderError(null);
                        }}
                      />
                      {reminderError ? (
                        <p role="alert" className="text-xs text-destructive">
                          {reminderError}
                        </p>
                      ) : null}
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={closeReminderEditor}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => submitReminder(note.id)}
                          disabled={setReminderMutation.isPending}
                        >
                          {setReminderMutation.isPending ? "Saving…" : "Save reminder"}
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  {isOwnNote && !isEditing ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        onClick={() => startEditing(note)}
                      >
                        <Pencil className="size-3" aria-hidden="true" />
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        onClick={() => deleteMutation.mutate(note.id)}
                        disabled={deleteMutation.isPending}
                      >
                        <Trash2 className="size-3" aria-hidden="true" />
                        Delete
                      </Button>
                      {note.reminder_at ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={() => clearReminderMutation.mutate(note.id)}
                          disabled={clearReminderMutation.isPending}
                        >
                          <BellOff className="size-3" aria-hidden="true" />
                          Clear reminder
                        </Button>
                      ) : isSettingReminder ? null : (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={() => openReminderEditor(note)}
                        >
                          <Bell className="size-3" aria-hidden="true" />
                          Set reminder
                        </Button>
                      )}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </ScrollArea>

      <div className="shrink-0 space-y-2 border-t p-3">
        <Label htmlFor="conversation-note-body" className="sr-only">
          Add a note
        </Label>
        <Textarea
          id="conversation-note-body"
          value={draft}
          maxLength={MAX_NOTE_LENGTH}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="What should the next person know?"
          rows={3}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            {remaining <= COUNTER_VISIBLE_FROM ? `${remaining} characters left` : null}
          </span>
          <Button
            type="button"
            size="sm"
            onClick={submitDraft}
            disabled={!draft.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? "Adding…" : "Add note"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Layout-facing wrapper: resolves the workspace, the signed-in user and the
 * conversation for the selected contact, the same way the neighbouring rails do,
 * so the console can drop it in with only a `className`.
 */
export function ConversationNotesRail({ className }: { className?: string }) {
  const workspaceId = useWorkspaceId();
  const { user } = useAuth();
  const { selectedContact } = useContactStore();

  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }),
    enabled: !!workspaceId && !!selectedContact,
  });

  const conversation = conversationsData?.items?.find(
    (candidate) => candidate.contact_id === selectedContact?.id,
  );

  if (!workspaceId || !conversation) {
    return (
      <div className={cn("flex h-full flex-col overflow-hidden bg-background", className)}>
        <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
          <StickyNote className="h-4 w-4 text-muted-foreground" />
          <h2 className="font-semibold">Notes</h2>
        </div>
        <PageEmptyState
          className="min-h-0 flex-1"
          icon={<StickyNote className="size-8" />}
          title="No conversation yet"
          description="Notes attach to a conversation, so start one first."
        />
      </div>
    );
  }

  return (
    <ConversationNotes
      className={className}
      workspaceId={workspaceId}
      conversationId={conversation.id}
      currentUserId={user?.id ?? null}
    />
  );
}
