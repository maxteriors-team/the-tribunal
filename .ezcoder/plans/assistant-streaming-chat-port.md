# Port Media Master agent streaming + fresh chats into Tribunal CRM Assistant

## Goal

Bring the useful user-facing pieces from `/Users/groot/media-master` into The Tribunal assistant:

- Visual streaming assistant replies with live text deltas, active/completed tool badges, retry/error notices, and a stop button.
- A chat sidebar/list so operators can start a new chat with cleared context and switch back to prior chats.
- Backend conversation identity support so each chat thread is isolated instead of reusing the single `(workspace_id, user_id)` assistant conversation.

This should be adapted to Tribunal’s FastAPI + Next.js architecture, not copied as Electron IPC.

## Source findings

### Tribunal current state

- UI entry: `frontend/src/app/assistant/page.tsx:1-19` renders `AssistantChat` under `AppSidebar` with a header.
- Existing chat UI: `frontend/src/components/assistant/assistant-chat.tsx:18-184` is a single-thread React Query chat. It:
  - reads `useAssistantHistory()` (`frontend/src/hooks/useAssistant.ts:9-21`),
  - posts via `useAssistantChat()` (`frontend/src/hooks/useAssistant.ts:23-100`),
  - appends optimistic `…`, then invalidates history,
  - hides `role === "tool"` messages,
  - renders outbound workflow JSON via `OutboundWorkflowCard`.
- API client: `frontend/src/lib/api/assistant.ts:25-48` only has:
  - `POST /api/v1/workspaces/{workspaceId}/assistant/chat`
  - `GET /api/v1/workspaces/{workspaceId}/assistant/history`
- Query key factory: `frontend/src/lib/query-keys.ts:61-63` only has `assistant.history(workspaceId)`.
- Backend route: `backend/app/api/v1/crm_assistant.py:24-84` has only `chat_with_assistant` and `get_assistant_history`.
- Backend model: `backend/app/models/assistant_conversation.py:14-84` has:
  - `AssistantConversation.id`, `workspace_id`, `user_id`, `created_at`, `updated_at`, `messages`
  - `AssistantMessage.id`, `conversation_id`, `role`, `content`, `tool_calls`, `tool_call_id`, `created_at`
  - no title/message-count helpers, no per-request conversation id routing.
- Backend processor: `backend/app/services/ai/crm_assistant/_processor.py:158-348` always gets or creates exactly one conversation via `(workspace_id, user_id)` (`lines 180-191`), appends user message (`lines 193-195`), calls non-streaming `client.chat.completions.create` (`lines 225-239`), persists assistant/tool messages, commits, and returns final text/actions.
- Processor already has strong tool-loop primitives worth preserving: `_serialize_history`, `_repair_pairing`, `maybe_summarize`, `_execute_tool_calls_sequential`, `CRMToolExecutor`, `get_crm_tools`.
- OpenAPI generated file contains old assistant endpoints (`frontend/src/lib/api/_generated.ts`), so changing API shape should be followed by openapi codegen if this repo keeps generated spec in sync.

### Media Master features to adapt

- Main chat page: `/Users/groot/media-master/src/renderer/src/pages/AutomationsPage.tsx`.
- Visual components:
  - `ConversationItem`: `lines 112-178` — sidebar row with active state, message count, streaming dot, delete.
  - `MessageBubble`: `lines 381-497` — markdown-capable user/assistant bubbles, reasoning panel, completed tool chips.
  - `StreamingBubble`: `lines 499-634` — live assistant bubble with bouncing dots, streaming reasoning, live text cursor, retry notice, active/completed tool chips.
- Runtime model:
  - `ConversationRuntime`: `lines 640-671` — per-conversation messages/loading/streaming/tool state/request id.
  - `patchRuntime`: `lines 677-689` — targeted runtime updates.
  - `StreamAccumulator`: `lines 691-696` — mutable accumulated text/reasoning/tools outside React state.
