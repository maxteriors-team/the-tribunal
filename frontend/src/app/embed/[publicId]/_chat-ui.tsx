"use client";

/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- Named message history must accept keyboard focus. */

import { Send, Loader2 } from "lucide-react";
import type { RefObject } from "react";

import type { EmbedTheme } from "./_theme";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

/** A single chat bubble. Pure presentation. */
export function MessageBubble({
  message,
  theme,
  primaryColor,
  maxWidthClass = "max-w-[80%]",
}: {
  message: ChatMessage;
  theme: EmbedTheme;
  primaryColor: string;
  maxWidthClass?: string;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`mb-3 flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`${maxWidthClass} rounded-2xl px-4 py-2 ${
          isUser ? "rounded-br-md" : "rounded-bl-md"
        }`}
        style={{
          backgroundColor: isUser ? primaryColor : theme.bubbleAssistantBg,
          color: isUser ? theme.textOnPrimary : theme.bubbleAssistantText,
          boxShadow: isUser ? "none" : theme.bubbleShadow,
        }}
      >
        <p className="whitespace-pre-wrap text-sm">{message.content}</p>
      </div>
    </div>
  );
}

/** Three bouncing dots used while the assistant is preparing a chat reply. */
export function TypingDots({ theme, primaryColor }: { theme: EmbedTheme; primaryColor: string }) {
  return (
    <div className="mb-3 flex justify-start">
      <div
        className="flex items-center gap-2 rounded-2xl rounded-bl-md px-4 py-2"
        style={{
          backgroundColor: theme.bubbleAssistantBg,
          boxShadow: theme.bubbleShadow,
        }}
      >
        <div className="flex gap-1">
          {[0, 150, 300].map((delay) => (
            <div
              key={delay}
              className="h-2 w-2 animate-bounce rounded-full"
              style={{ backgroundColor: primaryColor, animationDelay: `${delay}ms` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** Scrollable list of messages with greeting placeholder and typing indicator. */
export function MessageList({
  messages,
  isLoading,
  theme,
  primaryColor,
  agentName,
  bubbleMaxWidth,
  messagesEndRef,
}: {
  messages: ChatMessage[];
  isLoading: boolean;
  theme: EmbedTheme;
  primaryColor: string;
  agentName: string;
  bubbleMaxWidth?: string;
  messagesEndRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      tabIndex={0}
      role="log"
      aria-label="Conversation messages"
      aria-live="polite"
      className="flex-1 overflow-y-auto p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset"
      style={{ backgroundColor: theme.messagesBg }}
    >
      {messages.length === 0 && (
        <div className="flex h-full items-center justify-center">
          <p className="text-center text-sm" style={{ color: theme.textMuted }}>
            Start a conversation with {agentName}
          </p>
        </div>
      )}

      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          theme={theme}
          primaryColor={primaryColor}
          maxWidthClass={bubbleMaxWidth}
        />
      ))}

      {isLoading && <TypingDots theme={theme} primaryColor={primaryColor} />}

      <div ref={messagesEndRef} />
    </div>
  );
}

/** Text input with send button, theme-aware. The voice mic button is page-specific. */
export function ChatInput({
  inputRef,
  value,
  onChange,
  onKeyDown,
  onSend,
  disabled,
  placeholder,
  isLoading,
  theme,
  primaryColor,
  trailing,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  value: string;
  onChange: (next: string) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onSend: () => void;
  disabled: boolean;
  placeholder: string;
  isLoading: boolean;
  theme: EmbedTheme;
  primaryColor: string;
  /** Optional trailing controls — e.g. the voice toggle button. */
  trailing?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label="Message"
        disabled={isLoading}
        className="flex-1 rounded-full border px-4 py-2 text-sm outline-none transition-all focus:ring-2"
        style={{
          backgroundColor: theme.inputBg,
          borderColor: theme.inputBorder,
          color: theme.text,
        }}
      />
      <button
        type="button"
        onClick={onSend}
        disabled={disabled}
        aria-label={isLoading ? "Sending message" : "Send message"}
        className="flex h-10 w-10 items-center justify-center rounded-full transition-all hover:scale-105 disabled:opacity-50"
        style={{ backgroundColor: primaryColor }}
      >
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-white" aria-hidden="true" />
        ) : (
          <Send className="h-5 w-5 text-white" aria-hidden="true" />
        )}
      </button>
      {trailing}
    </div>
  );
}
