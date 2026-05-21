import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantChat } from "@/components/assistant/assistant-chat";
import type { AssistantConversationResponse } from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query-keys";

const { chatMock, getHistoryMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  chatMock: vi.fn(),
  getHistoryMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/assistant", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/assistant")>("@/lib/api/assistant");
  return {
    ...actual,
    assistantApi: {
      ...actual.assistantApi,
      chat: chatMock,
      getHistory: getHistoryMock,
    },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function renderAssistant(history: AssistantConversationResponse) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(queryKeys.assistant.history("ws_growth"), history);

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AssistantChat />
    </QueryClientProvider>,
  );

  return { ...utils, queryClient };
}

const workflowPayload = {
  type: "outbound_workflow",
  title: "Outbound growth workflow ready",
  summary: "Drafted Batch Video Ads outreach, previewed contacts, launched after approval, and queued warm-lead handoff.",
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
    description: "Ava replied with interest, was classified warm, and an opportunity was created for human follow-up.",
  },
  metrics: [
    { label: "Initial messages sent", value: "2", tone: "success" },
    { label: "Warm replies", value: "1", tone: "success" },
    { label: "Opportunities", value: "1", tone: "success" },
  ],
};

beforeEach(() => {
  chatMock.mockReset();
  getHistoryMock.mockReset();
  useWorkspaceIdMock.mockReset();
  getHistoryMock.mockResolvedValue(null);
  useWorkspaceIdMock.mockReturnValue("ws_growth");
});

describe("AssistantChat outbound growth workflow", () => {
  it("previews the Batch Video Ads happy path and sends the user's outreach request", async () => {
    chatMock.mockResolvedValue({ response: "queued", actions_taken: [] });
    renderAssistant({
      id: "conv_growth",
      created_at: "2026-05-20T14:00:00Z",
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
    });

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
      expect(chatMock).toHaveBeenCalledWith("ws_growth", "Please reach out to more Batch Video Ads leads");
    });
  });
});
