import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  activeLine: {
    active: true as boolean,
    phone_number_id: "PN_selected" as string | null,
    phone_number: "+14155552671" as string | null,
    has_contact_history: true,
  },
  activeLinePending: false,
  activeLineQueryKey: [] as readonly unknown[],
  conversationPending: false,
  showConversations: true,
  sourceProvider: "quo" as string | undefined,
  timelineArgs: [] as unknown[],
  timeline: [
    {
      id: "message-1",
      type: "sms",
      direction: "inbound",
      timestamp: "2026-08-26T12:00:00Z",
      content: "From the selected Quo line",
      is_ai: false,
      original_id: "message-1",
      original_type: "sms_message",
      source_provider: "quo",
    },
  ],
}));

const { sendMessageMock, sendMessageToContactMock, toastErrorMock } = vi.hoisted(() => ({
  sendMessageMock: vi.fn(),
  sendMessageToContactMock: vi.fn(),
  toastErrorMock: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: readonly unknown[] }) => {
    if (queryKey.includes("quo-active-line")) {
      state.activeLineQueryKey = queryKey;
      return { data: state.activeLine, isPending: state.activeLinePending };
    }
    return {
      isPending: state.conversationPending,
      data: {
        items: state.showConversations
          ? [
              {
                id: "conversation-old",
                contact_id: 42,
                contact_phone: "+14155552672",
                workspace_phone: "+14155550199",
                source_provider: state.sourceProvider,
                ai_enabled: false,
              },
              {
                id: "conversation-selected",
                contact_id: 42,
                contact_phone: "+14155552672",
                workspace_phone: "+14155552671",
                source_provider: state.sourceProvider,
                ai_enabled: false,
              },
            ]
          : [],
      },
    };
  },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock("@/hooks/useAgents", () => ({ useAgents: () => ({ data: { items: [] } }) }));
vi.mock("@/hooks/useContacts", () => ({
  useContactTimeline: (...args: unknown[]) => {
    state.timelineArgs = args;
    return {
      data: state.timeline,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    };
  },
}));
vi.mock("@/hooks/useConversations", () => ({
  useToggleConversationAI: () => ({ isPending: false, mutate: vi.fn() }),
  useAssignAgent: () => ({ isPending: false, mutate: vi.fn() }),
  useClearConversationHistory: () => ({ isPending: false, mutate: vi.fn() }),
  useMarkConversationRead: () => ({ isPending: false, mutate: vi.fn() }),
}));
vi.mock("@/hooks/usePhoneNumbers", () => ({
  usePhoneNumbers: () => ({ data: { items: [] } }),
}));
vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace-1" }));
vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: {
    list: vi.fn(),
    sendMessage: sendMessageMock,
    sendMessageToContact: sendMessageToContactMock,
  },
}));
vi.mock("@/lib/api/integrations", () => ({
  integrationsApi: { getActiveQuoLine: vi.fn() },
}));
vi.mock("@/lib/contact-store", () => ({
  useContactStore: () => ({
    selectedContact: {
      id: 42,
      first_name: "Ada",
      last_name: "Lovelace",
      phone_number: "+14155552672",
    },
  }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastErrorMock },
}));
vi.mock("@/components/conversation/chat-header", () => ({ ChatHeader: () => null }));
vi.mock("@/components/conversation/date-separator", () => ({ DateSeparator: () => null }));
vi.mock("@/components/conversation/message-item", () => ({ MessageItem: () => null }));
vi.mock("@/components/conversation/message-composer", () => ({
  MessageComposer: ({
    message,
    onMessageChange,
    onSend,
    textOnly,
  }: {
    message: string;
    onMessageChange: (value: string) => void;
    onSend: () => Promise<void>;
    textOnly?: boolean;
  }) => (
    <div data-testid="composer" data-text-only={textOnly ? "true" : "false"}>
      <label>
        Draft
        <input
          aria-label="Draft"
          value={message}
          onChange={(event) => onMessageChange(event.target.value)}
        />
      </label>
      <button type="button" onClick={() => void onSend().catch(() => undefined)}>
        Send
      </button>
    </div>
  ),
}));
vi.mock("@/components/conversation/teach-ai-dialog", () => ({ TeachAIDialog: () => null }));

import { ConversationFeed } from "@/components/conversation/conversation-feed";

