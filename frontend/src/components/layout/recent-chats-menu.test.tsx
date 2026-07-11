import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecentChatsMenu } from "@/components/layout/recent-chats-menu";
import type { Conversation } from "@/types";

const { listMock, pushMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: { list: listMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "conv-1",
    user_id: "user-1",
    contact_id: 101,
    workspace_phone: "+15550000000",
    contact_phone: "+15551234567",
    channel: "sms",
    status: "active",
    unread_count: 0,
    ai_enabled: true,
    ai_paused: false,
    last_message_preview: "Sounds good, thanks!",
    last_message_at: "2026-07-10T18:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-10T18:00:00Z",
    ...overrides,
  };
}

function renderMenu() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <RecentChatsMenu />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("RecentChatsMenu", () => {
  it("lists chats in the order the API returns and opens one on click", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          id: "conv-newest",
          contact_id: 101,
          contact_phone: "+15551110001",
          last_message_preview: "Freshest thread",
          unread_count: 2,
        }),
        conversation({
          id: "conv-older",
          contact_id: 202,
          contact_phone: "+15551110002",
          last_message_preview: "Older thread",
        }),
      ],
      total: 2,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: "Recent chats" }));

    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("Freshest thread")).toBeInTheDocument();
    expect(within(items[1]).getByText("Older thread")).toBeInTheDocument();
    // Unread total surfaces in the header.
    expect(screen.getByText("2 unread")).toBeInTheDocument();

    await userEvent.click(within(items[0]).getByRole("button"));
    expect(pushMock).toHaveBeenCalledWith("/contacts/101");
  });

  it("shows an empty state when there are no conversations", async () => {
    listMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
      pages: 0,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: "Recent chats" }));

    await waitFor(() =>
      expect(screen.getByText("No conversations yet.")).toBeInTheDocument(),
    );
  });
});
