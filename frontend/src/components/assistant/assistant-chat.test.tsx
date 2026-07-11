import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantChat } from "@/components/assistant/assistant-chat";
import type {
  AssistantConversationMetaResponse,
  AssistantConversationResponse,
  AssistantStreamEvent,
} from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query-keys";

const {
  deleteConversationMock,
  enhancePromptMock,
  getConversationMock,
  getHistoryMock,
  listConversationsMock,
  streamChatMock,
  useWorkspaceIdMock,
} = vi.hoisted(() => ({
  deleteConversationMock: vi.fn(),
  enhancePromptMock: vi.fn(),
  getConversationMock: vi.fn(),
  getHistoryMock: vi.fn(),
  listConversationsMock: vi.fn(),
  streamChatMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/assistant", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/assistant")>(
    "@/lib/api/assistant",
  );
  return {
    ...actual,
    assistantApi: {
      ...actual.assistantApi,
      deleteConversation: deleteConversationMock,
      enhancePrompt: enhancePromptMock,
      getConversation: getConversationMock,
      getHistory: getHistoryMock,
      listConversations: listConversationsMock,
      streamChat: streamChatMock,
    },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function conversationMeta(
  conversation: AssistantConversationResponse,
): AssistantConversationMetaResponse {
  const firstUser = conversation.messages.find((message) => message.role === "user");
  return {
    id: conversation.id,
    title: firstUser?.content ?? "New chat",
    message_count: conversation.messages.length,
    created_at: conversation.created_at,
    updated_at: conversation.updated_at,
  };
}

function renderAssistant({
  conversations,
  activeConversation,
}: {
  conversations?: AssistantConversationMetaResponse[];
  activeConversation?: AssistantConversationResponse;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(
    queryKeys.assistant.conversations("ws_growth"),
    conversations ?? (activeConversation ? [conversationMeta(activeConversation)] : []),
  );
  if (activeConversation) {
    queryClient.setQueryData(
      queryKeys.assistant.conversation("ws_growth", activeConversation.id),
      activeConversation,
    );
  }

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AssistantChat />
    </QueryClientProvider>,
  );

  return { ...utils, queryClient };
}

async function emitStream(events: AssistantStreamEvent[]) {
  streamChatMock.mockImplementationOnce(
    async ({ onEvent }: { onEvent: (event: AssistantStreamEvent) => void }) => {
      events.forEach(onEvent);
    },
  );
}

const workflowPayload = {
  type: "outbound_workflow",
  title: "Outbound growth workflow ready",
  summary:
    "Drafted Batch Video Ads outreach, previewed contacts, launched after approval, and queued warm-lead handoff.",
  offer: {
    name: "Batch Video Ads",
    headline: "Launch a month of scroll-stopping video ads in one batch",
  },
  segment: {
    name: "Dormant ecommerce leads",
    description: "Leads who asked about creative strategy but never booked",
    contact_count: 2,
  },
  campaign: {
    name: "Batch Video Ads → Dormant ecommerce leads",
    status: "running",
  },
  message_previews: [
    {
      channel: "sms",
      label: "Ava Rivera",
      body:
        "Hi Ava, quick note — Launch a month of scroll-stopping video ads in one batch. Would you like me to help you claim your Batch Video Ads audit?",
    },
    {
      channel: "sms",
      label: "Mia Rivera",
      body:
        "Hi Mia, quick note — Launch a month of scroll-stopping video ads in one batch. Would you like me to help you claim your Batch Video Ads audit?",
    },
  ],
  approval_label: "User approved start_campaign",
  approval_status: "approved",
  launch_status: "running",
  responder_agent: {
    name: "Batch Video Ads Responder",
    role: "Assigned to campaign conversations",
  },
  warm_lead_handoff: {
    title: "Warm-lead handoff created",
    description:
      "Ava replied with interest, was classified warm, and an opportunity was created for human follow-up.",
  },
  metrics: [
    { label: "Initial messages sent", value: "2", tone: "success" },
    { label: "Warm replies", value: "1", tone: "success" },
    { label: "Opportunities", value: "1", tone: "success" },
  ],
};

const growthConversation: AssistantConversationResponse = {
  id: "conv_growth",
  created_at: "2026-05-20T14:00:00Z",
  updated_at: "2026-05-20T14:00:05Z",
  messages: [
    {
      id: "msg_user",
      role: "user",
      content: "Reach out to dormant ecommerce leads about Batch Video Ads.",
      created_at: "2026-05-20T14:00:00Z",
    },
    {
      id: "msg_assistant",
      role: "assistant",
      content: JSON.stringify(workflowPayload),
      created_at: "2026-05-20T14:00:05Z",
    },
  ],
};

beforeEach(() => {
  deleteConversationMock.mockReset();
  enhancePromptMock.mockReset();
  getConversationMock.mockReset();
  getHistoryMock.mockReset();
  listConversationsMock.mockReset();
  streamChatMock.mockReset();
  useWorkspaceIdMock.mockReset();
  deleteConversationMock.mockResolvedValue(undefined);
  enhancePromptMock.mockResolvedValue({
    enhanced_prompt:
      "Analyze five contacts using dated CRM evidence and label missing data.",
  });
  getConversationMock.mockResolvedValue(growthConversation);
  getHistoryMock.mockResolvedValue(null);
  listConversationsMock.mockResolvedValue([]);
  streamChatMock.mockResolvedValue(undefined);
  useWorkspaceIdMock.mockReturnValue("ws_growth");
});

describe("AssistantChat", () => {
  it("previews the Batch Video Ads happy path and streams the user's outreach request", async () => {
    await emitStream([
      { type: "delta", text: "Queued" },
      {
        type: "done",
        conversation_id: "conv_growth",
        message_id: "msg_done",
        actions_taken: [],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    expect(screen.getByText("Outbound growth workflow ready")).toBeInTheDocument();
    expect(screen.getByText("Batch Video Ads")).toBeInTheDocument();
    expect(screen.getByText("Dormant ecommerce leads")).toBeInTheDocument();
    expect(screen.getByText("2 contacts matched")).toBeInTheDocument();
    expect(screen.getByText("Ava Rivera")).toBeInTheDocument();
    expect(screen.getByText(/Hi Ava, quick note/)).toBeInTheDocument();
    expect(screen.getByText("User approved start_campaign")).toBeInTheDocument();
    expect(screen.getByText("Batch Video Ads → Dormant ecommerce leads")).toBeInTheDocument();
    expect(screen.getByText("Batch Video Ads Responder")).toBeInTheDocument();
    expect(screen.getByText("Warm-lead handoff created")).toBeInTheDocument();
    expect(screen.getByText(/opportunity was created for human follow-up/i)).toBeInTheDocument();
    expect(screen.getByText("Initial messages sent")).toBeInTheDocument();
    expect(screen.getByText("Warm replies")).toBeInTheDocument();
    expect(screen.getByText("Opportunities")).toBeInTheDocument();

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "Please reach out to more Batch Video Ads leads",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(streamChatMock).toHaveBeenCalledWith(
        expect.objectContaining({
          workspaceId: "ws_growth",
          conversationId: "conv_growth",
          message: "Please reach out to more Batch Video Ads leads",
        }),
      );
    });
    expect(await screen.findByText("Queued")).toBeInTheDocument();
  });

  it("enhances a draft for review without sending it", async () => {
    renderAssistant({ activeConversation: growthConversation });
    const composer = screen.getByPlaceholderText("Ask your CRM assistant…");

    await userEvent.type(composer, "Who needs follow-up?");
    await userEvent.click(screen.getByRole("button", { name: "Enhance" }));

    await waitFor(() => {
      expect(enhancePromptMock).toHaveBeenCalledWith(
        "ws_growth",
        "Who needs follow-up?",
      );
    });
    expect(composer).toHaveValue(
      "Analyze five contacts using dated CRM evidence and label missing data.",
    );
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  it("starts a fresh chat with a new conversation id", async () => {
    await emitStream([
      { type: "delta", text: "Fresh context ready" },
      {
        type: "done",
        conversation_id: "new-conversation",
        message_id: "msg_new",
        actions_taken: [],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByText(/Start a fresh chat or pick a prior one from the sidebar/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Ask your CRM assistant…"), "New context please");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      const call = streamChatMock.mock.calls[0]?.[0];
      expect(call).toEqual(expect.objectContaining({ message: "New context please" }));
      expect(call.conversationId).not.toBe("conv_growth");
    });
  });

  it("appends live assistant text and completed tool chips", async () => {
    await emitStream([
      { type: "tool_start", name: "search_contacts" },
      { type: "tool_end", name: "search_contacts", success: true },
      { type: "delta", text: "Found 12 dormant leads." },
      {
        type: "done",
        conversation_id: "conv_growth",
        message_id: "msg_streamed",
        actions_taken: [
          { tool_name: "search_contacts", success: true, summary: "found" },
        ],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(screen.getByPlaceholderText("Ask your CRM assistant…"), "Find dormant leads");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Found 12 dormant leads.")).toBeInTheDocument();
    expect(screen.getByText("search contacts")).toBeInTheDocument();
  });

  it("aborts streaming when Stop is clicked", async () => {
    let observedAbort = false;
    streamChatMock.mockImplementationOnce(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise<void>((resolve) => {
          signal.addEventListener("abort", () => {
            observedAbort = true;
            resolve();
          });
        }),
    );
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(screen.getByPlaceholderText("Ask your CRM assistant…"), "Keep working");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("button", { name: "Stop streaming" });
    await userEvent.click(screen.getByRole("button", { name: "Stop streaming" }));

    await waitFor(() => {
      expect(observedAbort).toBe(true);
      expect(screen.queryByRole("button", { name: "Stop streaming" })).not.toBeInTheDocument();
    });
  });
});