- Thread lifecycle:
  - `getOrCreateConversationId`: `lines 88-95` — browser-generated chat ids stored per brand.
  - `handleNewConversation`: `lines 1255-1273` — UUID, empty runtime, switch sidebar to chats.
  - `handleSelectConversation`: `lines 1275-1283` — switch without canceling background streams.
  - `handleDeleteConversation`: `lines 1285-1302` — cancel if active, delete persisted conversation, remove runtime.
- Stream event handling:
  - global listener `lines 917-978` routes by `requestId` to the originating conversation.
  - event shapes in `/Users/groot/media-master/src/shared/automationTypes.ts:405-435`: `delta`, `reasoning`, `tool_start`, `tool_end`, `tool_progress`, `tool_confirm_request`, `compacted`, `steering`, `follow_up`, `retry`, `done`, `error`.
- Send/cancel flow:
  - `handleSendText`: `lines 1071-1171` sends current messages + `conversationId` + `requestId`, stores runtime loading state, finalizes assistant message from accumulated deltas.
  - `handleCancel`: `lines 1173-1193` cancels by `requestId`.
- Sidebar/header/input UI:
  - sidebar tabs + New button: `lines 1317-1414`.
  - chat header status + New chat: `lines 1416-1478`.
  - messages + streaming bubble: `lines 1480-1508`.
  - stop/send controls + Enter behavior: `lines 1511-1720`.
- Main process stream endpoint maps internal events to UI events in `/Users/groot/media-master/src/main/ipc/automations.ts:69-144`; we need an HTTP/SSE equivalent.
- Agent stream consumer details in `/Users/groot/media-master/src/main/services/agent/consume-stream.ts:62-211` show how text/reasoning/tool_call deltas are accumulated. Tribunal can implement a smaller Python version directly in `_processor.py` using OpenAI SDK async streaming.

## Dependency/API verification

- OpenAI Python installed source: `/Users/groot/.opensrc/repos/github.com/openai/openai-python/2.37.0`.
  - `AsyncCompletions.create(..., stream=True)` returns an async stream of chat completion chunks per overload docs in `src/openai/resources/chat/completions/completions.py:2078-2119` and implementation around `2692-2792`.
  - `prompt_cache_key`, `max_completion_tokens`, `tools`, `tool_choice`, `stream`, and `stream_options` are valid Chat Completions parameters (`completions.py:1938-1945`, `2013-2022`, `2029-2041`).
- Starlette source: `/Users/groot/.opensrc/repos/github.com/Kludex/starlette/1.0.0/starlette/responses.py`.
  - `StreamingResponse` accepts an `AsyncIterable` and sends every yielded string/bytes chunk (`lines 222-255`). Use `media_type="text/event-stream"` and `Cache-Control: no-cache` for SSE.
- Frontend API client uses relative browser paths and httpOnly cookies via axios (`frontend/src/lib/api.ts:5-23`). A streaming `fetch()` client can use relative `/api/...` and `credentials: "include"` to send the same cookies through Next rewrites (`frontend/next.config.ts:28-35`).

## Proposed backend design

### Conversation identity and listing

Add multi-chat support without breaking old callers:

- New request field: `conversation_id: uuid.UUID | None = None`.
- If `conversation_id` is present, load that conversation scoped by `workspace_id` + `user_id`; create with that id only if absent.
- If omitted, preserve old behavior by using the latest/legacy conversation for that `(workspace_id, user_id)`.
- New endpoints under the existing assistant router:
  - `GET /conversations` → list conversations for current user/workspace, newest first.
  - `GET /conversations/{conversation_id}` → load a single conversation with messages.
  - `DELETE /conversations/{conversation_id}` → delete one conversation.
  - `POST /chat/stream` → SSE stream for one assistant run.
  - Keep existing `POST /chat` and `GET /history` for compatibility, internally backed by the same conversation-aware processor.

Conversation list response can derive `title` from the first user message and `message_count` from a SQL aggregate. No schema migration is required for title unless we want durable rename later.

