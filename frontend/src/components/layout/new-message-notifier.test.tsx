import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  NewMessageNotifier,
  conversationLabel,
  findNewInboundMessages,
  truncatePreview,
} from "@/components/layout/new-message-notifier";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import type { Conversation } from "@/types";

const {
  listMock,
  markReadMock,
  pushMock,
  useWorkspaceIdMock,
  capabilitiesMock,
  useUnreadSummaryMock,
  toastMessageMock,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  markReadMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  capabilitiesMock: vi.fn(),
  useUnreadSummaryMock: vi.fn(),
  toastMessageMock: vi.fn(),
}));

vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: { list: listMock, markRead: markReadMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// This notifier is `crm:read`-gated; role behaviour lives in
// `header-chat-role-gating.test.tsx`. Here every case is an office role.
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

// The unread rollup is driven through the hook boundary so polls are explicit;
// everything downstream of it (the on-demand list fetch, the cache entry it
// writes) runs for real against a live QueryClient.
vi.mock("@/hooks/useConversations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useConversations")>()),
  useUnreadSummary: (...args: unknown[]) => useUnreadSummaryMock(...args),
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
  capabilitiesMock.mockReturnValue({
    tier: roleTier("owner"),
    can: (capability: Capability) => roleCan("owner", capability),
  });
  useUnreadSummaryMock.mockReturnValue({ data: undefined });
  listMock.mockResolvedValue(page([]));
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
  function summary(unreadMessages: number, unreadConversations = 1) {
    return {
      data: {
        unread_messages: unreadMessages,
        unread_conversations: unreadMessages === 0 ? 0 : unreadConversations,
      },
    };
  }

  /**
   * Render with an opening rollup, then `poll()` plays the next rollup value
   * and the thread list the notifier would fetch in response.
   */
  function renderNotifier(initialUnread: number, items: Conversation[] = []) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    useUnreadSummaryMock.mockReturnValue(summary(initialUnread));
    listMock.mockResolvedValue(page(items));

    // A fresh element per render: passing the same element object back to
    // `rerender` lets React bail out of the subtree entirely.
    const ui = () => (
      <QueryClientProvider client={client}>
        <NewMessageNotifier />
      </QueryClientProvider>
    );
    const view = render(ui());

    const poll = async (unreadMessages: number, next: Conversation[]) => {
      useUnreadSummaryMock.mockReturnValue(summary(unreadMessages));
      listMock.mockResolvedValue(page(next));
      view.rerender(ui());
      // Let the on-demand fetch and its toasts settle.
      await waitFor(() => {});
    };

    return { ...view, client, poll };
  }

  it("never fetches the thread list while the inbox is empty", async () => {
    // This is what keeps the app shell to a single request per page.
    const { poll } = renderNotifier(0);
    await poll(0, []);

    expect(listMock).not.toHaveBeenCalled();
    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("stays silent when unread threads are already waiting at sign-in", async () => {
    renderNotifier(3, [
      conversation({ unread_count: 3, contact_name: "Robin" }),
    ]);

    // It fetches once to learn what was already there, but announces nothing.
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));
    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("toasts the sender and preview when a message arrives", async () => {
    const { poll } = renderNotifier(0);

    await poll(1, [
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

  it("does not fetch again while the rollup holds steady", async () => {
    const arrived = conversation({
      id: "conv-a",
      unread_count: 1,
      last_message_at: "2026-07-10T18:05:00Z",
    });

    const { poll } = renderNotifier(0);
    await poll(1, [arrived]);
    expect(listMock).toHaveBeenCalledTimes(1);

    // An unread thread nobody has touched is not a new arrival.
    await poll(1, [arrived]);
    await poll(1, [arrived]);

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(toastMessageMock).toHaveBeenCalledTimes(1);
  });

  it("does not fetch or toast when the rollup shrinks", async () => {
    const { poll } = renderNotifier(0);
    await poll(3, [
      conversation({ id: "conv-a", unread_count: 3, last_message_at: "2026-07-10T18:05:00Z" }),
    ]);
    toastMessageMock.mockClear();
    listMock.mockClear();

    // The operator read something; nothing arrived.
    await poll(1, []);

    expect(listMock).not.toHaveBeenCalled();
    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("opens the thread and clears it from the toast action", async () => {
    const { poll } = renderNotifier(0);

    await poll(1, [
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
    const { poll } = renderNotifier(0);

    await poll(1, [
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

  it("omits the open action for a thread with no linked contact", async () => {
    const { poll } = renderNotifier(0);

    await poll(1, [
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

  it("survives a failed list fetch and recovers on the next arrival", async () => {
    const { poll } = renderNotifier(0);

    useUnreadSummaryMock.mockReturnValue(summary(1));
    listMock.mockRejectedValueOnce(new Error("network"));
    await poll(1, []);
    expect(toastMessageMock).not.toHaveBeenCalled();

    await poll(2, [
      conversation({
        id: "conv-a",
        unread_count: 1,
        last_message_at: "2026-07-10T18:05:00Z",
      }),
    ]);

    expect(toastMessageMock).toHaveBeenCalledTimes(1);
  });

  it("watches the workspace the operator is in", () => {
    renderNotifier(0);

    expect(useUnreadSummaryMock).toHaveBeenCalledWith("ws-1");
  });

  it("re-baselines on workspace switch so the new inbox stays silent", async () => {
    const { poll } = renderNotifier(0);

    // Switching workspaces swaps in a different inbox; its unread threads are
    // not new arrivals for this operator's session.
    useWorkspaceIdMock.mockReturnValue("ws-2");
    await poll(5, [
      conversation({
        id: "conv-other-workspace",
        unread_count: 5,
        last_message_at: "2026-07-10T19:00:00Z",
      }),
    ]);

    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("makes no requests at all without a workspace", async () => {
    useWorkspaceIdMock.mockReturnValue(null);

    const { poll } = renderNotifier(0);
    await poll(3, [conversation({ unread_count: 3 })]);

    expect(listMock).not.toHaveBeenCalled();
    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it("makes no requests for a field technician, even on a warm rollup", async () => {
    // The rollup query is disabled for this role, but React Query still hands
    // back whatever an earlier session cached under the same key — and the
    // list fetch below is an imperative `fetchQuery` that ignores `enabled`.
    // Without the capability check in the effect, that cache would buy a 403.
    capabilitiesMock.mockReturnValue({
      tier: roleTier("technician"),
      can: (capability: Capability) => roleCan("technician", capability),
    });

    const { poll } = renderNotifier(3);
    await poll(9, [conversation({ unread_count: 9 })]);

    expect(listMock).not.toHaveBeenCalled();
    expect(toastMessageMock).not.toHaveBeenCalled();
  });
});