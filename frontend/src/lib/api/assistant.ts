/** CRM Assistant API client. */

import api from "@/lib/api";

export type AssistantRole = "user" | "assistant" | "tool";

export interface AssistantActionSummary {
  tool_name: string;
  success: boolean;
  summary: string;
}

export interface AssistantChatResponse {
  response: string;
  actions_taken: AssistantActionSummary[];
  conversation_id?: string | null;
}

export interface AssistantMessageResponse {
  id: string;
  role: AssistantRole;
  content: string;
  /** Local-only: data URL of an image attached to a user turn (not persisted). */
  image?: string | null;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[] | null;
  tool_call_id?: string | null;
  created_at: string;
}

export interface AssistantConversationResponse {
  id: string;
  messages: AssistantMessageResponse[];
  created_at: string;
  updated_at: string;
}

export interface AssistantConversationMetaResponse {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export type AssistantStreamEvent =
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_end"; name: string; success?: boolean | null }
  | { type: "retry"; reason: string; attempt: number }
  | { type: "error"; message: string }
  | {
      type: "done";
      conversation_id: string;
      message_id?: string | null;
      actions_taken: AssistantActionSummary[];
    };

interface StreamChatParams {
  workspaceId: string;
  conversationId?: string | null;
  message: string;
  image?: string | null;
  signal?: AbortSignal;
  onEvent: (event: AssistantStreamEvent) => void;
}

const basePath = (workspaceId: string) =>
  `/api/v1/workspaces/${workspaceId}/assistant`;

function parseSseFrames(buffer: string): { frames: string[]; remainder: string } {
  const frames: string[] = [];
  let remainder = buffer;
  let separatorIndex = remainder.indexOf("\n\n");

  while (separatorIndex !== -1) {
    frames.push(remainder.slice(0, separatorIndex));
    remainder = remainder.slice(separatorIndex + 2);
    separatorIndex = remainder.indexOf("\n\n");
  }

  return { frames, remainder };
}

function parseSseData(frame: string): AssistantStreamEvent | null {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");

  if (!data || data === "[DONE]") return null;
  return JSON.parse(data) as AssistantStreamEvent;
}

export const assistantApi = {
  chat: async (
    workspaceId: string,
    message: string,
    conversationId?: string | null,
    image?: string | null,
  ): Promise<AssistantChatResponse> => {
    const { data } = await api.post<AssistantChatResponse>(
      `${basePath(workspaceId)}/chat`,
      { message, conversation_id: conversationId ?? null, image: image ?? null },
    );
    return data;
  },

  getHistory: async (
    workspaceId: string,
  ): Promise<AssistantConversationResponse | null> => {
    const { data } = await api.get<AssistantConversationResponse | null>(
      `${basePath(workspaceId)}/history`,
    );
    return data;
  },

  listConversations: async (
    workspaceId: string,
  ): Promise<AssistantConversationMetaResponse[]> => {
    const { data } = await api.get<AssistantConversationMetaResponse[]>(
      `${basePath(workspaceId)}/conversations`,
    );
    return data;
  },

  getConversation: async (
    workspaceId: string,
    conversationId: string,
  ): Promise<AssistantConversationResponse> => {
    const { data } = await api.get<AssistantConversationResponse>(
      `${basePath(workspaceId)}/conversations/${conversationId}`,
    );
    return data;
  },

  deleteConversation: async (
    workspaceId: string,
    conversationId: string,
  ): Promise<void> => {
    await api.delete(`${basePath(workspaceId)}/conversations/${conversationId}`);
  },

  streamChat: async ({
    workspaceId,
    conversationId,
    message,
    image,
    signal,
    onEvent,
  }: StreamChatParams): Promise<void> => {
    const response = await fetch(`${basePath(workspaceId)}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      signal,
      body: JSON.stringify({
        message,
        conversation_id: conversationId ?? null,
        image: image ?? null,
      }),
    });

    if (!response.ok) {
      throw new Error(`Assistant stream failed with status ${response.status}`);
    }
    if (!response.body) {
      throw new Error("Assistant stream response did not include a body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseFrames(buffer);
      buffer = parsed.remainder;

      for (const frame of parsed.frames) {
        const event = parseSseData(frame);
        if (event) onEvent(event);
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = parseSseData(buffer);
      if (event) onEvent(event);
    }
  },
};