### Stream event contract

Define a minimal HTTP/SSE-friendly event contract adapted from Media Master:

```json
{"type":"delta","text":"..."}
{"type":"tool_start","name":"search_contacts"}
{"type":"tool_end","name":"search_contacts"}
{"type":"retry","reason":"stream_stall","attempt":1}
{"type":"error","message":"..."}
{"type":"done","conversation_id":"...","message_id":"...","actions_taken":[...]}
```

Potential future events (`reasoning`, `compacted`) can be included in types but only emitted when data exists. OpenAI GPT-5.4-nano may not expose `reasoning_content`; the UI should support it but not require it.

### Processor changes

Refactor `backend/app/services/ai/crm_assistant/_processor.py` carefully:

- Add helper `_get_or_create_conversation(db, workspace_id, user_id, conversation_id)`.
- Add helper `_build_api_messages(...)` or keep inline but parameterize selected conversation.
- Add stream helper `stream_assistant_message(...) -> AsyncIterator[AssistantStreamEvent]` that mirrors `process_assistant_message` but:
  - persists user message and flushes before streaming;
  - calls `client.chat.completions.create(..., stream=True)`;
  - accumulates content and tool-call chunks by `index` while yielding `delta` events;
  - yields `tool_start` before executing each tool and `tool_end` after each execution;
  - persists assistant/tool messages exactly like the non-stream path;
  - loops up to `MAX_TOOL_TURNS` as before;
  - commits on success or handled timeout/error;
  - emits `done` with conversation id + final assistant message id + action summaries.
- Keep sequential tool execution; do not introduce concurrent DB tool calls.
- Keep `_repair_pairing` and `maybe_summarize` before each LLM call.
- Add practical stream timeout handling. Full Media Master idle/hard timeout logic is larger; first port can use `asyncio.wait_for` around stream creation and provider exceptions mapped to `error` events. If needed, add idle timeout per chunk as a follow-up.
- If a client disconnects, Starlette may cancel the generator. Catch `asyncio.CancelledError`, commit any persisted user/tool messages that are valid, do not save an empty assistant message, and re-raise or return cleanly.

### Cancellation

HTTP cannot cancel by IPC request id like Media Master. Use browser `AbortController` in the frontend. On abort:

- The fetch connection closes.
- The FastAPI streaming generator should observe cancellation and stop generating/persisting final assistant text if no complete text exists.
- The UI clears loading/streaming state and leaves the user message in local runtime. After refetch, only committed messages will remain.

A server-side `POST /chat/cancel/{request_id}` is optional but not necessary for first implementation because there is no persistent job registry yet.

## Proposed frontend design

### API client

Update `frontend/src/lib/api/assistant.ts`:

- Expand types:
  - `AssistantRole = "user" | "assistant" | "tool"`.
  - `AssistantConversationMetaResponse { id, title, message_count, created_at, updated_at }`.
  - `AssistantStreamEvent` union for `delta`, `reasoning`, `tool_start`, `tool_end`, `retry`, `error`, `done`.
- Add methods:
  - `listConversations(workspaceId)`.
  - `getConversation(workspaceId, conversationId)`.
  - `deleteConversation(workspaceId, conversationId)`.
  - `streamChat({ workspaceId, conversationId, message, signal, onEvent })` using `fetch` + `ReadableStream` + `TextDecoder` to parse `data: {json}\n\n` SSE frames.
- Keep `chat()`/`getHistory()` for old tests or route fallback.

### React state/hooks

Replace or supplement `useAssistantChat()` with stream-oriented hooks in `frontend/src/hooks/useAssistant.ts`:

- Add `useAssistantConversations()` using `queryKeys.assistant.conversations(workspaceId)`.
- Add `useAssistantConversation(conversationId)` using `queryKeys.assistant.conversation(workspaceId, conversationId)`.
- Add `useDeleteAssistantConversation()`.
- The streaming send is better as component-local imperative state, as in Media Master, because React Query mutation callbacks do not fit incremental deltas cleanly.

