import { describe, expect, it } from "vitest";

import type { AssistantMessageResponse, AssistantStreamEvent } from "@/lib/api/assistant";

import {
  applyStreamResult,
  emptyAccumulator,
  emptyRuntime,
  mergeRuntimePatch,
  parseWorkflowPayload,
  reduceStreamEvent,
  resolveActiveConversationId,
  resolveActiveRuntime,
  selectVisibleMessages,
  startUserTurn,
  toolNamesFromMessage,
  type ConversationRuntime,
  type StreamAccumulator,
} from "./conversation-runtime";

const FIXED_NOW = () => new Date("2026-05-20T14:00:00.000Z");

/** Fold a list of events through the reducer, returning the final accumulator + merged runtime. */
function runEvents(events: AssistantStreamEvent[]): {
  accumulator: StreamAccumulator;
  runtime: ConversationRuntime;
  appended: ConversationRuntime["messages"];
} {
  let accumulator = emptyAccumulator();
  let runtime = emptyRuntime();
  const appended: ConversationRuntime["messages"] = [];

  for (const event of events) {
    const result = reduceStreamEvent(accumulator, event, FIXED_NOW);
    accumulator = result.accumulator;
    runtime = { ...runtime, ...result.patch };
    if (result.appendMessage) {
      appended.push(result.appendMessage);
      runtime = { ...runtime, messages: [...runtime.messages, result.appendMessage] };
    }
  }

  return { accumulator, runtime, appended };
}

