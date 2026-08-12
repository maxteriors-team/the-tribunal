import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  NewMessageNotifier,
  conversationLabel,
  findNewInboundMessages,
  truncatePreview,
} from "@/components/layout/new-message-notifier";
import type { Conversation } from "@/types";

const {
  listMock,
  markReadMock,
  pushMock,
  useWorkspaceIdMock,
  useRecentChatsMock,
  toastMessageMock,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  markReadMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  useRecentChatsMock: vi.fn(),
  toastMessageMock: vi.fn(),
}));

vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: { list: listMock, markRead: markReadMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// Polls are driven through the hook boundary: the notifier's job is to decide
// what to announce given consecutive poll results, and asserting that directly
// avoids depending on React Query's internal notification timing. The real
// query path (fetch -> render) is covered in recent-chats-menu.test.tsx.
vi.mock("@/hooks/useRecentChats", () => ({
  useRecentChats: (...args: unknown[]) => useRecentChatsMock(...args),
  RECENT_CHATS_LIMIT: 12,
  RECENT_CHATS_PARAMS: { page: 1, page_size: 12 },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("sonner", () => ({
  toast: { message: toastMessageMock },
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

function page(items: Conversation[]) {
  return { items, total: items.length, page: 1, page_size: 12, pages: 1 };
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  useRecentChatsMock.mockReturnValue({ data: undefined });
  markReadMock.mockResolvedValue(conversation({ unread_count: 0 }));
});

describe("conversationLabel", () => {
  it("prefers the contact name", () => {
    expect(
      conversationLabel(conversation({ contact_name: "Robin Stevanovich" })),
    ).toBe("Robin Stevanovich");
  });

  it("falls back to a formatted phone number when unnamed", () => {
    expect(
      conversationLabel(
        conversation({ contact_name: null, contact_phone: "+15551110003" }),
      ),
    ).toBe("+1 (555) 111-0003");
  });

  it("ignores a whitespace-only name", () => {
    expect(
      conversationLabel(
        conversation({ contact_name: "   ", contact_phone: "+15551110003" }),
      ),
    ).toBe("+1 (555) 111-0003");
  });
});

describe("truncatePreview", () => {
  it("passes short previews through untouched", () => {
    expect(truncatePreview("Are you free Tuesday?")).toBe(
      "Are you free Tuesday?",
    );
  });

  it("ellipsizes long bodies so the toast stays one glance", () => {
    const result = truncatePreview("x".repeat(400));
    expect(result).toHaveLength(120);
    expect(result.endsWith("…")).toBe(true);
  });

  it("describes an empty preview rather than showing a blank toast", () => {
    expect(truncatePreview(null)).toBe("New message");
    expect(truncatePreview("   ")).toBe("New message");
  });
});

describe("findNewInboundMessages", () => {
  const unread = conversation({
    id: "conv-a",
    unread_count: 1,
    last_message_at: "2026-07-10T18:00:00Z",
  });

  it("announces nothing before a baseline exists", () => {
    // Otherwise signing in with a full inbox would fire a toast per thread.
    expect(findNewInboundMessages(null, [unread])).toEqual([]);
  });

  it("announces a thread whose last message advanced", () => {
    const previous = new Map([["conv-a", Date.parse("2026-07-10T18:00:00Z")]]);
    const arrived = conversation({
      id: "conv-a",
      unread_count: 2,
      last_message_at: "2026-07-10T18:05:00Z",
    });

    expect(findNewInboundMessages(previous, [arrived])).toEqual([arrived]);
  });

  it("does not re-announce a thread that is still unread but unchanged", () => {
    const previous = new Map([["conv-a", Date.parse("2026-07-10T18:00:00Z")]]);
    expect(findNewInboundMessages(previous, [unread])).toEqual([]);
  });

  it("announces a thread that appeared since the last poll", () => {
    const previous = new Map([["conv-other", Date.now()]]);
    expect(findNewInboundMessages(previous, [unread])).toEqual([unread]);
  });

  it("ignores read threads", () => {
    const previous = new Map([["conv-other", Date.now()]]);
    const read = conversation({ id: "conv-a", unread_count: 0 });
    expect(findNewInboundMessages(previous, [read])).toEqual([]);
  });

  it("ignores threads with no last message timestamp", () => {
    const previous = new Map([["conv-other", Date.now()]]);
    const noTimestamp = conversation({
      id: "conv-a",
      unread_count: 1,
      last_message_at: null,
    });
    expect(findNewInboundMessages(previous, [noTimestamp])).toEqual([]);
  });
});

describe("NewMessageNotifier", () => {
  /**
   * Render with the first poll already returned, establishing the baseline,
   * then `poll()` plays the next snapshot and re-renders.
   */
  function renderNotifier(initial: Conversation[]) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    useRecentChatsMock.mockReturnValue({ data: page(initial) });

    // A fresh element per render: passing the same element object back to
    // `rerender` lets React bail out of the subtree entirely.
    const ui = () => (
      <QueryClientProvider client={client}>
        <NewMessageNotifier />
      </QueryClientProvider>
    );
    const view = render(ui());

    const poll = (items: Conversation[]) => {
      useRecentChatsMock.mockReturnValue({ data: page(items) });
      view.rerender(ui());
    };

    return { ...view, client, poll };
  }

  it("stays silent on the first poll", () => {
    // A full inbox at sign-in must not fire a toast per unread thread.
    renderNotifier([conversation({ unread_count: 3, contact_name: "Robin" })]);

    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("toasts the sender and preview when a message arrives", () => {
    const { poll } = renderNotifier([
      conversation({
        id: "conv-a",
        contact_name: "Robin Stevanovich",
        unread_count: 0,
        last_message_at: "2026-07-10T18:00:00Z",
      }),
    ]);

    poll([
      conversation({
        id: "conv-a",
        contact_name: "Robin Stevanovich",
        unread_count: 1,
        last_message_preview: "Are you free Tuesday?",
        last_message_at: "2026-07-10T18:05:00Z",
      }),
    ]);

    expect(toastMessageMock).toHaveBeenCalledTimes(1);
    const [title, options] = toastMessageMock.mock.calls[0];
    expect(title).toBe("Robin Stevanovich");
    expect(options.description).toBe("Are you free Tuesday?");
    // Stable id: a re-fire for the same thread replaces rather than stacks.
    expect(options.id).toBe("new-message-conv-a");
    expect(options.action.label).toBe("Open");
    expect(options.cancel.label).toBe("Mark read");
  });

  it("does not re-toast a thread that stays unread across polls", () => {
    const arrived = conversation({
      id: "conv-a",
      unread_count: 1,
      last_message_at: "2026-07-10T18:05:00Z",
    });

    const { poll } = renderNotifier([
      conversation({
        id: "conv-a",
        unread_count: 0,
        last_message_at: "2026-07-10T18:00:00Z",
      }),
    ]);

    poll([arrived]);
    poll([arrived]);
    poll([arrived]);

    expect(toastMessageMock).toHaveBeenCalledTimes(1);
  });

  it("opens the thread and clears it from the toast action", async () => {
    const { poll } = renderNotifier([
      conversation({ id: "conv-a", unread_count: 0 }),
    ]);

    poll([
      conversation({
        id: "conv-a",
        contact_id: 101,
        unread_count: 1,
        last_message_at: "2026-07-10T18:05:00Z",
      }),
    ]);

    toastMessageMock.mock.calls[0][1].action.onClick();

    await waitFor(() =>
      expect(markReadMock).toHaveBeenCalledWith("ws-1", "conv-a"),
    );
    expect(pushMock).toHaveBeenCalledWith("/contacts/101");
  });

  it("clears the thread from the toast without navigating", async () => {
    const { poll } = renderNotifier([
      conversation({ id: "conv-a", unread_count: 0 }),
    ]);

    poll([
      conversation({
        id: "conv-a",
        unread_count: 1,
        last_message_at: "2026-07-10T18:05:00Z",
      }),
    ]);

    toastMessageMock.mock.calls[0][1].cancel.onClick();

    await waitFor(() =>
      expect(markReadMock).toHaveBeenCalledWith("ws-1", "conv-a"),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("omits the open action for a thread with no linked contact", () => {
    const { poll } = renderNotifier([
      conversation({ id: "conv-a", unread_count: 0 }),
    ]);

    poll([
      conversation({
        id: "conv-a",
        contact_id: null,
        unread_count: 1,
        last_message_at: "2026-07-10T18:05:00Z",
      }),
    ]);

    expect(toastMessageMock).toHaveBeenCalledTimes(1);
    expect(toastMessageMock.mock.calls[0][1].action).toBeUndefined();
  });

  it("polls the workspace the operator is in", () => {
    renderNotifier([conversation()]);

    expect(useRecentChatsMock).toHaveBeenCalledWith("ws-1");
  });

  it("re-baselines on workspace switch so the new inbox stays silent", () => {
    const { poll } = renderNotifier([
      conversation({
        id: "conv-a",
        unread_count: 0,
        last_message_at: "2026-07-10T18:00:00Z",
      }),
    ]);

    // Switching workspaces swaps in a different inbox; its unread threads are
    // not new arrivals for this operator's session.
    useWorkspaceIdMock.mockReturnValue("ws-2");
    poll([
      conversation({
        id: "conv-other-workspace",
        unread_count: 5,
        last_message_at: "2026-07-10T19:00:00Z",
      }),
    ]);

    expect(toastMessageMock).not.toHaveBeenCalled();
  });
});