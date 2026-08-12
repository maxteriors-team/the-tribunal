import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  RecentChatsMenu,
  formatUnreadBadge,
} from "@/components/layout/recent-chats-menu";
import type { Conversation } from "@/types";

const {
  listMock,
  markReadMock,
  markAllReadMock,
  unreadSummaryMock,
  pushMock,
  useWorkspaceIdMock,
  toastErrorMock,
  toastSuccessMock,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  markReadMock: vi.fn(),
  markAllReadMock: vi.fn(),
  unreadSummaryMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));

vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: {
    list: listMock,
    markRead: markReadMock,
    markAllRead: markAllReadMock,
    getUnreadSummary: unreadSummaryMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("sonner", () => ({
  toast: { error: toastErrorMock, success: toastSuccessMock },
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
  unreadSummaryMock.mockResolvedValue({
    unread_conversations: 0,
    unread_messages: 0,
  });
  markReadMock.mockResolvedValue(conversation({ unread_count: 0 }));
  markAllReadMock.mockResolvedValue({ conversations_marked: 0 });
});

describe("formatUnreadBadge", () => {
  it("shows the exact count up to 99", () => {
    expect(formatUnreadBadge(1)).toBe("1");
    expect(formatUnreadBadge(99)).toBe("99");
  });

  it("caps at 99+ so the badge stays two digits", () => {
    expect(formatUnreadBadge(100)).toBe("99+");
    expect(formatUnreadBadge(4210)).toBe("99+");
  });
});

describe("RecentChatsMenu", () => {
  it("lists chats in the order the API returns and opens one on click", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          id: "conv-newest",
          contact_id: 101,
          contact_name: "Robin Stevanovich",
          contact_phone: "+15551110001",
          last_message_preview: "Freshest thread",
          unread_count: 2,
        }),
        conversation({
          id: "conv-older",
          contact_id: 202,
          contact_name: "Casey Nguyen",
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
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    const items = await screen.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    // Threads are labelled by contact name, not the raw phone number.
    expect(within(items[0]).getByText("Robin Stevanovich")).toBeInTheDocument();
    expect(within(items[0]).queryByText(/555/)).not.toBeInTheDocument();
    expect(within(items[0]).getByText("Freshest thread")).toBeInTheDocument();
    expect(within(items[1]).getByText("Casey Nguyen")).toBeInTheDocument();
    expect(within(items[1]).getByText("Older thread")).toBeInTheDocument();

    await userEvent.click(
      within(items[0]).getByRole("button", { name: /Freshest thread/ }),
    );
    expect(pushMock).toHaveBeenCalledWith("/contacts/101");
  });

  it("shows the workspace unread rollup on the trigger, not the page total", async () => {
    // The menu only fetched one thread, but the workspace has more unread.
    listMock.mockResolvedValue({
      items: [conversation({ unread_count: 2 })],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });
    unreadSummaryMock.mockResolvedValue({
      unread_conversations: 3,
      unread_messages: 7,
    });

    renderMenu();

    const trigger = await screen.findByRole("button", {
      name: "Recent chats, 7 unread",
    });
    expect(within(trigger).getByText("7")).toBeInTheDocument();
    // The badge comes from the rollup alone — no thread list needed.
    expect(listMock).not.toHaveBeenCalled();
  });

  it("does not fetch the thread list until the menu is opened", async () => {
    // This menu renders on every page; fetching threads before it is opened
    // would put a request on every page load for every operator.
    listMock.mockResolvedValue({
      items: [conversation()],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await waitFor(() => expect(unreadSummaryMock).toHaveBeenCalled());
    expect(listMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith("ws-1", { page: 1, page_size: 12 }),
    );
  });

  it("marks a single thread read without navigating", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          id: "conv-unread",
          contact_name: "Robin Stevanovich",
          unread_count: 3,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });
    unreadSummaryMock.mockResolvedValue({
      unread_conversations: 1,
      unread_messages: 3,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Mark Robin Stevanovich as read",
      }),
    );

    await waitFor(() =>
      expect(markReadMock).toHaveBeenCalledWith("ws-1", "conv-unread"),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("clears the unread count when opening an unread thread", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          id: "conv-unread",
          contact_id: 101,
          contact_name: "Robin Stevanovich",
          last_message_preview: "Are you free Tuesday?",
          unread_count: 1,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));
    await userEvent.click(
      await screen.findByRole("button", { name: /Are you free Tuesday\?/ }),
    );

    await waitFor(() =>
      expect(markReadMock).toHaveBeenCalledWith("ws-1", "conv-unread"),
    );
    expect(pushMock).toHaveBeenCalledWith("/contacts/101");
  });

  it("does not fire mark-read when opening an already-read thread", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          contact_id: 101,
          contact_name: "Casey Nguyen",
          last_message_preview: "Older thread",
          unread_count: 0,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));
    await userEvent.click(
      await screen.findByRole("button", { name: /Older thread/ }),
    );

    expect(markReadMock).not.toHaveBeenCalled();
    expect(pushMock).toHaveBeenCalledWith("/contacts/101");
  });

  it("marks every thread read from the menu header", async () => {
    listMock.mockResolvedValue({
      items: [conversation({ unread_count: 2 })],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });
    unreadSummaryMock.mockResolvedValue({
      unread_conversations: 4,
      unread_messages: 9,
    });
    markAllReadMock.mockResolvedValue({ conversations_marked: 4 });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Mark all read" }),
    );

    await waitFor(() => expect(markAllReadMock).toHaveBeenCalledWith("ws-1"));
    expect(toastSuccessMock).toHaveBeenCalledWith(
      "4 conversations marked as read",
    );
  });

  it("hides mark all read when nothing is unread", async () => {
    listMock.mockResolvedValue({
      items: [conversation()],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    await screen.findByText("Recent chats");
    expect(
      screen.queryByRole("button", { name: "Mark all read" }),
    ).not.toBeInTheDocument();
  });

  it("surfaces a mark-read failure instead of silently doing nothing", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({ contact_name: "Robin Stevanovich", unread_count: 1 }),
      ],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });
    markReadMock.mockRejectedValue(new Error("network down"));

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Mark Robin Stevanovich as read",
      }),
    );

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalled());
  });

  it("falls back to the phone number when the thread has no contact name", async () => {
    listMock.mockResolvedValue({
      items: [
        conversation({
          contact_id: null,
          contact_name: null,
          contact_phone: "+15551110003",
        }),
      ],
      total: 1,
      page: 1,
      page_size: 12,
      pages: 1,
    });

    renderMenu();
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    expect(await screen.findByText("+1 (555) 111-0003")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: /Recent chats/ }));

    await waitFor(() =>
      expect(screen.getByText("No conversations yet.")).toBeInTheDocument(),
    );
  });
});
