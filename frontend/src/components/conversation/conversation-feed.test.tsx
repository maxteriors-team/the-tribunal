import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  queriedKeys: [] as (readonly unknown[])[],
  sourceProvider: "legacy_import" as string | undefined,
  timeline: [
    {
      id: "message-1",
      type: "sms",
      direction: "inbound",
      timestamp: "2026-08-26T12:00:00Z",
      content: "Archived provider message",
      is_ai: false,
      original_id: "message-1",
      original_type: "sms_message",
      source_provider: "legacy_import",
    },
  ],
}));

const { sendMessageMock, sendMessageToContactMock } = vi.hoisted(() => ({
  sendMessageMock: vi.fn(),
  sendMessageToContactMock: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: readonly unknown[] }) => {
    state.queriedKeys.push(queryKey);
    return {
      isPending: false,
      data: {
        items: [
          {
            id: "conversation-1",
            contact_id: 42,
            contact_phone: "+14155552672",
            workspace_phone: "+14155550199",
            source_provider: state.sourceProvider,
            ai_enabled: false,
          },
        ],
      },
    };
  },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock("@/hooks/useAgents", () => ({ useAgents: () => ({ data: { items: [] } }) }));
vi.mock("@/hooks/useContacts", () => ({
  useContactTimeline: () => ({
    data: state.timeline,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
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
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/conversation/chat-header", () => ({ ChatHeader: () => null }));
vi.mock("@/components/conversation/date-separator", () => ({ DateSeparator: () => null }));
vi.mock("@/components/conversation/message-item", () => ({ MessageItem: () => null }));
vi.mock("@/components/conversation/message-composer", () => ({
  MessageComposer: ({
    message,
    onMessageChange,
    onSend,
  }: {
    message: string;
    onMessageChange: (value: string) => void;
    onSend: () => Promise<void>;
  }) => (
    <div data-testid="composer">
      <input
        aria-label="Draft"
        value={message}
        onChange={(event) => onMessageChange(event.target.value)}
      />
      <button type="button" onClick={() => void onSend()}>
        Send
      </button>
    </div>
  ),
}));
vi.mock("@/components/conversation/teach-ai-dialog", () => ({ TeachAIDialog: () => null }));

import { ConversationFeed } from "@/components/conversation/conversation-feed";

describe("ConversationFeed imported-provider safeguards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.queriedKeys = [];
    state.sourceProvider = "legacy_import";
    sendMessageToContactMock.mockResolvedValue({ id: "message-out" });
  });

  it("shows imported history without loading provider controls or a composer", () => {
    render(<ConversationFeed />);

    expect(state.queriedKeys.flat()).not.toContain("quo-active-line");
    expect(screen.queryByTestId("composer")).not.toBeInTheDocument();
    expect(sendMessageMock).not.toHaveBeenCalled();
    expect(sendMessageToContactMock).not.toHaveBeenCalled();
  });

  it("keeps native conversations writable through the native contact send path", async () => {
    const user = userEvent.setup();
    state.sourceProvider = undefined;
    render(<ConversationFeed />);

    await user.type(screen.getByRole("textbox", { name: "Draft" }), "Native reply");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sendMessageToContactMock).toHaveBeenCalledOnce());
    expect(sendMessageToContactMock).toHaveBeenCalledWith(
      "workspace-1",
      42,
      "Native reply",
      undefined,
      undefined,
    );
    expect(sendMessageMock).not.toHaveBeenCalled();
  });
});
