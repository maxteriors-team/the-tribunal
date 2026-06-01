import { useCallback, useEffect, useRef, useState } from "react";

import {
  closeAudioAnalysis,
  closeWebRTCResources,
  emptyAudioAnalysisResources,
  emptyWebRTCResources,
  setAudioTracksEnabled,
  stopMediaStream,
  type AudioAnalysisResources,
  type WebRTCResources,
} from "@/lib/embed/session";
import {
  isRealtimeAudioDeltaEvent,
  isRealtimeAudioDoneEvent,
  isRealtimeAudioTranscriptDeltaEvent,
  isRealtimeAudioTranscriptDoneEvent,
} from "@/lib/realtime-events";

import type {
  AgentConfig,
  AgentState,
  ConnectionStatus,
  TokenResponse,
  TranscriptEntry,
} from "./_types";

export type AudioAnalysisMode = "none" | "level" | "level+bars";

export interface UseVoiceSessionOptions {
  publicId: string;
  config: AgentConfig | null;
  /** Called when a finalized user utterance arrives. */
  onUserTranscript?: (text: string) => void;
  /** Called incrementally as the assistant streams text. */
  onAssistantDelta?: (delta: string) => void;
  /** Called when an assistant turn is finalized. */
  onAssistantDone?: (text: string) => void;
  /** Called on terminal session errors. */
  onError?: (message: string) => void;
  /** Called when the session closes (whether by us or remote). */
  onClose?: () => void;
  /** Whether to capture and POST a transcript on session end. */
  saveTranscript?: boolean;
  /** Audio analysis level — `"level"` only updates smoothedLevel, `"level+bars"` also updates frequencies. */
  audioAnalysis?: AudioAnalysisMode;
  /** Number of frequency bars (only used when audioAnalysis === "level+bars"). */
  barCount?: number;
}

export interface UseVoiceSessionResult {
  status: ConnectionStatus;
  agentState: AgentState;
  isMuted: boolean;
  frequencies: number[];
  smoothedLevel: number;
  start: () => Promise<void>;
  end: () => void;
  toggleMute: () => void;
}

/**
 * Encapsulates the OpenAI Realtime WebRTC voice session lifecycle used by the
 * embed pages: token fetch, peer connection, mic capture, audio analysis,
 * transcript routing, tool-call execution, and cleanup.
 */