describe("reduceStreamEvent", () => {
  it("appends delta text without mutating the input accumulator", () => {
    const accumulator = emptyAccumulator();
    const result = reduceStreamEvent(accumulator, { type: "delta", text: "Hello" }, FIXED_NOW);

    expect(result.accumulator.text).toBe("Hello");
    expect(result.patch).toEqual({ streamingText: "Hello" });
    expect(result.finished).toBe(false);
    // input accumulator is untouched (purity)
    expect(accumulator.text).toBe("");
  });

  it("moves a tool from active to completed across tool_start/tool_end", () => {
    const startResult = reduceStreamEvent(
      emptyAccumulator(),
      { type: "tool_start", name: "search_contacts" },
      FIXED_NOW,
    );
    expect(startResult.accumulator.activeTools).toEqual([
      { name: "search_contacts", status: "running" },
    ]);

    const endResult = reduceStreamEvent(
      startResult.accumulator,
      { type: "tool_end", name: "search_contacts", success: true },
      FIXED_NOW,
    );
    expect(endResult.accumulator.activeTools).toEqual([]);
    expect(endResult.accumulator.completedTools).toEqual([
      { name: "search_contacts", status: "complete", success: true },
    ]);
  });

  it("deduplicates a repeated tool_start for the same tool name", () => {
    const first = reduceStreamEvent(
      emptyAccumulator(),
      { type: "tool_start", name: "draft_sms" },
      FIXED_NOW,
    );
    const second = reduceStreamEvent(
      first.accumulator,
      { type: "tool_start", name: "draft_sms" },
      FIXED_NOW,
    );

    expect(second.accumulator.activeTools).toEqual([{ name: "draft_sms", status: "running" }]);
  });

  it("stores a complete pending approval action for inline review", () => {
    const action = {
      id: "action-1",
      workspace_id: "workspace-1",
      agent_id: null,
      action_type: "start_campaign",
      action_payload: { campaign_id: "campaign-1" },
      description: "Start the summer campaign",
      context: { source: "crm_assistant" },
      status: "pending" as const,
      urgency: "normal",
      reviewed_by_id: null,
      reviewed_at: null,
      review_channel: null,
      rejection_reason: null,
      executed_at: null,
      execution_result: null,
      expires_at: null,
      notification_sent: false,
      notification_sent_at: null,
      created_at: "2026-07-29T12:00:00Z",
      updated_at: "2026-07-29T12:00:00Z",
    };

    const first = reduceStreamEvent(
      emptyAccumulator(),
      { type: "pending_approval", action },
      FIXED_NOW,
    );
    const replacement = { ...action, description: "Updated review details" };
    const second = reduceStreamEvent(
      first.accumulator,
      { type: "pending_approval", action: replacement },
      FIXED_NOW,
    );

    expect(second.patch.pendingApprovals).toEqual([replacement]);
    expect(second.accumulator.pendingApprovals).toEqual([replacement]);
  });

  it("stops streaming and surfaces the message on error", () => {
    const result = reduceStreamEvent(
      emptyAccumulator(),
      { type: "error", message: "stream failed" },
      FIXED_NOW,
    );

    expect(result.patch).toMatchObject({
      isStreaming: false,
      error: "stream failed",
      requestId: null,
    });
    expect(result.finished).toBe(true);
  });

  it("preserves partial assistant text when the stream errors", () => {
    const { runtime, appended } = runEvents([
      { type: "delta", text: "I found three" },
      { type: "error", message: "connection lost" },
    ]);

    expect(runtime).toMatchObject({
      streamingText: "I found three",
      isStreaming: false,
      error: "connection lost",
    });
    expect(appended).toHaveLength(0);
  });

  it("builds an assistant message with deterministic id and tool calls on done", () => {
    const { runtime, appended } = runEvents([
      { type: "tool_start", name: "search_contacts" },
      { type: "tool_end", name: "search_contacts", success: true },
      { type: "delta", text: "Done." },
      {
        type: "done",
        conversation_id: "conv_1",
        message_id: null,
        actions_taken: [
          {
            tool_name: "search_contacts",
            success: true,
            summary: "12 contacts found",
            arguments: { query: "dormant" },
            result: { success: true, total: 12 },
          },
        ],
      },
    ]);

    expect(appended).toHaveLength(1);
    const message = appended[0]!;
    expect(message.id).toBe(`assistant-conv_1-${FIXED_NOW().getTime()}`);
    expect(message.content).toBe("Done.");
    expect(message.tool_calls).toEqual([
      { id: "tool-0", function: { name: "search_contacts", arguments: "{}" } },
    ]);
    expect(message.actions_taken).toEqual([
      {
        tool_name: "search_contacts",
        success: true,
        summary: "12 contacts found",
        arguments: { query: "dormant" },
        result: { success: true, total: 12 },
      },
    ]);
    expect(runtime.isStreaming).toBe(false);
    expect(runtime.streamingText).toBe("");
  });

  it("prefers an explicit message_id when provided on done", () => {
    const { appended } = runEvents([
      { type: "delta", text: "Hi" },
      {
        type: "done",
        conversation_id: "conv_2",
        message_id: "msg_explicit",
        actions_taken: [],
      },
    ]);

    expect(appended[0]!.id).toBe("msg_explicit");
  });

  it("does not append a message on done when no text was streamed", () => {
    const { appended, runtime } = runEvents([
      {
        type: "done",
        conversation_id: "conv_3",
        message_id: "msg_empty",
        actions_taken: [],
      },
    ]);

    expect(appended).toHaveLength(0);
    expect(runtime.messages).toHaveLength(0);
  });
});

describe("toolNamesFromMessage", () => {
  it("extracts tool names and ignores entries without a function name", () => {
    const names = toolNamesFromMessage({
      id: "m1",
      role: "assistant",
      content: "",
      created_at: "2026-05-20T14:00:00Z",
      tool_calls: [
        { id: "t1", function: { name: "search_contacts", arguments: "{}" } },
        { id: "t2", function: { name: "", arguments: "{}" } },
      ],
    });

    expect(names).toEqual(["search_contacts"]);
  });

  it("returns an empty array when there are no tool calls", () => {
    const names = toolNamesFromMessage({
      id: "m2",
      role: "assistant",
      content: "no tools",
      created_at: "2026-05-20T14:00:00Z",
    });

    expect(names).toEqual([]);
  });
});

describe("resolveActiveConversationId", () => {
  it("prefers the explicit selection when present", () => {
    expect(resolveActiveConversationId("conv_sel", [{ id: "conv_first" }], "draft_1")).toBe(
      "conv_sel",
    );
  });

  it("falls back to the first conversation, then the draft", () => {
    expect(resolveActiveConversationId(null, [{ id: "conv_first" }], "draft_1")).toBe("conv_first");
    expect(resolveActiveConversationId(null, [], "draft_1")).toBe("draft_1");
  });
});

