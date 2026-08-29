import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationNotes } from "@/components/conversations/conversation-notes";
import type { ConversationNote } from "@/lib/api/conversation-notes";

/**
 * The rail's job is to keep three things straight that the server enforces but
 * cannot explain in the UI: whose note this is (edits are author-only and a
 * non-author is answered with a 404), which notes a machine wrote, and that a
 * reminder is a real future instant with an offset.
 */
const {
  listMock,
  createMock,
  updateMock,
  deleteMock,
  setReminderMock,
  clearReminderMock,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  createMock: vi.fn(),
  updateMock: vi.fn(),
  deleteMock: vi.fn(),
  setReminderMock: vi.fn(),
  clearReminderMock: vi.fn(),
}));

vi.mock("@/lib/api/conversation-notes", () => ({
  conversationNotesApi: {
    list: listMock,
    create: createMock,
    update: updateMock,
    delete: deleteMock,
    setReminder: setReminderMock,
    clearReminder: clearReminderMock,
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CURRENT_USER_ID = 7;

function makeNote(overrides: Partial<ConversationNote> = {}): ConversationNote {
  return {
    id: "note-1",
    conversation_id: "conv-1",
    body: "Gate code is 4821.",
    source: "human",
    author_user_id: CURRENT_USER_ID,
    author_name: "Dana Rep",
    created_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-08-01T12:00:00Z",
    reminder_at: null,
    reminder_status: null,
    ...overrides,
  };
}

const ownNote = makeNote();
const colleagueNote = makeNote({
  id: "note-2",
  body: "Customer prefers texts after 5pm.",
  author_user_id: 99,
  author_name: "Sam Closer",
});
const quoNote = makeNote({
  id: "note-3",
  body: "Caller asked for a gutter quote.",
  source: "quo_summary",
  author_user_id: null,
  author_name: null,
});

function renderRail(notes: ConversationNote[]) {
  listMock.mockResolvedValue(notes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ConversationNotes
        workspaceId="ws-1"
        conversationId="conv-1"
        currentUserId={CURRENT_USER_ID}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  createMock.mockResolvedValue(makeNote({ id: "note-new" }));
  updateMock.mockResolvedValue(makeNote());
  deleteMock.mockResolvedValue(undefined);
  setReminderMock.mockResolvedValue(makeNote({ reminder_at: "2099-01-01T09:00:00+00:00" }));
  clearReminderMock.mockResolvedValue(makeNote({ reminder_at: null }));
});

describe("ConversationNotes", () => {
  it("lists notes with the author who wrote them", async () => {
    renderRail([ownNote, colleagueNote]);

    expect(await screen.findByText("Gate code is 4821.")).toBeInTheDocument();
    expect(screen.getByText("Dana Rep")).toBeInTheDocument();
    expect(screen.getByText("Customer prefers texts after 5pm.")).toBeInTheDocument();
    expect(screen.getByText("Sam Closer")).toBeInTheDocument();
    expect(listMock).toHaveBeenCalledWith("ws-1", "conv-1");
  });

  it("badges an AI call recap and never offers to edit it", async () => {
    renderRail([quoNote]);

    const note = await screen.findByTestId("note-note-3");
    expect(within(note).getByText("Quo summary")).toBeInTheDocument();
    expect(within(note).getByText("Quo")).toBeInTheDocument();
    expect(within(note).queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
    expect(within(note).queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(within(note).queryByRole("button", { name: /reminder/i })).not.toBeInTheDocument();
  });

  it("hides edit, delete and reminder controls on a colleague's note", async () => {
    renderRail([ownNote, colleagueNote]);

    const theirs = await screen.findByTestId("note-note-2");
    expect(within(theirs).queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
    expect(within(theirs).queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(within(theirs).queryByRole("button", { name: /reminder/i })).not.toBeInTheDocument();

    // Same list, own note: the controls are there, so the absence above is
    // about authorship and not about the rail failing to render buttons.
    const mine = screen.getByTestId("note-note-1");
    expect(within(mine).getByRole("button", { name: /edit/i })).toBeInTheDocument();
    expect(within(mine).getByRole("button", { name: /delete/i })).toBeInTheDocument();
    expect(within(mine).getByRole("button", { name: /set reminder/i })).toBeInTheDocument();
  });

  it("posts the trimmed body when a note is added", async () => {
    const user = userEvent.setup();
    renderRail([]);

    await screen.findByText("No notes yet");
    await user.type(screen.getByLabelText("Add a note"), "  Ladder access is round the back  ");
    await user.click(screen.getByRole("button", { name: "Add note" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith("ws-1", "conv-1", {
        body: "Ladder access is round the back",
      }),
    );
  });

  it("refuses to submit a whitespace-only note", async () => {
    const user = userEvent.setup();
    renderRail([]);

    await screen.findByText("No notes yet");
    const submit = screen.getByRole("button", { name: "Add note" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Add a note"), "    ");
    expect(submit).toBeDisabled();

    await user.click(submit);
    expect(createMock).not.toHaveBeenCalled();
  });

  it("sends a future reminder as an ISO instant carrying a timezone offset", async () => {
    const user = userEvent.setup();
    renderRail([ownNote]);

    const note = await screen.findByTestId("note-note-1");
    await user.click(within(note).getByRole("button", { name: /set reminder/i }));
    fireEvent.change(screen.getByLabelText("Remind me at"), {
      target: { value: "2099-01-01T09:00" },
    });
    await user.click(screen.getByRole("button", { name: "Save reminder" }));

    await waitFor(() => expect(setReminderMock).toHaveBeenCalled());
    const [workspaceId, conversationId, noteId, body] = setReminderMock.mock.calls[0];
    expect([workspaceId, conversationId, noteId]).toEqual(["ws-1", "conv-1", "note-1"]);
    expect(body.due_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/,
    );
    expect(new Date(body.due_at).getTime()).toBeGreaterThan(Date.now());
  });

  it("blocks a past reminder before it reaches the server", async () => {
    const user = userEvent.setup();
    renderRail([ownNote]);

    const note = await screen.findByTestId("note-note-1");
    await user.click(within(note).getByRole("button", { name: /set reminder/i }));
    fireEvent.change(screen.getByLabelText("Remind me at"), {
      target: { value: "2020-01-01T09:00" },
    });
    await user.click(screen.getByRole("button", { name: "Save reminder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Pick a time in the future.");
    expect(setReminderMock).not.toHaveBeenCalled();
  });

  it("clears an existing reminder through the delete-reminder endpoint", async () => {
    const user = userEvent.setup();
    renderRail([makeNote({ reminder_at: "2099-01-01T09:00:00+00:00", reminder_status: "pending" })]);

    const note = await screen.findByTestId("note-note-1");
    expect(within(note).getByText(/Reminder set for/)).toBeInTheDocument();

    await user.click(within(note).getByRole("button", { name: /clear reminder/i }));

    await waitFor(() =>
      expect(clearReminderMock).toHaveBeenCalledWith("ws-1", "conv-1", "note-1"),
    );
  });
});
