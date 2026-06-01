"use client";

import { X, Mic, MicOff, MessageSquare, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, use, Suspense } from "react";

import {
  postToParent,
  subscribeToEmbedMessages,
} from "@/lib/embed/messaging";

import { ChatInput, MessageList, type ChatMessage } from "../_chat-ui";
import {
  DEFAULT_PRIMARY_COLOR,
  getAgentStateInfo,
  getEmbedTheme,
} from "../_theme";
import { POSITION_CLASSES, type ThemeOption } from "../_types";
import { useAgentConfig, useResolvedTheme } from "../_use-agent-config";
import { useVoiceSession } from "../_use-voice-session";

type Message = ChatMessage;

interface BothEmbedPageProps {
  params: Promise<{ publicId: string }>;
}

function BothEmbedPageContent({ params }: BothEmbedPageProps) {
  const { publicId } = use(params);
  const searchParams = useSearchParams();
  const themeParam = (searchParams.get("theme") as ThemeOption) ?? "auto";
  const position = searchParams.get("position") ?? "bottom-right";
  const autostart = searchParams.get("autostart") === "true";

  const resolvedTheme = useResolvedTheme(themeParam);
  const { config, error: configError, setError } = useAgentConfig(publicId);

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Track a streaming assistant message (for voice transcripts)
  const currentAssistantMsgIdRef = useRef<string>("");
  const currentAssistantTextRef = useRef<string>("");
  const autostartTriggeredRef = useRef(false);

  // Voice session — routes transcripts straight into the chat list.
  const {
    status: voiceStatus,
    agentState,
    smoothedLevel,
    start: startVoice,
    end: endVoice,
  } = useVoiceSession({
    publicId,
    config,
    audioAnalysis: "level",
    onError: setSessionError,
    onUserTranscript: (text) => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", content: text, timestamp: new Date() },
      ]);
    },
    onAssistantDelta: (delta) => {
      currentAssistantTextRef.current += delta;
      const msgId = currentAssistantMsgIdRef.current;
      if (!msgId) {
        const newId = crypto.randomUUID();
        currentAssistantMsgIdRef.current = newId;
        setMessages((prev) => [
          ...prev,
          {
            id: newId,
            role: "assistant",
            content: currentAssistantTextRef.current,
            timestamp: new Date(),
          },
        ]);
      } else {
        const text = currentAssistantTextRef.current;
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, content: text } : m))
        );
      }
    },
    onAssistantDone: (finalText) => {
      const msgId = currentAssistantMsgIdRef.current;
      if (msgId) {
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, content: finalText } : m))
        );
      }
      currentAssistantTextRef.current = "";
      currentAssistantMsgIdRef.current = "";
    },
  });

  const error = configError ?? sessionError;

  // Greeting message after config loads
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

  // Notify parent of state
  useEffect(() => {
    const state =
      voiceStatus === "connected"
        ? agentState
        : isChatLoading
          ? "thinking"
          : "idle";
    postToParent({ type: "ai-agent:state", state });
  }, [agentState, isChatLoading, voiceStatus]);

  // Notify parent of audio level
  useEffect(() => {
    if (smoothedLevel > 0.05) {
      postToParent({ type: "ai-agent:audio-level", level: smoothedLevel });
    }
  }, [smoothedLevel]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  // Auto-start voice if requested
  useEffect(() => {
    if (autostart && config && !autostartTriggeredRef.current) {
      autostartTriggeredRef.current = true;
      void startVoice();
    }
  }, [autostart, config, startVoice]);

  // Listen for start message from parent
  useEffect(() => {
    return subscribeToEmbedMessages((message) => {
      if (message.type === "ai-agent:start" && config && voiceStatus === "idle") {
        void startVoice();
      }
    });
  }, [voiceStatus, config, startVoice]);

  const sendMessage = useCallback(async () => {
    if (!inputValue.trim() || isChatLoading || !config) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsChatLoading(true);

    try {
      const conversationHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await fetch(`/api/v1/p/embed/${publicId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: window.location.origin },
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
      setIsChatLoading(false);
    }
  }, [inputValue, isChatLoading, config, messages, publicId, setError]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const closeChat = () => {
    endVoice();
    postToParent({ type: "ai-agent:close" });
  };

  const toggleVoice = () => {
    if (voiceStatus === "connected" || voiceStatus === "connecting") {
      endVoice();
    } else {
      void startVoice();
    }
  };

  const theme = getEmbedTheme(resolvedTheme === "dark");
  const primaryColor = config?.primary_color ?? DEFAULT_PRIMARY_COLOR;
  const voiceActive = voiceStatus === "connected" || voiceStatus === "connecting";
  const stateInfo = getAgentStateInfo(agentState, primaryColor, "Voice active");
  const stateLabel = voiceStatus === "connecting" ? "Connecting..." : stateInfo.label;

  if (error && !config) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-transparent">
        <div className="rounded-lg bg-red-50 p-4 text-red-600 shadow-lg">
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (!config) {
    return (
      <div
        className={`fixed ${POSITION_CLASSES[position] ?? POSITION_CLASSES["bottom-right"]}`}
      >
        <div className="h-14 w-14 animate-pulse rounded-full bg-gray-200" />
      </div>
    );
  }

  return (
    <div
      className={`fixed ${POSITION_CLASSES[position] ?? POSITION_CLASSES["bottom-right"]} z-[9999] font-sans`}
    >
      <div
        className="flex h-[500px] w-full max-w-[360px] sm:w-[360px] flex-col overflow-hidden rounded-2xl shadow-2xl"
        style={{
          backgroundColor: theme.panelBg,
          border: `1px solid ${theme.panelBorder}`,
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ backgroundColor: primaryColor }}
        >
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20">
              <MessageSquare className="h-4 w-4 text-white" />
            </div>
            <span className="font-semibold text-white">{config.name}</span>

            {voiceActive && voiceStatus === "connected" && (
              <div className="flex items-center gap-1.5 rounded-full bg-white/20 px-2 py-0.5">
                <div
                  className="h-2 w-2 rounded-full"
                  style={{
                    backgroundColor: stateInfo.color,
                    boxShadow: `0 0 ${4 + smoothedLevel * 8}px ${stateInfo.color}`,
                    transform: `scale(${1 + smoothedLevel * 0.5})`,
                    transition: "transform 0.1s ease-out, box-shadow 0.1s ease-out",
                  }}
                />
                <span className="text-[10px] font-medium text-white/90">{stateLabel}</span>
              </div>
            )}

            {voiceStatus === "connecting" && (
              <div className="flex items-center gap-1.5 rounded-full bg-white/20 px-2 py-0.5">
                <Loader2 className="h-3 w-3 animate-spin text-white/90" />
                <span className="text-[10px] font-medium text-white/90">Connecting...</span>
              </div>
            )}
          </div>
          <button
            onClick={closeChat}
            className="rounded-full p-1 transition-colors hover:bg-white/20"
          >
            <X className="h-5 w-5 text-white" />
          </button>
        </div>

        {/* Messages */}
        <MessageList
          messages={messages}
          isLoading={isChatLoading}
          theme={theme}
          primaryColor={primaryColor}
          agentName={config.name}
          messagesEndRef={messagesEndRef}
        />

        {/* Input bar */}
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
            disabled={!inputValue.trim() || isChatLoading}
            placeholder={voiceActive ? "Voice active — or type here..." : "Type a message..."}
            isLoading={isChatLoading}
            theme={theme}
            primaryColor={primaryColor}
            trailing={
              <button
                onClick={toggleVoice}
                disabled={voiceStatus === "connecting"}
                className="flex h-10 w-10 items-center justify-center rounded-full transition-all hover:scale-105 disabled:opacity-50"
                style={{ backgroundColor: voiceActive ? "#ef4444" : theme.iconBg }}
                title={voiceActive ? "Stop voice" : "Start voice"}
              >
                {voiceStatus === "connecting" ? (
                  <Loader2 className="h-5 w-5 animate-spin" style={{ color: theme.iconColor }} />
                ) : voiceActive ? (
                  <MicOff className="h-5 w-5 text-white" />
                ) : (
                  <Mic className="h-5 w-5" style={{ color: theme.iconColor }} />
                )}
              </button>
            }
          />
        </div>
      </div>
    </div>
  );
}

export default function BothEmbedPage({ params }: BothEmbedPageProps) {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <BothEmbedPageContent params={params} />
    </Suspense>
  );
}