Update query keys in `frontend/src/lib/query-keys.ts`:

- `assistant.all(workspaceId)`
- `assistant.conversations(workspaceId)`
- `assistant.conversation(workspaceId, conversationId)`
- keep `assistant.history(workspaceId)` for compatibility.

### Chat UI

Refactor `frontend/src/components/assistant/assistant-chat.tsx` using Tribunal styling and existing primitives:

- Keep one file unless it grows too large; if it grows beyond maintainability, split into:
  - `assistant-chat.tsx`
  - `assistant-streaming-bubble.tsx`
  - `assistant-conversation-sidebar.tsx`
- Adapt Media Master’s runtime model:
  - local `activeConversationId`, generated with `crypto.randomUUID()` for new chats;
  - local runtime map keyed by conversation id;
  - mutable stream accumulator refs;
  - `AbortController` per active request for stop.
- Sidebar:
  - list prior chats from `useAssistantConversations()`.
  - `New chat` button creates a UUID runtime with welcome/empty state and clears context immediately.
  - selecting a chat loads `GET /conversations/{id}` into runtime.
  - deleting a chat calls backend delete and invalidates conversation list; if active, create new chat.
- Message rendering:
  - Preserve existing `parseWorkflowPayload()` and `OutboundWorkflowCard` behavior for structured outbound workflow JSON.
  - Hide `role === "tool"` in normal transcript, but show completed tool chips from stream events and persisted `tool_calls` where possible.
  - Use `motion` already installed (`frontend/package.json:66`) for pulse/cursor animations, importing from `motion/react` as Media Master does.
  - Avoid `react-markdown`; Tribunal does not currently depend on it. Use `whitespace-pre-wrap` plain text first to avoid adding dependencies.
- Input:
  - Enter sends, Shift+Enter newline.
  - Stop button while streaming calls `AbortController.abort()`.
  - Add retry/re-run-last-message if small and safe, but prioritize new chats + streaming.
- Page layout:
  - `frontend/src/app/assistant/page.tsx` can keep the outer header, or move header/status into `AssistantChat`. Prefer minimal route change: keep page header and let `AssistantChat` render a two-column body below.

### Tests

Update `frontend/src/components/assistant/assistant-chat.test.tsx`:

- Mock new `assistantApi.listConversations`, `getConversation`, `streamChat`, `deleteConversation`.
- Keep outbound workflow card rendering assertion from existing test.
- Add tests:
  - clicking `New chat` shows empty/welcome state and sends with a fresh conversation id (not the old loaded id);
  - stream events append live assistant text and show completed tool chip;
  - Stop button aborts streaming and clears loading state (can be tested via fake `streamChat` that observes `signal.aborted`).

Backend tests:

- Add `backend/tests/test_crm_assistant_conversations.py` or extend current assistant tests:
  - list conversations scoped by workspace/user;
  - create/load two conversation ids and verify messages do not bleed across context;
  - delete conversation removes only that thread.
- Stream endpoint can be unit-tested by monkeypatching the processor stream generator or OpenAI client to emit deterministic chunks.

## Risks / tradeoffs

- Streaming Chat Completions with function calls is more complex than final-message completions because tool call arguments arrive incrementally. We must accumulate tool calls by chunk `index` before executing tools, like Media Master’s `consume-stream.ts:163-183`.
- Existing code assumes one assistant conversation per user/workspace. Introducing multiple conversations changes `/history` semantics unless compatibility is preserved. Keep old `/history` returning latest/default thread.
- `AssistantConversation.updated_at` currently relies on ORM `onupdate`; adding messages may not always update parent rows unless parent is modified. Explicitly set `conversation.updated_at = datetime.now(UTC)` whenever adding a user/assistant/tool message so conversation lists sort reliably.
- Full Media Master “thinking/model selector/attachments/tool confirmation” should not be ported wholesale in first pass. The user asked for visual streaming and fresh chats; tool confirmation can remain the existing pending-action/approval model.
- Browser fetch streaming through Next rewrites should work, but proxy buffering must be verified in runtime. If Next dev/prod buffers SSE, fallback is adding a Next route handler that proxies streaming manually or fetching the backend URL directly with CORS configured.

