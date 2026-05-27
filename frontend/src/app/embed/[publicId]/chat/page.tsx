"use client";

import { Send, X, MessageSquare, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, useCallback, useRef, use, Suspense } from "react";

interface AgentConfig {
  public_id: string;
  name: string;
  greeting_message: string | null;
  button_text: string;
  theme: "light" | "dark" | "auto";
  position: string;
  primary_color: string;
  language: string;
  channel_mode: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatEmbedPageProps {
  params: Promise<{ publicId: string }>;
}

function ChatEmbedPageContent({ params }: ChatEmbedPageProps) {
  const { publicId } = use(params);
  const searchParams = useSearchParams();
  const themeParam = searchParams.get("theme");
  const theme = themeParam === "light" || themeParam === "dark" ? themeParam : "auto";
  const position = searchParams.get("position") ?? "bottom-right";
  const autostart = searchParams.get("autostart") === "true";

  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(autostart);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [systemTheme, setSystemTheme] = useState<"light" | "dark">(() => {
    if (typeof window === "undefined") return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    if (theme === "auto") {
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = (e: MediaQueryListEvent) =>
        setSystemTheme(e.matches ? "dark" : "light");
      mediaQuery.addEventListener("change", handler);
      return () => mediaQuery.removeEventListener("change", handler);
    }

    return undefined;
  }, [theme]);

  // Notify parent window of state
  useEffect(() => {
    if (window.parent !== window) {
      window.parent.postMessage(
        { type: "ai-agent:state", state: isLoading ? "thinking" : "idle" },
        "*"
      );
    }
  }, [isLoading]);

  // Fetch agent config
  useEffect(() => {
    async function fetchConfig() {
      try {
        const res = await fetch(`/api/v1/p/embed/${publicId}/config`, {
          headers: { Origin: window.location.origin },
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error((data.detail as string) ?? "Failed to load agent");
        }
        const data = await res.json();
        setConfig(data);

        // Add greeting message if available
        if (data.greeting_message) {
          setMessages([
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: data.greeting_message,
              timestamp: new Date(),
            },
          ]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load agent");
      }
    }
    if (publicId) {
      void fetchConfig();
    }
  }, [publicId]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Listen for start message from widget
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === "ai-agent:start" && !isOpen && config) {
        setIsOpen(true);
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [isOpen, config]);

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

      const res = await fetch(`/api/v1/p/embed/${publicId}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: window.location.origin,
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

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.response,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setIsLoading(false);
    }
  }, [inputValue, isLoading, config, messages, publicId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  };

  const closeChat = () => {
    setIsOpen(false);
    if (window.parent !== window) {
      window.parent.postMessage({ type: "ai-agent:close" }, "*");
    }
  };

  const positionClasses: Record<string, string> = {
    "bottom-right": "bottom-5 right-5",
    "bottom-left": "bottom-5 left-5",
    "top-right": "top-5 right-5",
    "top-left": "top-5 left-5",
  };

  const isDark = (theme === "auto" ? systemTheme : theme) === "dark";
  const primaryColor = config?.primary_color ?? "#6366f1";

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
      <div className={`fixed ${positionClasses[position] ?? positionClasses["bottom-right"]}`}>
        <div className="h-14 w-14 animate-pulse rounded-full bg-gray-200" />
      </div>
    );
  }

  return (
    <div
      className={`fixed ${positionClasses[position] ?? positionClasses["bottom-right"]} z-[9999] font-sans`}
    >
      {isOpen ? (
        <div
          className="flex h-[500px] w-full max-w-[360px] sm:w-[360px] flex-col overflow-hidden rounded-2xl shadow-2xl"
          style={{
            backgroundColor: isDark ? "#1f2937" : "#ffffff",
            border: isDark ? "1px solid #374151" : "1px solid #e5e7eb",
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
            </div>
            <button
              onClick={closeChat}
              className="rounded-full p-1 transition-colors hover:bg-white/20"
            >
              <X className="h-5 w-5 text-white" />
            </button>
          </div>

          {/* Messages */}
          <div
            className="flex-1 overflow-y-auto p-4"
            style={{ backgroundColor: isDark ? "#111827" : "#f9fafb" }}
          >
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <p
                  className="text-center text-sm"
                  style={{ color: isDark ? "#9ca3af" : "#6b7280" }}
                >
                  Start a conversation with {config.name}
                </p>
              </div>
            )}

            {messages.map((message) => (
              <div
                key={message.id}
                className={`mb-3 flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-2 ${
                    message.role === "user"
                      ? "rounded-br-md"
                      : "rounded-bl-md"
                  }`}
                  style={{
                    backgroundColor:
                      message.role === "user"
                        ? primaryColor
                        : isDark
                          ? "#374151"
                          : "#ffffff",
                    color:
                      message.role === "user"
                        ? "#ffffff"
                        : isDark
                          ? "#f3f4f6"
                          : "#1f2937",
                    boxShadow:
                      message.role === "assistant"
                        ? isDark
                          ? "0 1px 2px rgba(0,0,0,0.3)"
                          : "0 1px 2px rgba(0,0,0,0.1)"
                        : "none",
                  }}
                >
                  <p className="whitespace-pre-wrap text-sm">{message.content}</p>
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="mb-3 flex justify-start">
                <div
                  className="flex items-center gap-2 rounded-2xl rounded-bl-md px-4 py-2"
                  style={{
                    backgroundColor: isDark ? "#374151" : "#ffffff",
                    boxShadow: isDark
                      ? "0 1px 2px rgba(0,0,0,0.3)"
                      : "0 1px 2px rgba(0,0,0,0.1)",
                  }}
                >
                  <div className="flex gap-1">
                    <div
                      className="h-2 w-2 animate-bounce rounded-full"
                      style={{ backgroundColor: primaryColor, animationDelay: "0ms" }}
                    />
                    <div
                      className="h-2 w-2 animate-bounce rounded-full"
                      style={{ backgroundColor: primaryColor, animationDelay: "150ms" }}
                    />
                    <div
                      className="h-2 w-2 animate-bounce rounded-full"
                      style={{ backgroundColor: primaryColor, animationDelay: "300ms" }}
                    />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div
            className="border-t p-3"
            style={{
              backgroundColor: isDark ? "#1f2937" : "#ffffff",
              borderColor: isDark ? "#374151" : "#e5e7eb",
            }}
          >
            {error && (
              <p className="mb-2 text-xs text-red-500">{error}</p>
            )}
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a message..."
                disabled={isLoading}
                className="flex-1 rounded-full border px-4 py-2 text-sm outline-none transition-all focus:ring-2"
                style={{
                  backgroundColor: isDark ? "#374151" : "#f3f4f6",
                  borderColor: isDark ? "#4b5563" : "#e5e7eb",
                  color: isDark ? "#f3f4f6" : "#1f2937",
                }}
              />
              <button
                onClick={() => void sendMessage()}
                disabled={!inputValue.trim() || isLoading}
                className="flex h-10 w-10 items-center justify-center rounded-full transition-all hover:scale-105 disabled:opacity-50"
                style={{ backgroundColor: primaryColor }}
              >
                {isLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-white" />
                ) : (
                  <Send className="h-5 w-5 text-white" />
                )}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setIsOpen(true)}
          className="group flex items-center gap-3 rounded-full py-3 pl-4 pr-6 shadow-lg transition-all duration-300 hover:scale-105 hover:shadow-xl"
          style={{
            backgroundColor: primaryColor,
            color: "#ffffff",
            boxShadow: `0 8px 32px ${primaryColor}50`,
          }}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20">
            <MessageSquare className="h-5 w-5" />
          </div>
          <span className="text-sm font-semibold">{config.button_text}</span>
        </button>
      )}
    </div>
  );
}

export default function ChatEmbedPage({ params }: ChatEmbedPageProps) {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ChatEmbedPageContent params={params} />
    </Suspense>
  );
}
