"use client";

import { Mic, MicOff, X, Phone } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, use, Suspense } from "react";

import {
  postToParent,
  subscribeToEmbedMessages,
} from "@/lib/embed/messaging";

import {
  DEFAULT_PRIMARY_COLOR,
  getAgentStateInfo,
  getEmbedTheme,
} from "./_theme";
import { POSITION_CLASSES_LG, type ThemeOption } from "./_types";
import { useAgentConfig, useResolvedTheme } from "./_use-agent-config";
import { useVoiceSession } from "./_use-voice-session";

const BAR_COUNT = 24;

interface EmbedPageProps {
  params: Promise<{ publicId: string }>;
}

function EmbedPageContent({ params }: EmbedPageProps) {
  const { publicId } = use(params);
  const searchParams = useSearchParams();
  const themeParam = (searchParams.get("theme") as ThemeOption) ?? "auto";
  const position = searchParams.get("position") ?? "bottom-right";
  const autostart = searchParams.get("autostart") === "true";

  const resolvedTheme = useResolvedTheme(themeParam);
  const { config, error: configError, setError } = useAgentConfig(publicId);

  const [isExpanded, setIsExpanded] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const autostartTriggeredRef = useRef(false);

  const handleClose = useCallback(() => {
    setIsExpanded(false);
    postToParent({ type: "ai-agent:close" });
  }, []);

  const {
    status,
    agentState,
    isMuted,
    frequencies,
    smoothedLevel,
    start,
    end,
    toggleMute,
  } = useVoiceSession({
    publicId,
    config,
    saveTranscript: true,
    audioAnalysis: "level+bars",
    barCount: BAR_COUNT,
    onError: setSessionError,
    onClose: () => setIsExpanded(false),
  });

  const error = configError ?? sessionError;

  // Notify parent of agent state
  useEffect(() => {
    postToParent({ type: "ai-agent:state", state: agentState });
  }, [agentState]);

  // Notify parent of audio level
  useEffect(() => {
    if (smoothedLevel > 0.05) {
      postToParent({ type: "ai-agent:audio-level", level: smoothedLevel });
    }
  }, [smoothedLevel]);

  const handleStart = useCallback(async () => {
    setSessionError(null);
    setError(null);
    setIsExpanded(true);
    await start();
  }, [start, setError]);

  const handleEnd = useCallback(() => {
    end();
    handleClose();
  }, [end, handleClose]);

  // Auto-start
  useEffect(() => {
    if (autostart && config && !autostartTriggeredRef.current) {
      autostartTriggeredRef.current = true;
      void handleStart();
    }
  }, [autostart, config, handleStart]);

  // Listen for start message from widget
  useEffect(() => {
    return subscribeToEmbedMessages((message) => {
      if (message.type === "ai-agent:start" && status === "idle" && config) {
        void handleStart();
      }
    });
  }, [status, config, handleStart]);

  const theme = getEmbedTheme(resolvedTheme === "dark");
  const primaryColor = config?.primary_color ?? DEFAULT_PRIMARY_COLOR;
  const stateInfo = getAgentStateInfo(agentState, primaryColor);

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
        className={`fixed ${POSITION_CLASSES_LG[position] ?? POSITION_CLASSES_LG["bottom-right"]}`}
      >
        <div className="h-14 w-14 animate-pulse rounded-full bg-gray-200" />
      </div>
    );
  }

  return (
    <div
      className={`fixed ${POSITION_CLASSES_LG[position] ?? POSITION_CLASSES_LG["bottom-right"]} z-[9999] font-sans`}
    >
      {isExpanded ? (
        <div
          className="relative flex flex-col items-center gap-3 rounded-3xl p-6 transition-all duration-500"
          style={{
            backgroundColor: theme.panelOverlayBg,
            backdropFilter: "blur(20px)",
            boxShadow: `0 0 ${40 + smoothedLevel * 60}px ${smoothedLevel * 20}px ${stateInfo.color}40`,
          }}
        >
          {/* Circular Audio Visualizer */}
          <div className="relative flex h-32 w-32 items-center justify-center">
            <div
              className="absolute inset-0 rounded-full"
              style={{
                background: `radial-gradient(circle, ${stateInfo.color}20 0%, transparent 70%)`,
                transform: `scale(${1.2 + smoothedLevel * 0.5})`,
                transition: "transform 0.15s ease-out",
              }}
            />

            <div className="absolute inset-0">
              {frequencies.map((level, i) => {
                const angle = (i / BAR_COUNT) * 360;
                const barHeight = 8 + level * 32;
                const opacity = 0.3 + level * 0.7;
                return (
                  <div
                    key={i}
                    className="absolute left-1/2 top-1/2 origin-bottom"
                    style={{
                      width: "3px",
                      height: `${barHeight}px`,
                      backgroundColor: stateInfo.color,
                      opacity,
                      transform: `translate(-50%, -100%) rotate(${angle}deg) translateY(-28px)`,
                      borderRadius: "2px",
                      transition: "height 0.05s ease-out, opacity 0.05s ease-out",
                    }}
                  />
                );
              })}
            </div>

            <div
              className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full"
              style={{
                background: `linear-gradient(135deg, ${stateInfo.color} 0%, ${primaryColor} 100%)`,
                boxShadow: `0 0 ${20 + smoothedLevel * 30}px ${stateInfo.color}80`,
                transform: `scale(${1 + smoothedLevel * 0.15})`,
                transition: "transform 0.1s ease-out, box-shadow 0.1s ease-out",
              }}
            >
              <div
                className="absolute inset-2 rounded-full"
                style={{
                  background: `radial-gradient(circle, rgba(255,255,255,${0.3 + smoothedLevel * 0.4}) 0%, transparent 70%)`,
                }}
              />
              {status === "connecting" ? (
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <Phone className="h-6 w-6 text-white" fill="white" />
              )}
            </div>

            <div
              className="absolute inset-0 rounded-full border-2"
              style={{
                borderColor: stateInfo.color,
                opacity: 0.5 + smoothedLevel * 0.5,
                transform: `scale(${1.1 + smoothedLevel * 0.1})`,
                transition: "transform 0.15s ease-out, opacity 0.15s ease-out",
              }}
            />
          </div>

          {/* Agent name and status */}
          <div className="text-center">
            <p className="text-sm font-semibold" style={{ color: theme.text }}>
              {config.name}
            </p>
            <p className="text-xs font-medium" style={{ color: stateInfo.color }}>
              {status === "connecting" ? "Connecting..." : stateInfo.label}
            </p>
          </div>

          {/* Control buttons */}
          <div className="flex items-center gap-2">
            {status === "connected" && (
              <button
                onClick={toggleMute}
                className="rounded-full p-3 transition-all duration-200 hover:scale-105"
                style={{
                  backgroundColor: isMuted
                    ? "#ef4444"
                    : theme.isDark
                      ? "rgba(255,255,255,0.1)"
                      : "rgba(0,0,0,0.05)",
                  color: isMuted ? "#ffffff" : theme.iconColor,
                }}
              >
                {isMuted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
              </button>
            )}

            <button
              onClick={handleEnd}
              className="rounded-full bg-red-500 p-3 text-white transition-all duration-200 hover:scale-105 hover:bg-red-600"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {error && <p className="max-w-[200px] text-center text-xs text-red-500">{error}</p>}
        </div>
      ) : autostart ? (
        <div className="flex flex-col items-center justify-center gap-3 p-4">
          <div className="relative flex h-16 w-16 items-center justify-center">
            <div
              className="absolute inset-0 animate-spin rounded-full"
              style={{
                background: `conic-gradient(from 0deg, ${primaryColor} 0deg, transparent 120deg)`,
                animationDuration: "1s",
              }}
            />
            <div className="absolute inset-1 rounded-full bg-[#212121]" />
            <div
              className="absolute inset-3 rounded-full"
              style={{ backgroundColor: primaryColor, opacity: 0.3 }}
            />
          </div>
          <p className="text-sm font-medium text-gray-300">
            {status === "connecting" ? "Connecting..." : "Starting..."}
          </p>
          {error && <p className="max-w-[200px] text-center text-xs text-red-500">{error}</p>}
        </div>
      ) : (
        <button
          onClick={() => void handleStart()}
          className="group relative flex items-center gap-3 overflow-hidden rounded-full py-3 pl-4 pr-6 shadow-lg transition-all duration-300 hover:scale-105 hover:shadow-xl active:scale-95"
          style={{
            backgroundColor: primaryColor,
            color: "#ffffff",
            boxShadow: `0 8px 32px ${primaryColor}50`,
          }}
        >
          <div
            className="absolute inset-0 opacity-30"
            style={{
              background:
                "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%)",
              animation: "shimmer 2s infinite",
            }}
          />

          <div className="relative h-10 w-10">
            <div
              className="absolute inset-0 animate-spin rounded-full"
              style={{
                background:
                  "conic-gradient(from 0deg, rgba(255,255,255,0.8) 0deg, rgba(255,255,255,0.2) 90deg, rgba(255,255,255,0.8) 180deg, rgba(255,255,255,0.2) 270deg, rgba(255,255,255,0.8) 360deg)",
                animationDuration: "3s",
              }}
            />
            <div
              className="absolute inset-1 rounded-full"
              style={{ backgroundColor: primaryColor }}
            />
            <div className="absolute inset-2 rounded-full bg-white/50 transition-all duration-300 group-hover:bg-white/70" />
            <div
              className="absolute inset-0 animate-ping rounded-full opacity-20"
              style={{ backgroundColor: "white", animationDuration: "2s" }}
            />
          </div>

          <span className="relative z-10 text-sm font-semibold">{config.button_text}</span>
        </button>
      )}
    </div>
  );
}

export default function EmbedPage({ params }: EmbedPageProps) {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <EmbedPageContent params={params} />
    </Suspense>
  );
}
