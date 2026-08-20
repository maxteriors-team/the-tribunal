"use client";

import { Mic, MicOff, Loader2, MessageSquare } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, use, Suspense } from "react";

import { embedFetch } from "@/lib/embed/request";

import { ChatInput, MessageList, type ChatMessage } from "../_chat-ui";
import { DEFAULT_PRIMARY_COLOR, getAgentStateInfo, getEmbedTheme } from "../_theme";
import type { ThemeOption } from "../_types";
import { useAgentConfig, useResolvedTheme } from "../_use-agent-config";
import { useVoiceSession } from "../_use-voice-session";

type Message = ChatMessage;

interface FullpageEmbedProps {
  params: Promise<{ publicId: string }>;
}

function FullpageEmbedContent({ params }: FullpageEmbedProps) {
  const { publicId } = use(params);
  const searchParams = useSearchParams();
  const themeParam = (searchParams.get("theme") as ThemeOption) ?? "auto";

  const resolvedTheme = useResolvedTheme(themeParam);
  const { config, error: configError, setError } = useAgentConfig(publicId);

  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const {
    status: voiceStatus,
    agentState,
    isMuted,
    start: startVoice,
    end: endVoice,
    toggleMute,
  } = useVoiceSession({
    publicId,
    config,
    saveTranscript: true,
    audioAnalysis: "none",
    onError: setSessionError,
    onUserTranscript: (text) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", content: text, timestamp: new Date() },
      ]);
    },
    onAssistantDone: (text) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: text, timestamp: new Date() },
      ]);
    },
  });

  const error = configError ?? sessionError;

  // Greeting message
  /* eslint-disable react-hooks/set-state-in-effect -- One-shot seed from async config. */
  useEffect(() => {
    if (config?.greeting_message && messages.length === 0) {
      setMessages([
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: config.greeting_message,
          timestamp: new Date(),
        },
      ]);
    }
  }, [config, messages.length]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input
  useEffect(() => {
    if (config) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [config]);

  const toggleMic = useCallback(() => {
    if (voiceStatus === "connected") {
      toggleMute();
    } else if (voiceStatus === "idle") {
      void startVoice();
    }
  }, [voiceStatus, toggleMute, startVoice]);

  // Cleanup voice on unmount
  useEffect(() => {
    return () => {
      endVoice();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendMessage = useCallback(async () => {
    if (!inputValue.trim() || isLoading || !config) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsLoading(true);

    try {
      const conversationHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await embedFetch(`/api/v1/p/embed/${publicId}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: userMessage.content,
          conversation_history: conversationHistory,
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error((errData.detail as string) ?? "Failed to get response");
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.response,
          timestamp: new Date(),
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, isLoading, config, messages, publicId, setError]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const theme = getEmbedTheme(resolvedTheme === "dark");
  const primaryColor = config?.primary_color ?? DEFAULT_PRIMARY_COLOR;
  const voiceIsActive = voiceStatus === "connected" || voiceStatus === "connecting";
  const stateInfo = getAgentStateInfo(agentState, primaryColor);

  if (error && !config) {
    return (
      <div
        className="flex h-screen w-screen items-center justify-center"
        style={{ backgroundColor: theme.pageBg }}
      >
        <div className="rounded-lg bg-red-50 p-6 text-red-600 shadow-lg">
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!config) {
    return (
      <div
        className="flex h-screen w-screen items-center justify-center"
        style={{ backgroundColor: theme.pageBg }}
      >
        <Loader2 className="h-8 w-8 animate-spin" style={{ color: primaryColor }} />
      </div>
    );
  }

  return (
    <div
      className="flex h-screen w-screen flex-col font-sans"
      style={{ backgroundColor: theme.pageBg, color: theme.text }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-center px-4 py-3"
        style={{
          backgroundColor: theme.panelBg,
          borderBottom: `1px solid ${theme.panelBorder}`,
          boxShadow: voiceIsActive
            ? `0 2px 12px ${stateInfo.color}40`
            : "0 1px 3px rgba(0,0,0,0.1)",
          transition: "box-shadow 0.3s ease",
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-full"
            style={{ backgroundColor: primaryColor }}
          >
            <MessageSquare className="h-4 w-4 text-white" />
          </div>
          <span className="font-semibold" style={{ color: theme.text }}>
            {config.name}
          </span>
          {voiceIsActive && (
            <div className="flex items-center gap-1.5">
              <div
                className="h-2 w-2 rounded-full"
                style={{
                  backgroundColor: voiceStatus === "connecting" ? "#f59e0b" : stateInfo.color,
                  boxShadow: `0 0 6px ${voiceStatus === "connecting" ? "#f59e0b" : stateInfo.color}`,
                  animation: voiceStatus === "connecting" ? "pulse 1.5s infinite" : undefined,
                }}
              />
              <span
                className="text-xs font-medium"
                style={{
                  color: voiceStatus === "connecting" ? "#f59e0b" : stateInfo.color,
                }}
              >
                {voiceStatus === "connecting" ? "Connecting..." : stateInfo.label}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      <MessageList
        messages={messages}
        isLoading={isLoading}
        theme={theme}
        primaryColor={primaryColor}
        agentName={config.name}
        bubbleMaxWidth="max-w-[70%]"
        messagesEndRef={messagesEndRef}
      />

      {/* Input area */}
      <div
        className="border-t p-3"
        style={{ backgroundColor: theme.panelBg, borderColor: theme.panelBorder }}
      >
        {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
        <ChatInput
          inputRef={inputRef}
          value={inputValue}
          onChange={setInputValue}
          onKeyDown={handleKeyDown}
          onSend={() => void sendMessage()}
          disabled={!inputValue.trim() || isLoading}
          placeholder="Type a message..."
          isLoading={isLoading}
          theme={theme}
          primaryColor={primaryColor}
          trailing={
            <button
              type="button"
              onClick={toggleMic}
              disabled={voiceStatus === "connecting"}
              aria-label={
                voiceStatus === "connecting"
                  ? "Connecting voice"
                  : voiceIsActive
                    ? isMuted
                      ? "Unmute microphone"
                      : "Mute microphone"
                    : "Start voice"
              }
              className="flex h-10 w-10 items-center justify-center rounded-full transition-all hover:scale-105 disabled:opacity-50"
              style={{
                backgroundColor: voiceIsActive
                  ? isMuted
                    ? "#ef4444"
                    : stateInfo.color
                  : theme.iconBg,
                color: voiceIsActive ? "#ffffff" : theme.iconColor,
              }}
              title={
                voiceIsActive ? (isMuted ? "Unmute microphone" : "Mute microphone") : "Start voice"
              }
            >
              {voiceStatus === "connecting" ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : voiceIsActive && isMuted ? (
                <MicOff className="h-5 w-5" />
              ) : (
                <Mic className="h-5 w-5" />
              )}
            </button>
          }
        />
      </div>
    </div>
  );
}

export default function FullpageEmbedPage({ params }: FullpageEmbedProps) {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen w-screen items-center justify-center bg-gray-50">
          <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
        </div>
      }
    >
      <FullpageEmbedContent params={params} />
    </Suspense>
  );
}
