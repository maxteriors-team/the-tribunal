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
import type { PendingAction } from "@/types/pending-action";

const {
  approvePendingActionMock,
  deleteConversationMock,
  enhancePromptMock,
  getConversationMock,
  getHistoryMock,
  listConversationsMock,
  rejectPendingActionMock,
  streamChatMock,
  useWorkspaceIdMock,
} = vi.hoisted(() => ({
  approvePendingActionMock: vi.fn(),
  deleteConversationMock: vi.fn(),
  enhancePromptMock: vi.fn(),
  getConversationMock: vi.fn(),
  getHistoryMock: vi.fn(),
  listConversationsMock: vi.fn(),
  rejectPendingActionMock: vi.fn(),
  streamChatMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/assistant", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/assistant")>("@/lib/api/assistant");
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

vi.mock("@/lib/api/pending-actions", () => ({
  pendingActionsApi: {
    approve: approvePendingActionMock,
    reject: rejectPendingActionMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({
    currentWorkspace: {
      workspace: { id: "ws_growth", name: "Growth Studio" },
    },
  }),
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
      body: "Hi Ava, quick note — Launch a month of scroll-stopping video ads in one batch. Would you like me to help you claim your Batch Video Ads audit?",
    },
    {
      channel: "sms",
      label: "Mia Rivera",
      body: "Hi Mia, quick note — Launch a month of scroll-stopping video ads in one batch. Would you like me to help you claim your Batch Video Ads audit?",
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

function pendingCampaignAction(id = "action-campaign"): PendingAction {
  return {
    id,
    workspace_id: "ws_growth",
    agent_id: null,
    action_type: "start_campaign",
    action_payload: {
      title: "Summer campaign ready",
      summary: "Review the message before launching it.",
      campaign: { name: "Summer reactivation", status: "draft" },
      initial_message: "Hi! Ready to book your summer service?",
    },
    description: "Start Summer reactivation",
    context: { source: "crm_assistant" },
    status: "pending",
    urgency: "normal",
    reviewed_by_id: null,
    reviewed_at: null,
    review_channel: null,
    rejection_reason: null,
    executed_at: null,
    execution_result: null,
    expires_at: "2026-07-30T12:00:00Z",
    notification_sent: false,
    notification_sent_at: null,
    created_at: "2026-07-29T12:00:00Z",
    updated_at: "2026-07-29T12:00:00Z",
  };
}

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
  approvePendingActionMock.mockReset();
  deleteConversationMock.mockReset();
  enhancePromptMock.mockReset();
  getConversationMock.mockReset();
  getHistoryMock.mockReset();
  listConversationsMock.mockReset();
  rejectPendingActionMock.mockReset();
  streamChatMock.mockReset();
  useWorkspaceIdMock.mockReset();
  approvePendingActionMock.mockImplementation(async (_workspaceId: string, actionId: string) => ({
    ...pendingCampaignAction(actionId),
    status: "approved" as const,
  }));
  deleteConversationMock.mockResolvedValue(undefined);
  enhancePromptMock.mockResolvedValue({
    enhanced_prompt: "Analyze five contacts using dated CRM evidence and label missing data.",
  });
  getConversationMock.mockResolvedValue(growthConversation);
  getHistoryMock.mockResolvedValue(null);
  listConversationsMock.mockResolvedValue([]);
  streamChatMock.mockResolvedValue(undefined);
  rejectPendingActionMock.mockImplementation(async (_workspaceId: string, actionId: string) => ({
    ...pendingCampaignAction(actionId),
    status: "rejected" as const,
  }));
  useWorkspaceIdMock.mockReturnValue("ws_growth");
});

describe("AssistantChat", () => {
  it("prefills a workspace-aware starter prompt without sending it", async () => {
    renderAssistant();
    const prompt = "Give me today's CRM briefing for Growth Studio";

    await userEvent.click(screen.getByRole("button", { name: prompt }));

    expect(screen.getByPlaceholderText("Ask your CRM assistant…")).toHaveValue(prompt);
    expect(streamChatMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", {
        name: "Find contacts at Growth Studio who need follow-up",
      }),
    ).toBeInTheDocument();
  });

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
      expect(enhancePromptMock).toHaveBeenCalledWith("ws_growth", "Who needs follow-up?");
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
    expect(
      screen.getByText(/Start a fresh chat or pick a prior one from the sidebar/),
    ).toBeInTheDocument();

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "New context please",
    );
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
        actions_taken: [{ tool_name: "search_contacts", success: true, summary: "found" }],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "Find dormant leads",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Found 12 dormant leads.")).toBeInTheDocument();
    expect(screen.getByText("search contacts · complete")).toBeInTheDocument();
  });

  it("renders failed tool status with inspectable inputs and results", async () => {
    await emitStream([
      { type: "tool_start", name: "get_contact" },
      { type: "tool_end", name: "get_contact", success: false },
      { type: "delta", text: "I could not load that contact." },
      {
        type: "done",
        conversation_id: "conv_growth",
        message_id: "msg_failed_tool",
        actions_taken: [
          {
            tool_name: "get_contact",
            success: false,
            summary: "Contact missing",
            arguments: { contact_id: 999 },
            result: {
              success: false,
              code: "not_found",
              message: "Contact missing",
            },
          },
        ],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "Load contact 999",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("I could not load that contact.")).toBeInTheDocument();
    expect(screen.getByText("get contact · failed")).toBeInTheDocument();
    expect(screen.getByText("Contact missing")).toBeInTheDocument();

    await userEvent.click(screen.getByText("View inputs and result"));
    expect(screen.getByText("Inputs")).toBeInTheDocument();
    expect(screen.getByText(/"contact_id": 999/)).toBeInTheDocument();
    expect(screen.getByText(/"code": "not_found"/)).toBeInTheDocument();
  });

  it("preserves partial text after a stream failure and retries without duplicating the user turn", async () => {
    streamChatMock
      .mockImplementationOnce(
        async ({ onEvent }: { onEvent: (event: AssistantStreamEvent) => void }) => {
          onEvent({ type: "delta", text: "I found part of the answer." });
          throw new Error("Connection dropped");
        },
      )
      .mockImplementationOnce(
        async ({ onEvent }: { onEvent: (event: AssistantStreamEvent) => void }) => {
          onEvent({ type: "delta", text: "Recovered answer." });
          onEvent({
            type: "done",
            conversation_id: "conv_growth",
            message_id: "msg_retry",
            actions_taken: [],
          });
        },
      );
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(screen.getByPlaceholderText("Ask your CRM assistant…"), "Retry my lookup");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("I found part of the answer.")).toBeInTheDocument();
    expect(await screen.findByText("Connection dropped")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Recovered answer.")).toBeInTheDocument();
    await waitFor(() => {
      expect(streamChatMock).toHaveBeenCalledTimes(2);
    });
    expect(streamChatMock.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        workspaceId: "ws_growth",
        conversationId: "conv_growth",
        message: "Retry my lookup",
      }),
    );
    expect(screen.getAllByText("Retry my lookup")).toHaveLength(1);
    expect(screen.queryByText("Connection dropped")).not.toBeInTheDocument();
  });

  it("renders and approves a pending action inside the chat", async () => {
    const action = pendingCampaignAction();
    await emitStream([
      { type: "pending_approval", action },
      { type: "delta", text: "Waiting for your approval." },
      {
        type: "done",
        conversation_id: "conv_growth",
        message_id: "msg_pending",
        actions_taken: [],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "Start the summer campaign",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Summer campaign ready")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve launch" }));

    await waitFor(() => {
      expect(approvePendingActionMock).toHaveBeenCalledWith("ws_growth", "action-campaign");
    });
    expect(await screen.findByText("Review status: approved")).toBeInTheDocument();
  });

  it("rejects a pending action inside the chat", async () => {
    const action = pendingCampaignAction("action-reject");
    await emitStream([
      { type: "pending_approval", action },
      { type: "delta", text: "Waiting for your approval." },
      {
        type: "done",
        conversation_id: "conv_growth",
        message_id: "msg_reject",
        actions_taken: [],
      },
    ]);
    renderAssistant({ activeConversation: growthConversation });

    await userEvent.type(
      screen.getByPlaceholderText("Ask your CRM assistant…"),
      "Start the summer campaign",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Summer campaign ready")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request changes" }));

    await waitFor(() => {
      expect(rejectPendingActionMock).toHaveBeenCalledWith("ws_growth", "action-reject");
    });
    expect(await screen.findByText("Review status: rejected")).toBeInTheDocument();
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