## Verification criteria

- Frontend after edits: `cd frontend && npm run lint && npm run build`.
- Backend after edits: `cd backend && uv run ruff check app && uv run mypy app`.
- Because backend routes/schemas change: hit assistant endpoints with `.gg/eyes/http.sh` when local backend is running:
  - `GET /api/v1/workspaces/<workspace_id>/assistant/conversations`
  - `GET /api/v1/workspaces/<workspace_id>/assistant/conversations/<conversation_id>`
  - `POST /api/v1/workspaces/<workspace_id>/assistant/chat/stream` if auth/session is available.
- Because `frontend/src/app/assistant/page.tsx`/`components/assistant/*.tsx` change: screenshot `/assistant` with `.gg/eyes/visual-web.sh http://localhost:3000/assistant` when dev server is running.
- Run targeted tests if added/updated:
  - `cd frontend && npm run test -- assistant-chat`
  - `cd backend && uv run pytest tests/test_crm_assistant_conversations.py` (or chosen file).

## Steps

1. Update backend schemas in `backend/app/schemas/crm_assistant.py` with conversation-aware request/response models and a typed stream event schema for documentation.
2. Update `backend/app/services/ai/crm_assistant/_processor.py` to accept optional `conversation_id`, explicitly touch `updated_at`, and factor shared conversation/history setup out of `process_assistant_message`.
3. Add streaming processor support in `_processor.py`: stream Chat Completions chunks, accumulate text/tool calls, execute tools sequentially with `tool_start`/`tool_end` events, persist messages, commit, and yield `done`/`error` events.
4. Export the new stream helper from `backend/app/services/ai/crm_assistant/__init__.py`.
5. Extend `backend/app/api/v1/crm_assistant.py` with `GET /conversations`, `GET /conversations/{conversation_id}`, `DELETE /conversations/{conversation_id}`, and `POST /chat/stream` returning `StreamingResponse` SSE frames while preserving existing `POST /chat` and `GET /history`.
6. Add backend tests for isolated conversations, listing/deleting, and the stream route using a deterministic monkeypatched stream helper.
7. Update `frontend/src/lib/query-keys.ts` assistant keys for conversation lists/details while keeping the legacy history key.
8. Update `frontend/src/lib/api/assistant.ts` with conversation types, list/load/delete methods, and a `fetch`-based SSE `streamChat` parser using `credentials: "include"` and `AbortSignal`.
9. Update `frontend/src/hooks/useAssistant.ts` with conversation list/detail/delete hooks and keep legacy hooks only where still needed by tests or callers.
10. Refactor `frontend/src/components/assistant/assistant-chat.tsx` to use Media Master-style per-conversation runtime state, sidebar chat list, New chat behavior, streaming bubble, tool chips, stop button, and the existing `OutboundWorkflowCard` parser.
11. Adjust `frontend/src/app/assistant/page.tsx` layout only as needed so the new two-column chat fills the available space without duplicating headers awkwardly.
12. Update `frontend/src/components/assistant/assistant-chat.test.tsx` for new API mocks and add coverage for new chat isolation and visible streaming events.
13. Regenerate OpenAPI/generated frontend API types if this repo expects generated specs to stay current.
14. Run backend verification (`cd backend && uv run ruff check app && uv run mypy app`) and relevant backend pytest.
15. Run frontend verification (`cd frontend && npm run lint && npm run build`) and relevant frontend tests.
16. If dev servers are available, verify runtime behavior with `.gg/eyes/http.sh` for new assistant endpoints and `.gg/eyes/visual-web.sh http://localhost:3000/assistant` for the assistant page.
