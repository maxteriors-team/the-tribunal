import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationFeed } from "@/components/conversation/conversation-feed";
import { queryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";
import type { PaginatedResponse } from "@/types/api";
import type { Contact } from "@/types/contact";
import type { Conversation } from "@/types/conversation";

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-1" }));
vi.mock("@/hooks/useCapabilities", () => ({ useCapabilities: () => ({ can: () => true }) }));
vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ data: { items: [
    { id: "agent-1", name: "First agent" }, { id: "agent-2", name: "Second agent" },
  ] } }),
}));
vi.mock("@/hooks/usePhoneNumbers", () => ({ usePhoneNumbers: () => ({ data: { items: [] } }) }));
vi.mock("@/hooks/useContacts", () => ({
  useContactTimeline: () => ({ data: [], isLoading: false, isError: false }),
}));
vi.mock("@/components/contacts/client-note-dialog", () => ({ ClientNoteDialog: () => null }));
vi.mock("@/components/conversation/teach-ai-dialog", () => ({ TeachAIDialog: () => null }));
vi.mock("@/components/conversation/message-composer", () => ({
  MessageComposer: () => <div>Reply composer</div>,
}));

const contact: Contact = {
  id: 42,
  user_id: 1,
  workspace_id: "ws-1",
  first_name: "Same",
  last_name: "Name",
  phone_number: "+12025550100",
  status: "new",
  tags: [],
  lead_score: 0,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};
const oldConversation: Conversation = {
  id: "old-conversation",
  user_id: "user-1",
  workspace_id: "ws-1",
  contact_id: contact.id,
  contact_name: "Same Name",
  workspace_phone: "+12025550101",
  contact_phone: "+12025550100",
  status: "active",
  channel: "sms",
  unread_count: 3,
  assigned_agent_id: "agent-1",
  ai_enabled: true,
  ai_paused: true,
  source_provider: null,
  last_message_at: "2025-01-01T00:00:00Z",
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};
const basePath = "*/api/v1/workspaces/:workspaceId/conversations";
let conversations: Conversation[];
let lookups: URL[];
let mutations: string[];

function renderFeed() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  const view = (selected: Contact) => (
    <QueryClientProvider client={client}>
      <ConversationFeed contact={selected} />
    </QueryClientProvider>
  );
  const rendered = render(view(contact));
  return { client, rerenderContact: (selected: Contact) => rendered.rerender(view(selected)) };
}

beforeEach(() => {
  lookups = [];
  mutations = [];
  // NEWER same-name/phone contacts must not substitute for the selected ID.
  conversations = [
    ...Array.from({ length: 101 }, (_, i) => ({
      ...oldConversation,
      id: `newer-${i}`,
      contact_id: 1000 + i,
      unread_count: 0,
      last_message_at: "2026-09-09T00:00:00Z",
    })),
    { ...oldConversation },
  ];
  server.use(
    http.get(basePath, ({ params, request }) => {
      const url = new URL(request.url);
      lookups.push(url);
      const contactId = url.searchParams.get("contact_id");
      const matching = conversations.filter((row) =>
        row.workspace_id === params.workspaceId &&
        (contactId === null || row.contact_id === Number(contactId))
      );
      const pageSize = Number(url.searchParams.get("page_size") ?? 50);
      return HttpResponse.json({
        items: matching.slice(0, pageSize), total: matching.length,
        page: 1, page_size: pageSize, pages: Math.ceil(matching.length / pageSize),
      });
    }),
    http.post(`${basePath}/:id/ai/toggle`, async ({ params, request }) => {
      const row = conversations.find((item) => item.id === params.id);
      if (!row) return new HttpResponse(null, { status: 404 });
      mutations.push(`toggle:${params.workspaceId}:${params.id}`);
      const body = await request.json() as { enabled: boolean };
      row.ai_enabled = body.enabled;
      return HttpResponse.json({ ai_enabled: row.ai_enabled });
    }),
    http.post(`${basePath}/:id/assign`, async ({ params, request }) => {
      const row = conversations.find((item) => item.id === params.id);
      if (!row) return new HttpResponse(null, { status: 404 });
      mutations.push(`assign:${params.workspaceId}:${params.id}`);
      const body = await request.json() as { agent_id: string };
      row.assigned_agent_id = body.agent_id;
      return HttpResponse.json({ assigned_agent_id: row.assigned_agent_id });
    }),
    http.post(`${basePath}/:id/read`, ({ params }) => {
      const row = conversations.find((item) => item.id === params.id);
      if (!row) return new HttpResponse(null, { status: 404 });
      mutations.push(`read:${params.workspaceId}:${params.id}`);
      row.unread_count = 0;
      return HttpResponse.json(row);
    }),
  );
});

