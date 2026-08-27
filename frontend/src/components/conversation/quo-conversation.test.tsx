import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatHeader } from "@/components/conversation/chat-header";
import { InboundMessageItem } from "@/components/conversation/inbound-message-item";
import type { Conversation, TimelineItem } from "@/types";

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));
vi.mock("@/components/contacts/client-note-dialog", () => ({ ClientNoteDialog: () => null }));

const timelineItem: TimelineItem = {
  id: "message-1",
  type: "sms",
  direction: "inbound",
  timestamp: "2026-08-26T12:00:00Z",
  content: "A mirrored message",
  is_ai: false,
  original_id: "message-1",
  original_type: "sms_message",
  source_provider: "quo",
  external_url: "https://my.quo.com/inbox/conversations/abc",
};

const conversation = (sourceProvider?: string): Conversation => ({
  id: "conversation-1",
  user_id: "user-1",
  workspace_id: "workspace-1",
  contact_id: 42,
  contact_name: "Ada Lovelace",
  workspace_phone: "+15555550999",
  contact_phone: "+15555550100",
  channel: "sms",
  status: "active",
  created_at: "2026-08-26T12:00:00Z",
  updated_at: "2026-08-26T12:00:00Z",
  last_message_at: "2026-08-26T12:00:00Z",
  unread_count: 0,
  ai_enabled: true,
  ai_paused: false,
  source_provider: sourceProvider,
});

const headerProps = {
  workspaceId: "workspace-1",
  contactId: 42,
  contactName: "Ada Lovelace",
  phoneNumber: "+15555550100",
  agents: [],
  hasTimelineItems: true,
  isToggleAIPending: false,
  isAssignAgentPending: false,
  isClearHistoryPending: false,
  isMarkReadPending: false,
  onToggleAI: vi.fn(),
  onAssignAgent: vi.fn(),
  onClearHistory: vi.fn(),
  onMarkRead: vi.fn(),
};

describe("Quo conversation provenance", () => {
  it("labels a mirrored message without exposing a provider exit link", () => {
    render(<InboundMessageItem item={timelineItem} contactName="Ada" />);

    expect(screen.getByText("via Quo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open in Quo/i })).not.toBeInTheDocument();
  });

  it("labels a mirrored call without exposing a provider exit link", () => {
    render(
      <InboundMessageItem
        item={{
          ...timelineItem,
          id: "call-1",
          type: "call",
          original_id: "call-1",
          original_type: "call_record",
          content: "Incoming call",
        }}
        contactName="Ada"
      />,
    );

    expect(screen.getByText("via Quo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open in Quo/i })).not.toBeInTheDocument();
  });

  it("keeps provenance visible but drops an unvalidated external link", () => {
    render(
      <InboundMessageItem
        item={{ ...timelineItem, external_url: "https://not-quo.example/conversations/abc" }}
        contactName="Ada"
      />,
    );

    expect(screen.getByText("via Quo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open in Quo/i })).not.toBeInTheDocument();
  });

  it("removes Tribunal AI and call controls only from Quo threads", () => {
    const { rerender } = render(
      <ChatHeader
        {...headerProps}
        quoPhoneNumber="+15555550999"
        manualMessagingOnly
        conversation={undefined}
      />,
    );

    expect(screen.getByText(/via Quo/)).toHaveTextContent("(555) 555-0999");
    expect(screen.queryByRole("button", { name: /AI On/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Call contact" })).not.toBeInTheDocument();

    rerender(<ChatHeader {...headerProps} conversation={conversation()} />);

    expect(screen.getByRole("button", { name: /AI On/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Call contact" })).toBeInTheDocument();
  });
});
