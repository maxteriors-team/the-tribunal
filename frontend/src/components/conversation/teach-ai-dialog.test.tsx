import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { conversationsApi } from "@/lib/api/conversations";

import { TeachAIDialog } from "./teach-ai-dialog";

vi.mock("@/lib/api/conversations", () => ({
  conversationsApi: { teachAI: vi.fn() },
}));

function renderDialog(onSaved = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TeachAIDialog
        open={true}
        onOpenChange={vi.fn()}
        workspaceId="workspace-1"
        conversationId="conversation-1"
        sourceMessageId="message-2"
        customerMessage="How much does this cost?"
        aiResponse="Book now."
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onSaved };
}

describe("TeachAIDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("labels every editable field and discloses that saving does not send", () => {
    renderDialog();

    expect(screen.getByText("How much does this cost?")).toBeInTheDocument();
    expect(screen.getByText("Book now.")).toBeInTheDocument();
    expect(screen.getByLabelText("What should the AI have said?")).toBeInTheDocument();
    expect(screen.getByLabelText("What should it learn? (optional)")).toBeInTheDocument();
    expect(screen.getByText(/does not send anything to this customer/i)).toBeInTheDocument();
    expect(screen.getByText(/does not retrain the base model/i)).toBeInTheDocument();
  });

  it("saves the lesson through Teach AI without a customer-send API", async () => {
    vi.mocked(conversationsApi.teachAI).mockResolvedValue({
      id: "lesson-1",
      workspace_id: "workspace-1",
      agent_id: "agent-1",
      conversation_id: "conversation-1",
      source_message_id: "message-2",
      ideal_response: "Happy to help. What service do you need?",
      note: "Ask one question first.",
      is_active: true,
      agent_name: "Lead agent",
      created_at: "2026-08-12T12:00:00Z",
      updated_at: "2026-08-12T12:00:00Z",
    });
    const { onSaved } = renderDialog();

    fireEvent.change(screen.getByLabelText("What should the AI have said?"), {
      target: { value: "Happy to help. What service do you need?" },
    });
    fireEvent.change(screen.getByLabelText("What should it learn? (optional)"), {
      target: { value: "Ask one question first." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save lesson" }));

    await waitFor(() => {
      expect(conversationsApi.teachAI).toHaveBeenCalledWith("workspace-1", "conversation-1", {
        source_message_id: "message-2",
        ideal_response: "Happy to help. What service do you need?",
        note: "Ask one question first.",
      });
    });
    expect(onSaved).toHaveBeenCalledWith("Lead agent");
  });
});
