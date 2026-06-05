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
import type { AssistantConversationMetaResponse, AssistantMessageResponse } from "@/lib/api/assistant";
import {
  parseWorkflowPayload,
  toolNamesFromMessage,
  type ConversationRuntime,
} from "@/lib/assistant/conversation-runtime";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils/date";

export const welcomePrompts = [
  "Find contacts who have not replied this month",
  "Draft a win-back SMS campaign",
  "Summarize recent warm leads",
];

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

export function EmptyState({ onPrompt }: { onPrompt: (message: string) => Promise<void> }) {
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

export function MessageList({
  messages,
  runtime,
  scrollRef,
  onPrompt,
}: {
  messages: AssistantMessageResponse[];
  runtime: ConversationRuntime;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onPrompt: (message: string) => Promise<void>;
}) {
  return (
    <ScrollArea className="min-h-0 flex-1">
      <div ref={scrollRef} className="space-y-4 p-4 lg:p-6">
        {messages.length === 0 && !runtime.isStreaming ? (
          <EmptyState onPrompt={onPrompt} />
        ) : null}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {runtime.isStreaming ? <StreamingBubble runtime={runtime} /> : null}

        {runtime.error ? (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="size-4" />
            {runtime.error}
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
  onInputChange,
  onImageChange,
  onSubmit,
  onKeyDown,
  onStop,
}: {
  input: string;
  isStreaming: boolean;
  canSend: boolean;
  imageDataUrl: string | null;
  onInputChange: (value: string) => void;
  onImageChange: (value: string | null) => void;
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
      {imageError ? (
        <p className="mb-2 text-xs text-destructive">{imageError}</p>
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
          <>
            {message.image ? (
              // eslint-disable-next-line @next/next/no-img-element -- user-supplied data URL, not a static asset
              <img
                src={message.image}
                alt="Attached"
                className="mb-2 max-h-48 w-auto rounded-lg"
              />
            ) : null}
            {message.content ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : null}
          </>
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

export function StreamingBubble({ runtime }: { runtime: ConversationRuntime }) {
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
