"use client";

import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  Square,
  Trash2,
  User,
  Wrench,
} from "lucide-react";
import { motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { OutboundWorkflowCard } from "@/components/assistant/outbound-workflow-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import {
  useAssistantConversation,
  useAssistantConversations,
  useDeleteAssistantConversation,
} from "@/hooks/useAssistant";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  assistantApi,
  type AssistantConversationMetaResponse,
  type AssistantMessageResponse,
  type AssistantStreamEvent,
} from "@/lib/api/assistant";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils/date";

interface RuntimeTool {
  name: string;
  status: "running" | "complete";
  success?: boolean | null;
}

interface ConversationRuntime {
  messages: AssistantMessageResponse[];
  streamingText: string;
  reasoningText: string;
  activeTools: RuntimeTool[];
  completedTools: RuntimeTool[];
  isStreaming: boolean;
  error: string | null;
  retryNotice: string | null;
  requestId: string | null;
}

interface StreamAccumulator {
  text: string;
  reasoning: string;
  activeTools: RuntimeTool[];
  completedTools: RuntimeTool[];
}

const emptyRuntime = (): ConversationRuntime => ({
  messages: [],
  streamingText: "",
  reasoningText: "",
  activeTools: [],
  completedTools: [],
  isStreaming: false,
  error: null,
  retryNotice: null,
  requestId: null,
});

const welcomePrompts = [
  "Find contacts who have not replied this month",
  "Draft a win-back SMS campaign",
  "Summarize recent warm leads",
];

function createRuntimeId(): string {
  return crypto.randomUUID();
}

