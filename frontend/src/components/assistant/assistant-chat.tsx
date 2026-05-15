"use client";

import * as React from "react";
import { Send, Loader2, Bot, User, Sparkles } from "lucide-react";
import { formatTime } from "@/lib/utils/date";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  useAssistantHistory,
  useAssistantChat,
} from "@/hooks/use-assistant";
import type { AssistantMessageResponse } from "@/lib/api/assistant";

export function AssistantChat({ className }: { className?: string }) {
  const { data: history } = useAssistantHistory();
  const chat = useAssistantChat();
  const [input, setInput] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const messages = history?.messages ?? [];

  // Auto-scroll to bottom on new messages
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || chat.isPending) return;
    setInput("");
    chat.mutate(trimmed);
  }

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {/* Messages */}
      <ScrollArea className="flex-1 p-4">
        <div ref={scrollRef} className="space-y-4">
          {messages.length === 0 && <EmptyState />}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
      </ScrollArea>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t p-4">
        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask your CRM assistant…"
            className="min-h-[44px] max-h-[120px] resize-none"
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
          <Button
            type="submit"
            size="icon"
            disabled={!input.trim() || chat.isPending}
            aria-label="Send message"
          >
            {chat.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Sparkles className="mb-3 h-10 w-10 text-primary/60" />
      <h3 className="text-lg font-semibold text-foreground">
        CRM Assistant
      </h3>
      <p className="mt-1 max-w-sm text-sm">
        I can help you search contacts, send messages, check campaigns,
        and more. Just ask!
      </p>
    </div>
  );
}

function MessageBubble({ message }: { message: AssistantMessageResponse }) {
  if (message.role === "tool") return null; // Hide tool messages

  const isUser = message.role === "user";
  const isLoading = message.content === "…" && message.role === "assistant";

  return (
    <div
      className={cn(
        "flex gap-3",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-foreground",
          isLoading && "animate-pulse",
        )}
      >
        <p className="whitespace-pre-wrap">
          {isLoading ? "Thinking…" : message.content}
        </p>
        <p
          className={cn(
            "mt-1 text-[10px]",
            isUser
              ? "text-primary-foreground/60"
              : "text-muted-foreground",
          )}
        >
          {formatTime(message.created_at)}
        </p>
      </div>
    </div>
  );
}
