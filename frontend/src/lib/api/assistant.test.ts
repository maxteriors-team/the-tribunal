import type { AxiosResponse } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { assistantApi, type AssistantStreamEvent } from "@/lib/api/assistant";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("assistantApi.streamChat", () => {
  it("streams through the interceptor-backed Axios fetch adapter", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"delta","text":"Hel'));
        controller.enqueue(
          encoder.encode(
            'lo"}\n\ndata: {"type":"done","conversation_id":"conv-1","actions_taken":[]}\n\n',
          ),
        );
        controller.close();
      },
    });
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({ data: body } as AxiosResponse<ReadableStream<Uint8Array>>);
    const onEvent = vi.fn<(event: AssistantStreamEvent) => void>();
    const controller = new AbortController();

    await assistantApi.streamChat({
      workspaceId: "workspace-1",
      conversationId: "conversation-1",
      message: "Hello",
      signal: controller.signal,
      onEvent,
    });

    expect(postSpy).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace-1/assistant/chat/stream",
      {
        message: "Hello",
        conversation_id: "conversation-1",
        image: null,
      },
      {
        adapter: "fetch",
        responseType: "stream",
        signal: controller.signal,
        timeout: 0,
      },
    );
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { type: "delta", text: "Hello" },
      { type: "done", conversation_id: "conv-1", actions_taken: [] },
    ]);
  });
});