describe("ConversationFeed Quo CRM sending", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.activeLine = {
      active: true,
      phone_number_id: "PN_selected",
      phone_number: "+14155552671",
      has_contact_history: true,
    };
    state.activeLinePending = false;
    state.activeLineQueryKey = [];
    state.conversationPending = false;
    state.showConversations = true;
    state.sourceProvider = "quo";
    state.timelineArgs = [];
    sendMessageMock.mockResolvedValue({ id: "message-out" });
    sendMessageToContactMock.mockResolvedValue({ id: "message-out" });
  });

  it("selects only the active Quo line and renders the CRM composer", () => {
    render(<ConversationFeed />);

    expect(state.activeLineQueryKey).toContain(42);
    expect(state.timelineArgs[3]).toBe("conversation-selected");
    expect(screen.getByTestId("composer")).toHaveAttribute("data-text-only", "true");
    expect(screen.queryByRole("link", { name: /Reply in Quo/i })).not.toBeInTheDocument();
  });

  it("keeps inactive Quo history hidden after switching to a line without a thread", () => {
    state.showConversations = false;
    render(<ConversationFeed />);

    expect(state.timelineArgs[4]).toBe(false);
    expect(
      screen.getByText("No conversation exists for this contact on the active messaging line."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("composer")).not.toBeInTheDocument();
  });

  it("sends through the fixed conversation with one client request UUID", async () => {
    const user = userEvent.setup();
    render(<ConversationFeed />);

    await user.type(screen.getByRole("textbox", { name: "Draft" }), "Direct reply");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledOnce());
    const [workspaceId, conversationId, body, requestId] = sendMessageMock.mock.calls[0];
    expect([workspaceId, conversationId, body]).toEqual([
      "workspace-1",
      "conversation-selected",
      "Direct reply",
    ]);
    expect(requestId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(sendMessageToContactMock).not.toHaveBeenCalled();
  });

  it("retains the draft and request UUID while delivery status is unknown", async () => {
    const user = userEvent.setup();
    sendMessageMock.mockRejectedValue(new Error("Network Error"));
    render(<ConversationFeed />);

    const draft = screen.getByRole("textbox", { name: "Draft" });
    await user.type(draft, "Uncertain reply");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(draft).toHaveValue("Uncertain reply"));
    const firstRequestId = sendMessageMock.mock.calls[0][3];

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(2));
    expect(sendMessageMock.mock.calls[1][3]).toBe(firstRequestId);
    expect(toastErrorMock).toHaveBeenCalledWith(
      "Delivery status unknown—wait for the message to appear before retrying",
    );
  });

  it("starts a new request when an unknown-status draft is edited", async () => {
    const user = userEvent.setup();
    sendMessageMock.mockRejectedValue(new Error("Network Error"));
    render(<ConversationFeed />);

    const draft = screen.getByRole("textbox", { name: "Draft" });
    await user.type(draft, "Uncertain reply");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(draft).toHaveValue("Uncertain reply"));
    const firstRequestId = sendMessageMock.mock.calls[0][3];

    await user.type(draft, " with correction");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(2));
    expect(sendMessageMock.mock.calls[1][3]).not.toBe(firstRequestId);
  });

  it("uses a new request after a structured definitive provider rejection", async () => {
    const user = userEvent.setup();
    sendMessageMock.mockRejectedValue({
      response: {
        status: 502,
        data: { code: "quo_send_rejected", message: "Quo rejected the message" },
      },
    });
    render(<ConversationFeed />);

    const draft = screen.getByRole("textbox", { name: "Draft" });
    await user.type(draft, "Rejected reply");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(draft).toHaveValue("Rejected reply"));
    const firstRequestId = sendMessageMock.mock.calls[0][3];

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(2));
    expect(sendMessageMock.mock.calls[1][3]).not.toBe(firstRequestId);
  });

  it("keeps controls unavailable until line provenance loads", () => {
    state.activeLinePending = true;
    render(<ConversationFeed />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading reply controls");
    expect(screen.queryByTestId("composer")).not.toBeInTheDocument();
  });

  it("keeps a non-Quo thread writable when the workspace has an active Quo line", () => {
    state.activeLine.has_contact_history = false;
    state.sourceProvider = undefined;
    render(<ConversationFeed />);

    expect(state.timelineArgs[3]).toBeUndefined();
    expect(screen.getByTestId("composer")).toHaveAttribute("data-text-only", "false");
  });
});