export function useVoiceSession(options: UseVoiceSessionOptions): UseVoiceSessionResult {
  const {
    publicId,
    config,
    onUserTranscript,
    onAssistantDelta,
    onAssistantDone,
    onError,
    onClose,
    saveTranscript = false,
    audioAnalysis = "none",
    barCount = 24,
  } = options;

  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [frequencies, setFrequencies] = useState<number[]>(() =>
    new Array(barCount).fill(0)
  );
  const [smoothedLevel, setSmoothedLevel] = useState(0);

  const webrtcRef = useRef<WebRTCResources>(emptyWebRTCResources());

  const audioRef = useRef<AudioAnalysisResources>(
    emptyAudioAnalysisResources()
  );

  const abortControllerRef = useRef<AbortController | null>(null);
  const transcriptRef = useRef<TranscriptEntry[]>([]);
  const currentAssistantTextRef = useRef<string>("");
  const sessionIdRef = useRef<string>("");
  const sessionStartTimeRef = useRef<number>(0);

  // Stable callback refs so the start function can stay referentially stable.
  const callbacksRef = useRef({
    onUserTranscript,
    onAssistantDelta,
    onAssistantDone,
    onError,
    onClose,
  });
  useEffect(() => {
    callbacksRef.current = {
      onUserTranscript,
      onAssistantDelta,
      onAssistantDone,
      onError,
      onClose,
    };
  }, [onUserTranscript, onAssistantDelta, onAssistantDone, onError, onClose]);

  // ───── Audio analysis ─────
  const setupAudioAnalysis = useCallback(
    (stream: MediaStream) => {
      if (audioAnalysis === "none") return;
      try {
        const audioContext = new AudioContext();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 128;
        analyser.smoothingTimeConstant = 0.7;

        const source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        audioRef.current = { audioContext, analyser, dataArray, animationFrame: null };

        const wantsBars = audioAnalysis === "level+bars";

        const updateLevel = () => {
          if (audioRef.current.analyser && audioRef.current.dataArray) {
            audioRef.current.analyser.getByteFrequencyData(audioRef.current.dataArray);
            const data = audioRef.current.dataArray;

            if (wantsBars) {
              const bands: number[] = [];
              const bufferLength = data.length;
              for (let i = 0; i < barCount; i++) {
                const startIndex = Math.floor(
                  Math.pow(i / barCount, 1.5) * bufferLength
                );
                const endIndex = Math.floor(
                  Math.pow((i + 1) / barCount, 1.5) * bufferLength
                );
                let sum = 0;
                const count = Math.max(1, endIndex - startIndex);
                for (let j = startIndex; j < endIndex && j < bufferLength; j++) {
                  sum += data[j] ?? 0;
                }
                const avg = sum / count / 255;
                bands.push(Math.min(1, avg * 1.8));
              }
              setFrequencies(bands);
            }

            const voiceRange = Array.from(data).slice(0, 16);
            const avg =
              voiceRange.reduce((a, b) => a + b, 0) / voiceRange.length;
            const normalizedLevel = Math.min(avg / 128, 1);

            setSmoothedLevel((prev) => {
              if (normalizedLevel > prev) {
                return prev + (normalizedLevel - prev) * 0.3;
              }
              return prev + (normalizedLevel - prev) * 0.1;
            });
          }
          audioRef.current.animationFrame = requestAnimationFrame(updateLevel);
        };

        updateLevel();
      } catch {
        // Audio analysis is not critical to the call.
      }
    },
    [audioAnalysis, barCount]
  );

  const cleanupAudioAnalysis = useCallback(() => {
    closeAudioAnalysis(audioRef.current);
    audioRef.current = emptyAudioAnalysisResources();
    setFrequencies(new Array(barCount).fill(0));
    setSmoothedLevel(0);
  }, [barCount]);

  // ───── Cleanup ─────
  const cleanup = useCallback(() => {
    cleanupAudioAnalysis();
    closeWebRTCResources(webrtcRef.current);
    webrtcRef.current = emptyWebRTCResources();
    setAgentState("idle");
  }, [cleanupAudioAnalysis]);

  // ───── Persist transcript (best-effort) ─────
  const flushTranscript = useCallback(async () => {
    if (!saveTranscript) return;
    if (currentAssistantTextRef.current.trim()) {
      transcriptRef.current.push({
        role: "assistant",
        content: currentAssistantTextRef.current.trim(),
      });
      currentAssistantTextRef.current = "";
    }

    if (transcriptRef.current.length === 0 || !sessionIdRef.current) {
      return;
    }

    const transcriptText = transcriptRef.current
      .map(
        (entry) =>
          `[${entry.role === "user" ? "User" : "Assistant"}]: ${entry.content}`
      )
      .join("\n\n");

    const durationSeconds = sessionStartTimeRef.current
      ? Math.floor((Date.now() - sessionStartTimeRef.current) / 1000)
      : 0;

    try {
      await fetch(`/api/v1/p/embed/${publicId}/transcript`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: window.location.origin,
        },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          transcript: transcriptText,
          duration_seconds: durationSeconds,
        }),
      });
    } catch {
      // Best-effort.
    }

    transcriptRef.current = [];
    sessionIdRef.current = "";
    sessionStartTimeRef.current = 0;
  }, [publicId, saveTranscript]);

  // ───── End session ─────
  const end = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    void flushTranscript();
    cleanup();
    setStatus("idle");
    callbacksRef.current.onClose?.();
  }, [cleanup, flushTranscript]);

  // ───── Cleanup on unmount ─────
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  // ───── Start session ─────
  const start = useCallback(async () => {
    if (!config) return;

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    transcriptRef.current = [];
    currentAssistantTextRef.current = "";
    sessionIdRef.current = crypto.randomUUID();
    sessionStartTimeRef.current = Date.now();

    setStatus("connecting");
    setAgentState("idle");

    try {
      const tokenRes = await fetch(`/api/v1/p/embed/${publicId}/token`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: window.location.origin,
        },
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) return;
      if (!tokenRes.ok) {
        const errData = await tokenRes.json();
        throw new Error((errData.detail as string) ?? "Failed to get token");
      }

      const tokenData: TokenResponse = await tokenRes.json();
      const ephemeralKey = tokenData.client_secret.value;
      if (abortController.signal.aborted) return;

      const pc = new RTCPeerConnection();
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioTrack = micStream.getAudioTracks()[0];
      if (audioTrack) pc.addTrack(audioTrack);

      setupAudioAnalysis(micStream);

      const dataChannel = pc.createDataChannel("oai-events");

      const audioElement = document.createElement("audio");
      audioElement.autoplay = true;
      pc.ontrack = (event) => {
        audioElement.srcObject = event.streams[0] ?? null;
      };

      webrtcRef.current = {
        peerConnection: pc,
        dataChannel,
        audioStream: micStream,
        audioElement,
      };

      if (abortController.signal.aborted) {
        stopMediaStream(micStream);
        pc.close();
        return;
      }

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      if (abortController.signal.aborted) {
        stopMediaStream(micStream);
        pc.close();
        return;
      }

      const response = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        body: offer.sdp,
        headers: {
          "Content-Type": "application/sdp",
          Authorization: `Bearer ${ephemeralKey}`,
        },
        signal: abortController.signal,
      });

      if (abortController.signal.aborted) {
        stopMediaStream(micStream);
        pc.close();
        return;
      }

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`OpenAI API error (${response.status}): ${errorText}`);
      }

      const answerSdp = await response.text();
      if (abortController.signal.aborted) {
        stopMediaStream(micStream);
        pc.close();
        return;
      }

      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      dataChannel.onopen = () => {
        if (abortController.signal.aborted) return;
        setStatus("connected");
        setAgentState("listening");

        if (tokenData.agent.initial_greeting) {
          dataChannel.send(
            JSON.stringify({
              type: "response.create",
              response: {
                output_modalities: ["audio"],
                instructions: `Start the conversation by saying exactly this (do not add anything else): "${tokenData.agent.initial_greeting}"`,
              },
            })
          );
        }
      };

      const executeToolCall = async (
        callId: string,
        toolName: string,
        args: Record<string, unknown>
      ) => {
        try {
          const toolResponse = await fetch(
            `/api/v1/p/embed/${publicId}/tool-call`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Origin: window.location.origin,
              },
              body: JSON.stringify({ tool_name: toolName, arguments: args }),
            }
          );
          const result = (await toolResponse.json()) as Record<string, unknown>;

          if (dataChannel.readyState === "open") {
            dataChannel.send(
              JSON.stringify({
                type: "conversation.item.create",
                item: {
                  type: "function_call_output",
                  call_id: callId,
                  output: JSON.stringify(result),
                },
              })
            );
            dataChannel.send(
              JSON.stringify({
                type: "response.create",
                response: { output_modalities: ["audio"] },
              })
            );
          }

          if (result.action === "end_call") {
            setTimeout(() => {
              end();
            }, 3000);
          }
        } catch (err) {
          if (dataChannel.readyState === "open") {
            dataChannel.send(
              JSON.stringify({
                type: "conversation.item.create",
                item: {
                  type: "function_call_output",
                  call_id: callId,
                  output: JSON.stringify({
                    success: false,
                    error:
                      err instanceof Error
                        ? err.message
                        : "Tool execution failed",
                  }),
                },
              })
            );
            dataChannel.send(
              JSON.stringify({
                type: "response.create",
                response: { output_modalities: ["audio"] },
              })
            );
          }
        }
      };

      dataChannel.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "input_audio_buffer.speech_started") {
            setAgentState("listening");
          } else if (data.type === "input_audio_buffer.speech_stopped") {
            setAgentState("thinking");
          } else if (isRealtimeAudioDeltaEvent(data.type)) {
            setAgentState("speaking");
          } else if (isRealtimeAudioDoneEvent(data.type)) {
            setAgentState("listening");
          } else if (data.type === "response.done") {
            setAgentState("listening");
          } else if (data.type === "response.function_call_arguments.done") {
            const callId = data.call_id as string;
            const toolName = data.name as string;
            const argsJson = data.arguments;

            let args: Record<string, unknown>;
            try {
              args =
                typeof argsJson === "string"
                  ? (JSON.parse(argsJson) as Record<string, unknown>)
                  : ((argsJson as Record<string, unknown>) ?? {});
            } catch {
              const errorOutput = {
                type: "conversation.item.create",
                item: {
                  type: "function_call_output",
                  call_id: callId,
                  output: JSON.stringify({
                    success: false,
                    error: "Invalid JSON arguments",
                  }),
                },
              };
              dataChannel.send(JSON.stringify(errorOutput));
              dataChannel.send(
                JSON.stringify({
                  type: "response.create",
                  response: { output_modalities: ["audio"] },
                })
              );
              return;
            }

            void executeToolCall(callId, toolName, args);
          } else if (data.type === "error") {
            callbacksRef.current.onError?.(
              data.error?.message ?? "Unknown error"
            );
          }

          if (
            data.type === "conversation.item.input_audio_transcription.completed"
          ) {
            const userText = data.transcript as string;
            const trimmed = userText?.trim();
            if (trimmed) {
              if (saveTranscript) {
                transcriptRef.current.push({ role: "user", content: trimmed });
              }
              callbacksRef.current.onUserTranscript?.(trimmed);
            }
          } else if (isRealtimeAudioTranscriptDeltaEvent(data.type)) {
            const delta = data.delta as string;
            if (delta) {
              currentAssistantTextRef.current += delta;
              callbacksRef.current.onAssistantDelta?.(delta);
            }
          } else if (isRealtimeAudioTranscriptDoneEvent(data.type)) {
            const finalText = currentAssistantTextRef.current.trim();
            if (finalText) {
              if (saveTranscript) {
                transcriptRef.current.push({
                  role: "assistant",
                  content: finalText,
                });
              }
              callbacksRef.current.onAssistantDone?.(finalText);
            }
            currentAssistantTextRef.current = "";
          }
        } catch {
          // Ignore parse errors.
        }
      };

      dataChannel.onerror = () => {
        callbacksRef.current.onError?.("Connection error");
        setStatus("error");
      };

      dataChannel.onclose = () => {
        setStatus("idle");
        callbacksRef.current.onClose?.();
      };

      pc.onconnectionstatechange = () => {
        if (
          pc.connectionState === "disconnected" ||
          pc.connectionState === "failed"
        ) {
          cleanup();
          setStatus("idle");
          callbacksRef.current.onClose?.();
        }
      };
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      callbacksRef.current.onError?.(
        err instanceof Error ? err.message : "Failed to start session"
      );
      setStatus("error");
      cleanup();
    }
  }, [config, publicId, cleanup, setupAudioAnalysis, end, saveTranscript]);

  const toggleMute = useCallback(() => {
    const { audioStream } = webrtcRef.current;
    if (audioStream) {
      setIsMuted((prev) => {
        const next = !prev;
        setAudioTracksEnabled(audioStream, !next);
        return next;
      });
    }
  }, []);

  return {
    status,
    agentState,
    isMuted,
    frequencies,
    smoothedLevel,
    start,
    end,
    toggleMute,
  };
}