describe("ConversationFeed exact contact lookup", () => {
  it("finds a thread beyond 100 without losing unread or AI state", async () => {
    const { client } = renderFeed();
    await screen.findByText("Reply composer");
    expect(screen.getByText("3 new")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "First agent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI On" })).toBeEnabled();
    expect(lookups).toHaveLength(1);
    expect(lookups[0].searchParams.get("contact_id")).toBe("42");
    expect(lookups[0].searchParams.get("page_size")).toBe("1");
    expect(lookups[0].searchParams.has("search")).toBe(false);
    expect(client.getQueryData<PaginatedResponse<Conversation>>(
      queryKeys.conversations.byContact("ws-1", 42)
    )?.items[0]).toMatchObject({ id: "old-conversation", ai_paused: true });
  });

  it("toggles and assigns the exact old thread, then refreshes its state", async () => {
    const user = userEvent.setup();
    renderFeed();
    await screen.findByText("Reply composer");
    await user.click(screen.getByRole("button", { name: "AI On" }));
    await screen.findByRole("button", { name: "AI Off" });
    await user.click(screen.getByRole("button", { name: "First agent" }));
    await user.click(await screen.findByRole("menuitem", { name: "Second agent" }));
    await screen.findByRole("button", { name: "Second agent" });
    expect(mutations).toEqual([
      "toggle:ws-1:old-conversation", "assign:ws-1:old-conversation",
    ]);
    expect(screen.getByText("3 new")).toBeInTheDocument();
    expect(lookups.every((url) => url.searchParams.get("contact_id") === "42")).toBe(true);
  });

  it("marks only the exact old thread read and updates the contact cache", async () => {
    const user = userEvent.setup();
    const { client } = renderFeed();
    await screen.findByText("3 new");
    await user.click(screen.getByRole("button", { name: "Conversation actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Mark as read" }));
    await waitFor(() => expect(screen.queryByText("3 new")).not.toBeInTheDocument());
    expect(mutations).toEqual(["read:ws-1:old-conversation"]);
    expect(client.getQueryData<PaginatedResponse<Conversation>>(
      queryKeys.conversations.byContact("ws-1", 42)
    )?.items[0].unread_count).toBe(0);
  });

  it("clears the previous contact's controls when the next contact has no thread", async () => {
    const user = userEvent.setup();
    const { rerenderContact } = renderFeed();
    await screen.findByText("Reply composer");
    rerenderContact({ ...contact, id: 43 });
    await waitFor(() => expect(lookups.at(-1)?.searchParams.get("contact_id")).toBe("43"));
    await waitFor(() => expect(screen.queryByText("Loading reply controls…")).not.toBeInTheDocument());
    expect(screen.getByText("No conversation yet")).toBeInTheDocument();
    expect(screen.queryByText("Reply composer")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI Off" })).toBeDisabled();
    expect(screen.queryByText("3 new")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "No Agent" }));
    expect(await screen.findByRole("menuitem", { name: "Second agent" })).toHaveAttribute("aria-disabled", "true");
    expect(mutations).toEqual([]);
  });

  it("finds old imported history without enabling replies, AI or destructive controls", async () => {
    const user = userEvent.setup();
    conversations[101].source_provider = "quo";
    renderFeed();
    await screen.findByText("Imported history");
    expect(screen.getByText("3 new")).toBeInTheDocument();
    expect(screen.queryByText("Reply composer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /AI (On|Off)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "First agent" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Conversation actions" }));
    expect(screen.queryByRole("menuitem", { name: "Clear history" })).not.toBeInTheDocument();
    expect(mutations).toEqual([]);
  });
});
