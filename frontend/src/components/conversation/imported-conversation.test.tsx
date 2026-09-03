import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));
vi.mock("@/components/contacts/client-note-dialog", () => ({ ClientNoteDialog: () => null }));

import { ChatHeader } from "@/components/conversation/chat-header";
import { MessageItemShell } from "@/components/conversation/message-item-shell";
import type { Conversation, TimelineItem } from "@/types";

const importedConversation: Conversation = {
  id: "conversation-1",
  workspace_id: "workspace-1",
  contact_id: 42,
  user_id: "user-1",
  workspace_phone: "+14155550199",
  contact_phone: "+14155552671",
  status: "active",
  channel: "sms",
  ai_enabled: false,
  ai_paused: false,
  unread_count: 0,
  last_message_preview: "Archived message",
  last_message_at: "2026-08-26T12:00:00Z",
  last_message_direction: "inbound",
  source_provider: "legacy_import",
  followup_enabled: false,
  followup_delay_hours: 24,
  followup_max_count: 3,
  followup_count_sent: 0,
  created_at: "2026-08-26T12:00:00Z",
  updated_at: "2026-08-26T12:00:00Z",
};

const importedMessage = {
  id: "message-1",
  type: "sms",
  direction: "inbound",
  timestamp: "2026-08-26T12:00:00Z",
  content: "Archived message",
  is_ai: false,
  original_id: "message-1",
  original_type: "sms_message",
  source_provider: "legacy_import",
} as TimelineItem;

describe("imported conversation presentation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses a provider-neutral label and hides communication controls", () => {
    render(
      <ChatHeader
        workspaceId="workspace-1"
        contactId={42}
        contactName="Ada Lovelace"
        phoneNumber="+14155552671"
        conversation={importedConversation}
        agents={[]}
        hasTimelineItems
        isToggleAIPending={false}
        isAssignAgentPending={false}
        isClearHistoryPending={false}
        isMarkReadPending={false}
        onToggleAI={vi.fn()}
        onAssignAgent={vi.fn()}
        onClearHistory={vi.fn()}
        onMarkRead={vi.fn()}
      />,
    );

    expect(screen.getByText("Imported history")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Call contact" })).not.toBeInTheDocument();
    expect(screen.queryByText("AI Off")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Conversation actions" }));
    expect(screen.queryByText("Clear history")).not.toBeInTheDocument();
  });

  it("labels imported messages without naming the retired provider", () => {
    render(
      <MessageItemShell item={importedMessage} isOutbound={false} contactName="Ada Lovelace">
        Archived message
      </MessageItemShell>,
    );

    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(screen.queryByText(/legacy_import/i)).not.toBeInTheDocument();
  });
});
