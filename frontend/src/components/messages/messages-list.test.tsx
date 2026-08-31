import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MessagesList } from "@/components/messages/messages-list";
import { server } from "@/test/msw/server";
import type { Conversation, Message } from "@/types";

const ORIGIN = "http://localhost:3000";

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "ws_1",
}));

function thread(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conv_1",
    workspace_id: "ws_1",
    contact_id: 7,
    contact_name: "Marguerite Alvarez",
    contact_phone: "+15125550101",
    status: "active",
    channel: "sms",
    assigned_agent_id: null,
    ai_enabled: false,
    ai_paused: false,
    unread_count: 0,
    last_message_preview: "Thanks, see you Tuesday",
    last_message_at: "2024-03-02T15:04:00.000Z",
    created_at: "2024-03-01T15:04:00.000Z",
    ...overrides,
  } as Conversation;
}

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: "msg_1",
    conversation_id: "conv_1",
    contact_id: 7,
    direction: "inbound",
    channel: "sms",
    body: "Do you still have my quote?",
    status: "received",
    is_ai: false,
    created_at: "2022-05-04T12:00:00.000Z",
    ...overrides,
  } as Message;
}

/** Serves one page of threads, capturing the query the component asked for. */
function mockThreads(items: Conversation[], captured?: { url?: URL }) {
  server.use(
    http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/conversations`, ({ request }) => {
      if (captured) captured.url = new URL(request.url);
      return HttpResponse.json({
        items,
        total: items.length,
        page: 1,
        page_size: 50,
        pages: 1,
      });
    }),
  );
}

function mockMessages(items: Message[], pages = 1) {
  server.use(
    http.get(
      `${ORIGIN}/api/v1/workspaces/:workspaceId/conversations/:conversationId/messages`,
      ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? "1");
        return HttpResponse.json({
          items: page === 1 ? items : [message({ id: "msg_old", body: "First ever text" })],
          total: pages * items.length,
          page,
          page_size: 50,
          pages,
        });
      },
    ),
  );
}

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MessagesList />
    </QueryClientProvider>,
  );
}

describe("MessagesList", () => {
  it("lists past conversations with who, what, and when", async () => {
    mockThreads([thread()]);
    renderList();

    expect(await screen.findByText("Marguerite Alvarez")).toBeInTheDocument();
    expect(screen.getByText("Thanks, see you Tuesday")).toBeInTheDocument();
    // The date is the whole point of an archive: an operator has to be able to
    // tell a thread from last week from one from two years ago.
    expect(screen.getByText("Mar 2, 2024")).toBeInTheDocument();
  });

  it("searches by contact name and says plainly that message text is not searchable", async () => {
    const captured: { url?: URL } = {};
    mockThreads([thread()], captured);
    renderList();
    await screen.findByText("Marguerite Alvarez");

    await userEvent.type(screen.getByLabelText("Search messages by contact name"), "marguer");

    await waitFor(() => expect(captured.url?.searchParams.get("search")).toBe("marguer"));
    // Encrypted bodies cannot be searched; saying so beats letting someone
    // conclude an old thread is gone.
    expect(screen.getByText(/Message text itself is encrypted/i)).toBeInTheDocument();
  });

  it("opens a thread and pages back to its oldest messages", async () => {
    mockThreads([thread()]);
    mockMessages([message()], 2);
    renderList();

    await userEvent.click(
      await screen.findByRole("button", { name: "View conversation with Marguerite Alvarez" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Do you still have my quote?")).toBeInTheDocument();

    // History older than one page has to stay reachable, or "a long time ago"
    // is exactly what the archive cannot show.
    await userEvent.click(within(dialog).getByRole("button", { name: "Load older messages" }));
    expect(await within(dialog).findByText("First ever text")).toBeInTheDocument();
  });

  it("tells the operator when a search matched nobody", async () => {
    mockThreads([]);
    renderList();

    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });
});