export function AssistantChat({ className }: { className?: string }) {
  const workspaceId = useWorkspaceId();
  const conversationsQuery = useAssistantConversations();
  const conversations = useMemo(
    () => conversationsQuery.data ?? [],
    [conversationsQuery.data],
  );
  const [draftConversationId, setDraftConversationId] = useState(() => createRuntimeId());
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [runtimes, setRuntimes] = useState<Record<string, ConversationRuntime>>({});
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllersRef = useRef<Record<string, AbortController>>({});
  const accumulatorsRef = useRef<Record<string, StreamAccumulator>>({});
  const isDraftActive = activeConversationId === draftConversationId;
  const resolvedActiveConversationId =
    activeConversationId ?? conversations[0]?.id ?? draftConversationId;
  const activeConversation = useMemo(
    () =>
      isDraftActive
        ? undefined
        : conversations.find(
            (conversation) => conversation.id === resolvedActiveConversationId,
          ),
    [isDraftActive, resolvedActiveConversationId, conversations],
  );
  const conversationQuery = useAssistantConversation(
    activeConversation && !runtimes[activeConversation.id]?.isStreaming
      ? activeConversation.id
      : null,
  );
  const deleteConversation = useDeleteAssistantConversation();

  const activeRuntime = useMemo(() => {
    const storedRuntime = runtimes[resolvedActiveConversationId];
    if (storedRuntime?.isStreaming || storedRuntime?.messages.length || isDraftActive) {
      return storedRuntime ?? emptyRuntime();
    }
    if (conversationQuery.data?.id === resolvedActiveConversationId) {
      return { ...emptyRuntime(), messages: conversationQuery.data.messages };
    }
    return storedRuntime ?? emptyRuntime();
  }, [conversationQuery.data, isDraftActive, resolvedActiveConversationId, runtimes]);
  const visibleMessages = activeRuntime.messages.filter((message) => message.role !== "tool");

  const patchRuntime = useCallback(
    (conversationId: string, patch: Partial<ConversationRuntime>) => {
      setRuntimes((current) => ({
        ...current,
        [conversationId]: {
          ...(current[conversationId] ?? emptyRuntime()),
          ...patch,
        },
      }));
    },
    [],
  );

  const createConversationRuntime = useCallback((conversationId: string) => {
    setRuntimes((current) => ({
      ...current,
      [conversationId]: current[conversationId] ?? emptyRuntime(),
    }));
    setActiveConversationId(conversationId);
  }, []);

  const handleNewConversation = useCallback(() => {
    const conversationId = createRuntimeId();
    setDraftConversationId(conversationId);
    createConversationRuntime(conversationId);
  }, [createConversationRuntime]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [
    visibleMessages.length,
    activeRuntime.streamingText,
    activeRuntime.activeTools.length,
    activeRuntime.completedTools.length,
  ]);

  useEffect(() => {
    const abortControllers = abortControllersRef.current;
    return () => {
      Object.values(abortControllers).forEach((controller) => controller.abort());
    };
  }, []);

  const handleSelectConversation = (conversationId: string) => {
    setActiveConversationId(conversationId);
  };

  const handleDeleteConversation = async (conversationId: string) => {
    abortControllersRef.current[conversationId]?.abort();
    delete abortControllersRef.current[conversationId];
    delete accumulatorsRef.current[conversationId];
    await deleteConversation.mutateAsync(conversationId);
    setRuntimes((current) => {
      const next = { ...current };
      delete next[conversationId];
      return next;
    });
    if (resolvedActiveConversationId === conversationId) {
      handleNewConversation();
    }
  };

  const applyStreamEvent = (conversationId: string, event: AssistantStreamEvent) => {
    const accumulator = accumulatorsRef.current[conversationId];
    if (!accumulator) return;

    if (event.type === "delta") {
      accumulator.text += event.text;
      patchRuntime(conversationId, { streamingText: accumulator.text });
      return;
    }

    if (event.type === "reasoning") {
      accumulator.reasoning += event.text;
      patchRuntime(conversationId, { reasoningText: accumulator.reasoning });
      return;
    }

    if (event.type === "tool_start") {
      accumulator.activeTools = [
        ...accumulator.activeTools.filter((tool) => tool.name !== event.name),
        { name: event.name, status: "running" },
      ];
      patchRuntime(conversationId, { activeTools: accumulator.activeTools });
      return;
    }

    if (event.type === "tool_end") {
      accumulator.activeTools = accumulator.activeTools.filter(
        (tool) => tool.name !== event.name,
      );
      accumulator.completedTools = [
        ...accumulator.completedTools,
        { name: event.name, status: "complete", success: event.success },
      ];
      patchRuntime(conversationId, {
        activeTools: accumulator.activeTools,
        completedTools: accumulator.completedTools,
      });
      return;
    }

    if (event.type === "retry") {
      patchRuntime(conversationId, {
        retryNotice: `Retrying ${event.reason.replaceAll("_", " ")} (${event.attempt})`,
      });
      return;
    }

    if (event.type === "error") {
      patchRuntime(conversationId, {
        isStreaming: false,
        error: event.message,
        requestId: null,
      });
      return;
    }

    const assistantMessage: AssistantMessageResponse | null = accumulator.text
      ? {
          id: event.message_id ?? `assistant-${event.conversation_id}-${Date.now()}`,
          role: "assistant",
          content: accumulator.text,
          tool_calls: accumulator.completedTools.map((tool, index) => ({
            id: `tool-${index}`,
            function: { name: tool.name, arguments: "{}" },
          })),
          created_at: new Date().toISOString(),
        }
      : null;
    setRuntimes((current) => {
      const runtime = current[conversationId] ?? emptyRuntime();
      return {
        ...current,
        [conversationId]: {
          ...runtime,
          messages: assistantMessage ? [...runtime.messages, assistantMessage] : runtime.messages,
          streamingText: "",
          reasoningText: "",
          activeTools: [],
          completedTools: accumulator.completedTools,
          isStreaming: false,
          error: null,
          retryNotice: null,
          requestId: null,
        },
      };
    });
    delete abortControllersRef.current[conversationId];
    delete accumulatorsRef.current[conversationId];
  };

  const sendMessage = async (rawMessage: string) => {
    const trimmed = rawMessage.trim();
    if (!trimmed || !workspaceId) return;

    const conversationId = resolvedActiveConversationId;
    setActiveConversationId(conversationId);
    if (conversationId === draftConversationId && !runtimes[conversationId]) {
      createConversationRuntime(conversationId);
    }
    const requestId = createRuntimeId();
    const userMessage: AssistantMessageResponse = {
      id: `user-${requestId}`,
      role: "user",
      content: trimmed,
      created_at: new Date().toISOString(),
    };
    const controller = new AbortController();
    abortControllersRef.current[conversationId] = controller;
    accumulatorsRef.current[conversationId] = {
      text: "",
      reasoning: "",
      activeTools: [],
      completedTools: [],
    };

    setInput("");
    setRuntimes((current) => {
      const runtime =
        current[conversationId] ??
        (conversationQuery.data?.id === conversationId
          ? { ...emptyRuntime(), messages: conversationQuery.data.messages }
          : emptyRuntime());
      return {
        ...current,
        [conversationId]: {
          ...runtime,
          messages: [...runtime.messages, userMessage],
          streamingText: "",
          reasoningText: "",
          activeTools: [],
          completedTools: [],
          isStreaming: true,
          error: null,
          retryNotice: null,
          requestId,
        },
      };
    });

    try {
      await assistantApi.streamChat({
        workspaceId,
        conversationId,
        message: trimmed,
        signal: controller.signal,
        onEvent: (event) => applyStreamEvent(conversationId, event),
      });
      void conversationsQuery.refetch();
    } catch (error) {
      if (controller.signal.aborted) {
        patchRuntime(conversationId, {
          isStreaming: false,
          streamingText: "",
          activeTools: [],
          requestId: null,
        });
        return;
      }
      patchRuntime(conversationId, {
        isStreaming: false,
        error: error instanceof Error ? error.message : "Assistant stream failed.",
        requestId: null,
      });
    } finally {
      delete abortControllersRef.current[conversationId];
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (activeRuntime.isStreaming) return;
    void sendMessage(input);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!activeRuntime.isStreaming) void sendMessage(input);
    }
  };

  const handleStop = () => {
    abortControllersRef.current[resolvedActiveConversationId]?.abort();
    patchRuntime(resolvedActiveConversationId, {
      isStreaming: false,
      streamingText: "",
      activeTools: [],
      requestId: null,
    });
  };

  return (
    <div className={cn("flex h-full min-h-0 overflow-hidden", className)}>
      <ConversationSidebar
        conversations={conversations}
        activeConversationId={resolvedActiveConversationId}
        runtimes={runtimes}
        isLoading={conversationsQuery.isLoading}
        onNewConversation={handleNewConversation}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={(conversationId) => void handleDeleteConversation(conversationId)}
      />

      <section className="flex min-w-0 flex-1 flex-col bg-background">
        <ChatHeader
          conversation={activeConversation}
          runtime={activeRuntime}
          onNewConversation={handleNewConversation}
        />

        <ScrollArea className="min-h-0 flex-1">
          <div ref={scrollRef} className="space-y-4 p-4 lg:p-6">
            {visibleMessages.length === 0 && !activeRuntime.isStreaming ? (
              <EmptyState onPrompt={sendMessage} />
            ) : null}

            {visibleMessages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}

            {activeRuntime.isStreaming ? <StreamingBubble runtime={activeRuntime} /> : null}

            {activeRuntime.error ? (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="size-4" />
                {activeRuntime.error}
              </div>
            ) : null}
          </div>
        </ScrollArea>

        <form onSubmit={handleSubmit} className="border-t bg-background/95 p-4">
          <div className="flex items-end gap-2">
            <Textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask your CRM assistant…"
              className="max-h-[140px] min-h-[48px] resize-none"
              rows={1}
              onKeyDown={handleKeyDown}
              disabled={!workspaceId}
            />
            {activeRuntime.isStreaming ? (
              <Button type="button" size="icon" variant="secondary" onClick={handleStop}>
                <Square className="size-4" />
                <span className="sr-only">Stop streaming</span>
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon"
                disabled={!input.trim() || !workspaceId}
                aria-label="Send message"
              >
                <Send className="size-4" />
              </Button>
            )}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Press Enter to send, Shift+Enter for a new line.
          </p>
        </form>
      </section>
    </div>
  );
}

