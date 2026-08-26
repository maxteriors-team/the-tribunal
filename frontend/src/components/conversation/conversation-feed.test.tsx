import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  sourceProvider: "quo" as string | undefined,
  conversationPending: false,
  timeline: [
    {
      id: "message-1",
      type: "sms",
      direction: "inbound",
      timestamp: "2026-08-26T12:00:00Z",
      content: "Mirrored from Quo",
      is_ai: false,
      original_id: "message-1",
      original_type: "sms_message",
      source_provider: "quo",
      external_url: "https://my.quo.com/inbox/conversations/abc",
    },
  ],
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    isPending: state.conversationPending,
    data: {
      items: [
        {
          id: "conversation-1",
          contact_id: 42,
          contact_phone: "+15555550100",
          source_provider: state.sourceProvider,
          ai_enabled: false,
        },
      ],
    },
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock("@/hooks/useAgents", () => ({ useAgents: () => ({ data: { items: [] } }) }));
vi.mock("@/hooks/useContacts", () => ({
  useContactTimeline: () => ({
    data: state.timeline,
    isPending: false,
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
vi.mock("@/lib/contact-store", () => ({
  useContactStore: () => ({
    selectedContact: {
      id: 42,
      first_name: "Ada",
      last_name: "Lovelace",
      phone_number: "+15555550100",
    },
  }),
}));
vi.mock("@/components/conversation/chat-header", () => ({ ChatHeader: () => null }));
vi.mock("@/components/conversation/date-separator", () => ({ DateSeparator: () => null }));
vi.mock("@/components/conversation/message-item", () => ({ MessageItem: () => null }));
vi.mock("@/components/conversation/message-composer", () => ({
  MessageComposer: () => <div>Tribunal composer</div>,
}));
vi.mock("@/components/conversation/teach-ai-dialog", () => ({ TeachAIDialog: () => null }));

import { ConversationFeed } from "@/components/conversation/conversation-feed";

describe("ConversationFeed Quo bridge", () => {
  beforeEach(() => {
    state.sourceProvider = "quo";
    state.conversationPending = false;
  });

  it("replaces the Tribunal composer with a safe Quo reply action", () => {
    render(<ConversationFeed />);

    expect(screen.queryByText("Tribunal composer")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Reply in Quo.*opens in a new tab/i });
    expect(link).toHaveAttribute("href", "https://my.quo.com/inbox/conversations/abc");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("keeps sending controls unavailable until provenance loads", () => {
    state.conversationPending = true;

    render(<ConversationFeed />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading reply controls");
    expect(screen.queryByText("Tribunal composer")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Reply in Quo/i })).not.toBeInTheDocument();
  });

  it("keeps a mixed non-Quo thread writable", () => {
    state.sourceProvider = undefined;

    render(<ConversationFeed />);

    expect(screen.getByText("Tribunal composer")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Reply in Quo/i })).not.toBeInTheDocument();
  });
});