describe("resolveActiveRuntime", () => {
  const userMessage: AssistantMessageResponse = {
    id: "m_user",
    role: "user",
    content: "hi",
    created_at: "2026-05-20T14:00:00Z",
  };

  it("returns the stored runtime when it is streaming", () => {
    const storedRuntime = { ...emptyRuntime(), isStreaming: true };
    expect(
      resolveActiveRuntime({ storedRuntime, isDraftActive: false, hydratedMessages: [] }),
    ).toBe(storedRuntime);
  });

  it("returns the stored runtime when it already has messages", () => {
    const storedRuntime = { ...emptyRuntime(), messages: [userMessage] };
    expect(
      resolveActiveRuntime({
        storedRuntime,
        isDraftActive: false,
        hydratedMessages: [],
      }),
    ).toBe(storedRuntime);
  });

  it("returns an empty runtime for an active draft with no stored runtime", () => {
    expect(
      resolveActiveRuntime({
        storedRuntime: undefined,
        isDraftActive: true,
        hydratedMessages: [userMessage],
      }),
    ).toEqual(emptyRuntime());
  });

  it("hydrates from persisted messages when nothing is stored", () => {
    const runtime = resolveActiveRuntime({
      storedRuntime: undefined,
      isDraftActive: false,
      hydratedMessages: [userMessage],
    });
    expect(runtime.messages).toEqual([userMessage]);
    expect(runtime.isStreaming).toBe(false);
  });

  it("falls back to an empty runtime when there is nothing to hydrate", () => {
    expect(
      resolveActiveRuntime({
        storedRuntime: undefined,
        isDraftActive: false,
        hydratedMessages: null,
      }),
    ).toEqual(emptyRuntime());
  });
});

describe("selectVisibleMessages", () => {
  it("hides tool-role messages and preserves order", () => {
    const messages: AssistantMessageResponse[] = [
      { id: "a", role: "user", content: "q", created_at: "2026-05-20T14:00:00Z" },
      { id: "b", role: "tool", content: "{}", created_at: "2026-05-20T14:00:01Z" },
      { id: "c", role: "assistant", content: "a", created_at: "2026-05-20T14:00:02Z" },
    ];
    expect(selectVisibleMessages(messages).map((message) => message.id)).toEqual(["a", "c"]);
  });

  it("pairs persisted tool calls with their arguments and results", () => {
    const messages: AssistantMessageResponse[] = [
      {
        id: "assistant-tool-call",
        role: "assistant",
        content: "I checked that contact.",
        created_at: "2026-05-20T14:00:00Z",
        tool_calls: [
          {
            id: "call-1",
            function: {
              name: "get_contact",
              arguments: JSON.stringify({ contact_id: 42 }),
            },
          },
        ],
      },
      {
        id: "tool-result",
        role: "tool",
        content: JSON.stringify({ success: false, code: "not_found", message: "Missing" }),
        created_at: "2026-05-20T14:00:01Z",
        tool_call_id: "call-1",
      },
    ];

    const visible = selectVisibleMessages(messages);

    expect(visible).toHaveLength(1);
    expect(visible[0]?.actions_taken).toEqual([
      {
        tool_name: "get_contact",
        success: false,
        summary: expect.stringContaining("not_found"),
        arguments: { contact_id: 42 },
        result: { success: false, code: "not_found", message: "Missing" },
      },
    ]);
  });
});

describe("mergeRuntimePatch", () => {
  it("merges a patch onto an empty runtime when none exists", () => {
    expect(mergeRuntimePatch(undefined, { isStreaming: true })).toEqual({
      ...emptyRuntime(),
      isStreaming: true,
    });
  });

  it("overrides only the patched fields", () => {
    const runtime = { ...emptyRuntime(), streamingText: "keep", error: "old" };
    expect(mergeRuntimePatch(runtime, { error: null })).toEqual({
      ...runtime,
      error: null,
    });
  });
});