function ConversationSidebar({
  conversations,
  activeConversationId,
  runtimes,
  isLoading,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
}: {
  conversations: AssistantConversationMetaResponse[];
  activeConversationId: string | null;
  runtimes: Record<string, ConversationRuntime>;
  isLoading: boolean;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
}) {
  return (
    <aside className="hidden w-72 shrink-0 border-r bg-muted/20 md:flex md:flex-col">
      <div className="flex items-center justify-between border-b p-3">
        <div>
          <p className="text-sm font-medium">Chats</p>
          <p className="text-xs text-muted-foreground">Switch context anytime</p>
        </div>
        <Button size="sm" onClick={onNewConversation}>
          <Plus className="mr-1 size-3.5" />
          New
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-1 p-2">
          {isLoading ? (
            <div className="flex items-center gap-2 px-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading chats…
            </div>
          ) : null}
          {conversations.map((conversation) => (
            <ConversationItem
              key={conversation.id}
              conversation={conversation}
              runtime={runtimes[conversation.id]}
              isActive={conversation.id === activeConversationId}
              onSelect={() => onSelectConversation(conversation.id)}
              onDelete={() => onDeleteConversation(conversation.id)}
            />
          ))}
          {!isLoading && conversations.length === 0 ? (
            <p className="px-2 py-4 text-sm text-muted-foreground">
              No saved assistant chats yet.
            </p>
          ) : null}
        </div>
      </ScrollArea>
    </aside>
  );
}

