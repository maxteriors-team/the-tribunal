"use client";

import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ImagePlus,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  Square,
  Trash2,
  User,
  Wrench,
  X,
} from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState } from "react";

import { OutboundWorkflowCard } from "@/components/assistant/outbound-workflow-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { IMAGE_ACCEPT_ATTR, readImageFile } from "@/lib/ai/image-upload";
import type {
  AssistantActionSummary,
  AssistantConversationMetaResponse,
  AssistantMessageResponse,
} from "@/lib/api/assistant";
import {
  parseWorkflowPayload,
  toolNamesFromMessage,
  type ConversationRuntime,
  type PendingActionReviewState,
  type RuntimeTool,
} from "@/lib/assistant/conversation-runtime";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils/date";

export function buildWelcomePrompts(workspaceName: string | null): string[] {
  const businessName = workspaceName?.trim() || "my workspace";
  return [
    `Give me today's CRM briefing for ${businessName}`,
    `Find contacts at ${businessName} who need follow-up`,
    `Schedule a calendar appointment for a contact at ${businessName}`,
    `Create a follow-up workflow automation for ${businessName}`,
  ];
}

export function ConversationSidebar({
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
            <p className="px-2 py-4 text-sm text-muted-foreground">No saved assistant chats yet.</p>
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

export function ChatHeader({
  conversation,
  runtime,
  onNewConversation,
}: {
  conversation?: AssistantConversationMetaResponse;
  runtime: ConversationRuntime;
  onNewConversation: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-6">
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
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full sm:w-auto"
        onClick={onNewConversation}
      >
        <Plus className="mr-1 size-3.5" />
        New chat
      </Button>
    </div>
  );
}

export function EmptyState({
  workspaceName,
  onPrompt,
}: {
  workspaceName: string | null;
  onPrompt: (message: string) => void;
}) {
  const welcomePrompts = buildWelcomePrompts(workspaceName);
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Sparkles className="mb-3 size-10 text-primary/60" />
      <h3 className="text-lg font-semibold text-foreground">CRM Assistant</h3>
      <p className="mt-1 max-w-sm text-sm">
        I can manage contacts, calendar events, workflow automations, campaigns, messages, and more.
        Start a fresh chat or pick a prior one from the sidebar.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {welcomePrompts.map((prompt) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            size="sm"
            className="h-auto max-w-full whitespace-normal text-pretty py-2"
            onClick={() => onPrompt(prompt)}
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  runtime,
  scrollRef,
  workspaceName,
  onPrompt,
  actionReviewStates,
  onApproveAction,
  onRejectAction,
  onRetry,
}: {
  messages: AssistantMessageResponse[];
  runtime: ConversationRuntime;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  workspaceName: string | null;
  onPrompt: (message: string) => void;
  actionReviewStates: Record<string, PendingActionReviewState>;
  onApproveAction: (actionId: string) => Promise<void>;
  onRejectAction: (actionId: string) => Promise<void>;
  onRetry: () => Promise<void>;
}) {
  return (
    <ScrollArea className="min-h-0 flex-1">
      <div ref={scrollRef} className="space-y-4 p-4 lg:p-6">
        {messages.length === 0 && !runtime.isStreaming ? (
          <EmptyState workspaceName={workspaceName} onPrompt={onPrompt} />
        ) : null}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {runtime.pendingApprovals.map((action) => (
          <div key={action.id} className="ml-11 max-w-[92%]">
            <OutboundWorkflowCard
              action={action}
              onApprove={() => void onApproveAction(action.id)}
              onReject={() => void onRejectAction(action.id)}
              isApproving={actionReviewStates[action.id] === "approving"}
              isRejecting={actionReviewStates[action.id] === "rejecting"}
            />
          </div>
        ))}

        {runtime.isStreaming || runtime.streamingText ? (
          <StreamingBubble runtime={runtime} />
        ) : null}

        {runtime.error ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <div className="flex items-center gap-2">
              <AlertCircle className="size-4 shrink-0" />
              {runtime.error}
            </div>
            {runtime.retryRequest ? (
              <Button type="button" size="sm" variant="outline" onClick={() => void onRetry()}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </ScrollArea>
  );
}

export function MessageComposer({
  input,
  isStreaming,
  canSend,
  imageDataUrl,
  isEnhancing,
  enhancementError,
  onInputChange,
  onImageChange,
  onEnhance,
  onSubmit,
  onKeyDown,
  onStop,
}: {
  input: string;
  isStreaming: boolean;
  canSend: boolean;
  imageDataUrl: string | null;
  isEnhancing: boolean;
  enhancementError: string | null;
  onInputChange: (value: string) => void;
  onImageChange: (value: string | null) => void;
  onEnhance: () => void;
  onSubmit: (event: React.FormEvent) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onStop: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [imageError, setImageError] = useState<string | null>(null);

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const { dataUrl, error } = await readImageFile(file);
    if (error || !dataUrl) {
      setImageError(error ?? "Could not read the image file.");
      return;
    }
    setImageError(null);
    onImageChange(dataUrl);
  };

  return (
    <form onSubmit={onSubmit} className="border-t bg-background/95 p-4">
      {imageDataUrl ? (
        <div className="mb-2 inline-flex">
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element -- local preview of a data URL */}
            <img
              src={imageDataUrl}
              alt="Attachment preview"
              className="max-h-24 w-auto rounded-lg border"
            />
            <button
              type="button"
              onClick={() => onImageChange(null)}
              aria-label="Remove image"
              className="absolute -right-2 -top-2 flex size-5 items-center justify-center rounded-full bg-foreground text-background shadow"
            >
              <X className="size-3" />
            </button>
          </div>
        </div>
      ) : null}
      {imageError ? <p className="mb-2 text-xs text-destructive">{imageError}</p> : null}
      {enhancementError ? (
        <p className="mb-2 text-xs text-destructive">{enhancementError}</p>
      ) : null}
      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept={IMAGE_ACCEPT_ATTR}
          className="hidden"
          onChange={(event) => void handleFileChange(event)}
        />
        <Button
          type="button"
          size="icon"
          variant="outline"
          onClick={() => fileInputRef.current?.click()}
          disabled={!canSend || isStreaming}
          aria-label="Attach image"
        >
          <ImagePlus className="size-4" />
        </Button>
        <Textarea
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Ask your CRM assistant…"
          className="max-h-[140px] min-h-[48px] resize-none"
          rows={1}
          onKeyDown={onKeyDown}
          disabled={!canSend}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-12 gap-1.5"
          onClick={onEnhance}
          disabled={!input.trim() || !canSend || isStreaming || isEnhancing}
        >
          {isEnhancing ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Sparkles className="size-4" />
          )}
          Enhance
        </Button>
        {isStreaming ? (
          <Button type="button" size="icon" variant="secondary" onClick={onStop}>
            <Square className="size-4" />
            <span className="sr-only">Stop streaming</span>
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            disabled={(!input.trim() && !imageDataUrl) || !canSend}
            aria-label="Send message"
          >
            <Send className="size-4" />
          </Button>
        )}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Press Enter to send, Shift+Enter for a new line. Attach a photo for the assistant to read.
      </p>
    </form>
  );
}

export function MessageBubble({ message }: { message: AssistantMessageResponse }) {
  const isUser = message.role === "user";
  const workflowPayload = !isUser ? parseWorkflowPayload(message.content) : null;
  const actions = !isUser ? (message.actions_taken ?? []) : [];
  const tools: RuntimeTool[] =
    !isUser && actions.length === 0
      ? toolNamesFromMessage(message).map((name) => ({ name, status: "complete" }))
      : [];

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
          <>
            {message.image ? (
              // eslint-disable-next-line @next/next/no-img-element -- user-supplied data URL, not a static asset
              <img src={message.image} alt="Attached" className="mb-2 max-h-48 w-auto rounded-lg" />
            ) : null}
            {message.content ? <p className="whitespace-pre-wrap">{message.content}</p> : null}
          </>
        )}
        {actions.length > 0 ? <ToolActionDetails actions={actions} /> : null}
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

export function StreamingBubble({ runtime }: { runtime: ConversationRuntime }) {
  const hasText = runtime.streamingText.trim().length > 0;
  return (
    <div className="flex gap-3">
      <AvatarBubble isUser={false} pulsing={runtime.isStreaming} />
      <div className="max-w-[75%] rounded-2xl bg-muted px-4 py-3 text-sm text-foreground">
        {hasText ? (
          <p className="whitespace-pre-wrap">
            {runtime.streamingText}
            {runtime.isStreaming ? (
              <motion.span
                className="ml-0.5 inline-block h-4 w-1 rounded bg-primary align-middle"
                animate={{ opacity: [0.2, 1, 0.2] }}
                transition={{ repeat: Infinity, duration: 0.9 }}
              />
            ) : null}
          </p>
        ) : runtime.isStreaming ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <span>Thinking</span>
            <BouncingDots />
          </div>
        ) : null}
        {runtime.activeTools.length > 0 ? <ToolChips tools={runtime.activeTools} /> : null}
        {runtime.completedTools.length > 0 ? <ToolChips tools={runtime.completedTools} /> : null}
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

function ToolChips({ tools }: { tools: RuntimeTool[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {tools.map((tool, index) => (
        <Badge
          key={`${tool.name}-${index}`}
          variant={tool.status === "running" ? "secondary" : "outline"}
          className={cn(
            "gap-1 text-[11px]",
            tool.status === "complete" &&
              tool.success === false &&
              "border-destructive/40 text-destructive",
          )}
        >
          {tool.status === "running" ? (
            <Loader2 className="size-3 animate-spin" />
          ) : tool.success === false ? (
            <AlertCircle className="size-3" />
          ) : tool.success === true ? (
            <CheckCircle2 className="size-3 text-green-600" />
          ) : (
            <Wrench className="size-3" />
          )}
          {tool.name.replaceAll("_", " ")}
          {tool.status === "complete" && tool.success === false ? " failed" : ""}
        </Badge>
      ))}
    </div>
  );
}

function ToolActionDetails({ actions }: { actions: AssistantActionSummary[] }) {
  return (
    <div className="mt-2 space-y-2">
      {actions.map((action, index) => {
        const result = action.result ?? parseActionSummary(action.summary);
        const pendingApproval = result.pending_approval === true;
        const status = pendingApproval ? "approval needed" : action.success ? "complete" : "failed";
        const resultMessage = typeof result.message === "string" ? result.message : null;
        return (
          <div
            key={`${action.tool_name}-${index}`}
            className="rounded-lg border bg-background/60 p-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={cn(
                  "gap-1 text-[11px]",
                  status === "failed" && "border-destructive/40 text-destructive",
                  status === "approval needed" && "border-amber-500/40 text-amber-700",
                )}
              >
                {status === "failed" ? (
                  <AlertCircle className="size-3" />
                ) : status === "complete" ? (
                  <CheckCircle2 className="size-3 text-green-600" />
                ) : (
                  <Wrench className="size-3" />
                )}
                {action.tool_name.replaceAll("_", " ")} · {status}
              </Badge>
              {resultMessage ? (
                <span className="text-xs text-muted-foreground">{resultMessage}</span>
              ) : null}
            </div>
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                View inputs and result
              </summary>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <ToolJsonBlock label="Inputs" value={action.arguments ?? {}} />
                <ToolJsonBlock label="Result" value={result} />
              </div>
            </details>
          </div>
        );
      })}
    </div>
  );
}

function ToolJsonBlock({ label, value }: { label: string; value: Record<string, unknown> }) {
  return (
    <div className="min-w-0 rounded border bg-muted/30 p-2">
      <p className="mb-1 font-medium text-foreground">{label}</p>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-[11px] text-muted-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function parseActionSummary(summary: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(summary);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : { value: parsed };
  } catch {
    return { value: summary };
  }
}