describe("startUserTurn", () => {
  it("appends the user message and resets streaming fields", () => {
    const runtime: ConversationRuntime = {
      ...emptyRuntime(),
      messages: [
        { id: "prev", role: "assistant", content: "earlier", created_at: "2026-05-20T13:59:00Z" },
      ],
      streamingText: "stale",
      activeTools: [{ name: "x", status: "running" }],
      error: "boom",
    };
    const userMessage: AssistantMessageResponse = {
      id: "u1",
      role: "user",
      content: "new question",
      created_at: "2026-05-20T14:00:00Z",
    };

    const next = startUserTurn(runtime, userMessage, "req_1");
    expect(next.messages).toHaveLength(2);
    expect(next.messages[1]).toBe(userMessage);
    expect(next.streamingText).toBe("");
    expect(next.activeTools).toEqual([]);
    expect(next.error).toBeNull();
    expect(next.isStreaming).toBe(true);
    expect(next.requestId).toBe("req_1");
  });

  it("restarts a failed turn without duplicating the user message", () => {
    const userMessage: AssistantMessageResponse = {
      id: "u1",
      role: "user",
      content: "Try this again",
      image: "data:image/png;base64,reuse-me",
      created_at: "2026-05-20T14:00:00Z",
    };
    const runtime: ConversationRuntime = {
      ...emptyRuntime(),
      messages: [userMessage],
      streamingText: "Partial answer",
      error: "connection lost",
      retryRequest: { message: userMessage.content, image: userMessage.image ?? null },
    };

    const next = startUserTurn(runtime, userMessage, "req_retry", false);

    expect(next.messages).toEqual([userMessage]);
    expect(next.streamingText).toBe("");
    expect(next.error).toBeNull();
    expect(next.isStreaming).toBe(true);
    expect(next.requestId).toBe("req_retry");
    expect(next.retryRequest).toEqual({
      message: "Try this again",
      image: "data:image/png;base64,reuse-me",
    });
  });
});

describe("applyStreamResult", () => {
  it("merges the patch and appends a completed message", () => {
    const runtime: ConversationRuntime = {
      ...emptyRuntime(),
      messages: [{ id: "u1", role: "user", content: "q", created_at: "2026-05-20T14:00:00Z" }],
      isStreaming: true,
    };
    const appendMessage: AssistantMessageResponse = {
      id: "a1",
      role: "assistant",
      content: "done",
      created_at: "2026-05-20T14:00:05Z",
    };

    const next = applyStreamResult(runtime, {
      accumulator: emptyAccumulator(),
      patch: { isStreaming: false },
      appendMessage,
      finished: true,
    });
    expect(next.isStreaming).toBe(false);
    expect(next.messages).toHaveLength(2);
    expect(next.messages[1]).toBe(appendMessage);
  });

  it("keeps existing messages when there is nothing to append", () => {
    const runtime: ConversationRuntime = {
      ...emptyRuntime(),
      messages: [{ id: "u1", role: "user", content: "q", created_at: "2026-05-20T14:00:00Z" }],
    };

    const next = applyStreamResult(runtime, {
      accumulator: emptyAccumulator(),
      patch: { streamingText: "partial" },
      appendMessage: null,
      finished: false,
    });
    expect(next.messages).toBe(runtime.messages);
    expect(next.streamingText).toBe("partial");
  });
});

describe("parseWorkflowPayload", () => {
  it("returns the record for a tagged outbound workflow payload", () => {
    const payload = parseWorkflowPayload(
      JSON.stringify({ type: "outbound_workflow", title: "Ready" }),
    );
    expect(payload).toMatchObject({ type: "outbound_workflow", title: "Ready" });
  });

  it("recognizes alternate workflow markers", () => {
    expect(parseWorkflowPayload(JSON.stringify({ message_previews: [] }))).not.toBeNull();
    expect(parseWorkflowPayload(JSON.stringify({ launch_status: "running" }))).not.toBeNull();
    expect(parseWorkflowPayload(JSON.stringify({ warm_lead_handoff: {} }))).not.toBeNull();
  });

  it("returns null for plain text, arrays, and untagged objects", () => {
    expect(parseWorkflowPayload("just a normal reply")).toBeNull();
    expect(parseWorkflowPayload(JSON.stringify([1, 2, 3]))).toBeNull();
    expect(parseWorkflowPayload(JSON.stringify({ greeting: "hi" }))).toBeNull();
  });

  it("returns null for malformed JSON that starts with a brace", () => {
    expect(parseWorkflowPayload("{ not valid json")).toBeNull();
  });
});