function ConversationItem({
  conversation,
  runtime,
  isActive,
  onSelect,
  onDelete,
}: {
  conversation: AssistantConversationMetaResponse;
  runtime?: ConversationRuntime;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors",
        isActive ? "bg-background shadow-sm" : "hover:bg-background/70",
      )}
    >
      <button type="button" className="min-w-0 flex-1 text-left" onClick={onSelect}>
        <div className="flex items-center gap-2">
          <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
          <p className="truncate text-sm font-medium">{conversation.title}</p>
          {runtime?.isStreaming ? (
            <span className="size-1.5 shrink-0 rounded-full bg-primary" />
          ) : null}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {conversation.message_count} messages · {formatTime(conversation.updated_at)}
        </p>
      </button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="size-7 opacity-0 group-hover:opacity-100"
        onClick={onDelete}
      >
        <Trash2 className="size-3.5" />
        <span className="sr-only">Delete chat</span>
      </Button>
    </div>
  );
}

function ChatHeader({
  conversation,
  runtime,
  onNewConversation,
}: {
  conversation?: AssistantConversationMetaResponse;
  runtime: ConversationRuntime;
  onNewConversation: () => void;
}) {
  return (
    <div className="flex items-center justify-between border-b px-4 py-3 lg:px-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="truncate text-sm font-semibold">
            {conversation?.title ?? "New assistant chat"}
          </h2>
          {runtime.isStreaming ? (
            <Badge variant="secondary" className="gap-1">
              <span className="size-1.5 rounded-full bg-primary" />
              Streaming
            </Badge>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground">
          {runtime.isStreaming ? "Working live…" : "Each chat keeps its own CRM context."}
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onNewConversation}>
        <Plus className="mr-1 size-3.5" />
        New chat
      </Button>
    </div>
  );
}

function EmptyState({ onPrompt }: { onPrompt: (message: string) => Promise<void> }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Sparkles className="mb-3 size-10 text-primary/60" />
      <h3 className="text-lg font-semibold text-foreground">CRM Assistant</h3>
      <p className="mt-1 max-w-sm text-sm">
        I can help you search contacts, send messages, check campaigns, and more.
        Start a fresh chat or pick a prior one from the sidebar.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {welcomePrompts.map((prompt) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void onPrompt(prompt)}
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: AssistantMessageResponse }) {
  const isUser = message.role === "user";
  const workflowPayload = !isUser ? parseWorkflowPayload(message.content) : null;
  const tools = !isUser ? toolNamesFromMessage(message) : [];

  return (
    <div className={cn("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <AvatarBubble isUser={isUser} />

      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm",
          workflowPayload && "max-w-[92%] bg-transparent p-0",
          !workflowPayload &&
            (isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"),
        )}
      >
        {workflowPayload ? (
          <OutboundWorkflowCard payload={workflowPayload} />
        ) : (
          <p className="whitespace-pre-wrap">{message.content}</p>
        )}
        {tools.length > 0 ? <ToolChips tools={tools} /> : null}
        <p
          className={cn(
            "mt-1 text-[10px]",
            isUser ? "text-primary-foreground/60" : "text-muted-foreground",
          )}
        >
          {formatTime(message.created_at)}
        </p>
      </div>
    </div>
  );
}

function StreamingBubble({ runtime }: { runtime: ConversationRuntime }) {
  const hasText = runtime.streamingText.trim().length > 0;
  return (
    <div className="flex gap-3">
      <AvatarBubble isUser={false} pulsing />
      <div className="max-w-[75%] rounded-2xl bg-muted px-4 py-3 text-sm text-foreground">
        {runtime.retryNotice ? (
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            <AlertCircle className="size-3.5" />
            {runtime.retryNotice}
          </div>
        ) : null}
        {runtime.reasoningText ? (
          <div className="mb-2 rounded-lg border bg-background/60 p-2 text-xs text-muted-foreground">
            <p className="font-medium text-foreground">Reasoning</p>
            <p className="mt-1 whitespace-pre-wrap">{runtime.reasoningText}</p>
          </div>
        ) : null}
        {hasText ? (
          <p className="whitespace-pre-wrap">
            {runtime.streamingText}
            <motion.span
              className="ml-0.5 inline-block h-4 w-1 rounded bg-primary align-middle"
              animate={{ opacity: [0.2, 1, 0.2] }}
              transition={{ repeat: Infinity, duration: 0.9 }}
            />
          </p>
        ) : (
          <div className="flex items-center gap-2 text-muted-foreground">
            <span>Thinking</span>
            <BouncingDots />
          </div>
        )}
        {runtime.activeTools.length > 0 ? (
          <ToolChips tools={runtime.activeTools.map((tool) => tool.name)} active />
        ) : null}
        {runtime.completedTools.length > 0 ? (
          <ToolChips tools={runtime.completedTools.map((tool) => tool.name)} />
        ) : null}
      </div>
    </div>
  );
}

function AvatarBubble({ isUser, pulsing = false }: { isUser: boolean; pulsing?: boolean }) {
  return (
    <div
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full",
        isUser ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
        pulsing && "ring-2 ring-primary/20",
      )}
    >
      {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
    </div>
  );
}

function BouncingDots() {
  return (
    <span className="inline-flex gap-1">
      {[0, 1, 2].map((index) => (
        <motion.span
          key={index}
          className="size-1 rounded-full bg-muted-foreground"
          animate={{ y: [0, -3, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ repeat: Infinity, duration: 0.8, delay: index * 0.12 }}
        />
      ))}
    </span>
  );
}

function ToolChips({ tools, active = false }: { tools: string[]; active?: boolean }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {tools.map((tool, index) => (
        <Badge
          key={`${tool}-${index}`}
          variant={active ? "secondary" : "outline"}
          className="gap-1 text-[11px]"
        >
          {active ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <CheckCircle2 className="size-3 text-green-600" />
          )}
          <Wrench className="size-3" />
          {tool.replaceAll("_", " ")}
        </Badge>
      ))}
    </div>
  );
}

function toolNamesFromMessage(message: AssistantMessageResponse): string[] {
  return (message.tool_calls ?? [])
    .map((toolCall) => toolCall.function?.name)
    .filter((name): name is string => Boolean(name));
}

function parseWorkflowPayload(content: string): Record<string, unknown> | null {
  if (!content.trim().startsWith("{")) return null;

  try {
    const parsed: unknown = JSON.parse(content);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;

    const record = parsed as Record<string, unknown>;
    if (
      record.type === "outbound_workflow" ||
      record.outbound_workflow === true ||
      record.segment_preview ||
      record.message_previews ||
      record.launch_status ||
      record.warm_lead_handoff
    ) {
      return record;
    }
  } catch {
    return null;
  }

  return null;
}
