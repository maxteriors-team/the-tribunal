"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Play, Square, Loader2 } from "lucide-react";

import { agentsApi } from "@/lib/api/agents";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { PageEmptyState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatTime } from "@/lib/utils/date";
import { Slider } from "@/components/ui/slider";
import { Separator } from "@/components/ui/separator";

type TranscriptItem = {
  id: string;
  speaker: "user" | "assistant" | "system";
  text: string;
  timestamp: Date;
};

type ConnectionStatus = "idle" | "connecting" | "connected";

// OpenAI Realtime voices
const VOICES = [
  { id: "marin", name: "Marin" },
  { id: "cedar", name: "Cedar" },
  { id: "alloy", name: "Alloy" },
  { id: "ash", name: "Ash" },
  { id: "ballad", name: "Ballad" },
  { id: "coral", name: "Coral" },
  { id: "echo", name: "Echo" },
  { id: "sage", name: "Sage" },
  { id: "shimmer", name: "Shimmer" },
];

// Audio visualizer component using Web Audio API for real-time frequency analysis
/* eslint-disable react-hooks/set-state-in-effect -- Intentional pattern for animation frames */
function AudioVisualizer({
  stream,
  isActive,
  barCount = 12,
}: {
  stream: MediaStream | null;
  isActive: boolean;
  barCount?: number;
}) {
  const [frequencies, setFrequencies] = useState<number[]>(() => new Array(barCount).fill(0));
  const audioRef = useRef<{
    audioContext: AudioContext | null;
    analyser: AnalyserNode | null;
  }>({ audioContext: null, analyser: null });
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (!stream || !isActive) {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }
      if (audioRef.current.audioContext?.state !== "closed") {
        void audioRef.current.audioContext?.close();
        audioRef.current = { audioContext: null, analyser: null };
      }
      setFrequencies(new Array(barCount).fill(0));
      return;
    }

    const audioContext = new AudioContext();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.7;

    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    audioRef.current = { audioContext, analyser };

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const updateFrequencies = () => {
      if (!audioRef.current.analyser) return;
      audioRef.current.analyser.getByteFrequencyData(dataArray);

      const bands: number[] = [];
      for (let i = 0; i < barCount; i++) {
        const startIndex = Math.floor(Math.pow(i / barCount, 1.5) * bufferLength);
        const endIndex = Math.floor(Math.pow((i + 1) / barCount, 1.5) * bufferLength);
        let sum = 0;
        const count = Math.max(1, endIndex - startIndex);
        for (let j = startIndex; j < endIndex && j < bufferLength; j++) {
          sum += dataArray[j] ?? 0;
        }
        bands.push(Math.min(1, (sum / count / 255) * 1.5));
      }
      setFrequencies(bands);
      animationRef.current = requestAnimationFrame(updateFrequencies);
    };

    updateFrequencies();

    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      if (audioContext.state !== "closed") void audioContext.close();
    };
  }, [stream, isActive, barCount]);

  return (
    <div className="flex h-6 items-center gap-0.5">
      {frequencies.map((freq, i) => {
        const height = isActive ? Math.max(4, freq * 20) : 4;
        const opacity = isActive ? 0.4 + freq * 0.6 : 0.3;
        return (
          <div
            key={i}
            className="w-0.5 rounded-full bg-foreground transition-all duration-75"
            style={{ height: `${height}px`, opacity }}
          />
        );
      })}
    </div>
  );
}
/* eslint-enable react-hooks/set-state-in-effect */

export default function VoiceTestPage() {
  const workspaceId = useWorkspaceId();
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [callDuration, setCallDuration] = useState(0);
  const [audioStream, setAudioStream] = useState<MediaStream | null>(null);

  // Settings state
  const [voice, setVoice] = useState("marin");
  const [threshold, setThreshold] = useState(0.5);
  const [silenceDuration, setSilenceDuration] = useState(500);
  const [editedSystemPrompt, setEditedSystemPrompt] = useState("");

  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const callTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);

  // Fetch agents
  const { data: agentsData } = useQuery({
    queryKey: ["agents", workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return agentsApi.list(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const voiceAgents = agentsData?.items.filter(
    (a) => a.channel_mode === "voice" || a.channel_mode === "both"
  );

  const selectedAgent = voiceAgents?.find((a) => a.id === selectedAgentId);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // Update settings when agent changes
  useEffect(() => {
    if (selectedAgent) {
      setEditedSystemPrompt(selectedAgent.system_prompt ?? "");
      setVoice(selectedAgent.voice_id ?? "marin");
    }
  }, [selectedAgent]);

  const addTranscript = useCallback(
    (speaker: "user" | "assistant" | "system", text: string) => {
      setTranscript((prev) => [
        ...prev,
        { id: crypto.randomUUID(), speaker, text, timestamp: new Date() },
      ]);
    },
    []
  );

  const cleanup = useCallback(() => {
    if (callTimerRef.current) {
      clearInterval(callTimerRef.current);
      callTimerRef.current = null;
    }
    if (dcRef.current) {
      try { dcRef.current.close(); } catch {}
      dcRef.current = null;
    }
    if (pcRef.current) {
      try { pcRef.current.close(); } catch {}
      pcRef.current = null;
    }
    if (audioStream) {
      audioStream.getTracks().forEach((t) => t.stop());
    }
    setAudioStream(null);
  }, [audioStream]);

  useEffect(() => {
    return () => cleanup();
  }, [cleanup]);

  const handleConnect = async () => {
    if (connectionStatus === "connected") {
      cleanup();
      setConnectionStatus("idle");
      setCallDuration(0);
      addTranscript("system", "Session ended");
      return;
    }

    if (!selectedAgentId || !selectedAgent) {
      toast.error("Please select an agent first");
      return;
    }

    setConnectionStatus("connecting");
    addTranscript("system", `Connecting to ${selectedAgent.name}...`);

    try {
      // Use relative URLs so calls go through the Next.js proxy and the
      // httpOnly auth cookie is sent same-origin. JS cannot read the cookie,
      // so an XSS payload cannot lift the access token.
      const apiBase = "";

      // Get ephemeral token
      const tokenResponse = await fetch(
        `${apiBase}/api/v1/realtime/token/${selectedAgentId}?workspace_id=${workspaceId}`,
        { credentials: "include" }
      );

      if (!tokenResponse.ok) {
        throw new Error(`Failed to get token: ${await tokenResponse.text()}`);
      }

      const tokenData = await tokenResponse.json();
      const ephemeralKey = tokenData.client_secret?.value;

      if (!ephemeralKey) {
        throw new Error("No ephemeral key received");
      }

      // Set up WebRTC
      const pc = new RTCPeerConnection();
      pcRef.current = pc;

      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setAudioStream(micStream);
      const audioTrack = micStream.getAudioTracks()[0];
      if (audioTrack) pc.addTrack(audioTrack);

      const dc = pc.createDataChannel("oai-events");
      dcRef.current = dc;

      // Audio playback
      const audioEl = document.createElement("audio");
      audioEl.autoplay = true;
      pc.ontrack = (e) => {
        audioEl.srcObject = e.streams[0] ?? null;
      };

      // Create and send offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        body: offer.sdp,
        headers: {
          "Content-Type": "application/sdp",
          Authorization: `Bearer ${ephemeralKey}`,
        },
      });

      if (!response.ok) {
        throw new Error(`OpenAI API error: ${await response.text()}`);
      }

      await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });

      dc.onopen = () => {
        setConnectionStatus("connected");
        setCallDuration(0);
        callTimerRef.current = setInterval(() => setCallDuration((p) => p + 1), 1000);

        // Configure session
        dc.send(JSON.stringify({
          type: "session.update",
          session: {
            instructions: editedSystemPrompt || "You are a helpful assistant.",
            voice: voice,
            input_audio_transcription: { model: "whisper-1" },
            turn_detection: {
              type: "server_vad",
              threshold: threshold,
              silence_duration_ms: silenceDuration,
              prefix_padding_ms: 300,
            },
            tools: tokenData.tools ?? [],
            tool_choice: tokenData.tools?.length > 0 ? "auto" : "none",
          },
        }));

        // Initial greeting
        if (tokenData.agent?.initial_greeting) {
          dc.send(JSON.stringify({
            type: "response.create",
            response: {
              instructions: `Start by saying: "${tokenData.agent.initial_greeting}"`,
            },
          }));
        }
      };

      dc.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "conversation.item.input_audio_transcription.completed") {
            addTranscript("user", data.transcript);
          } else if (data.type === "response.audio_transcript.done") {
            addTranscript("assistant", data.transcript);
          } else if (data.type === "response.function_call_arguments.done") {
            const { call_id, name, arguments: argsJson } = data;
            try {
              const toolResponse = await fetch(`${apiBase}/api/v1/tools/execute`, {
                method: "POST",
                credentials: "include",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify({
                  tool_name: name,
                  arguments: JSON.parse(argsJson ?? "{}"),
                  agent_id: selectedAgentId,
                }),
              });
              const toolResult = await toolResponse.json();
              dc.send(JSON.stringify({
                type: "conversation.item.create",
                item: { type: "function_call_output", call_id, output: JSON.stringify(toolResult) },
              }));
              dc.send(JSON.stringify({ type: "response.create" }));

              if (toolResult.action === "end_call") {
                setTimeout(() => {
                  cleanup();
                  setConnectionStatus("idle");
                  setCallDuration(0);
                }, 3000);
              }
            } catch (e) {
              dc.send(JSON.stringify({
                type: "conversation.item.create",
                item: { type: "function_call_output", call_id, output: JSON.stringify({ error: String(e) }) },
              }));
              dc.send(JSON.stringify({ type: "response.create" }));
            }
          } else if (data.type === "error") {
            addTranscript("system", `Error: ${data.error?.message ?? "Unknown"}`);
          }
        } catch {}
      };

      dc.onclose = () => {
        setConnectionStatus("idle");
        cleanup();
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "disconnected" || pc.connectionState === "failed") {
          cleanup();
          setConnectionStatus("idle");
          setCallDuration(0);
        }
      };
    } catch (error) {
      const err = error as Error;
      addTranscript("system", `Error: ${err.message}`);
      cleanup();
      setConnectionStatus("idle");
      toast.error(err.name === "NotAllowedError" ? "Microphone access denied" : err.message);
    }
  };

  const formatDuration = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

  return (
    <div className="-m-4 flex h-[calc(100vh-3.5rem)] md:-m-6 lg:-m-8">
      {/* Left - Transcript */}
      <div className="relative flex min-h-0 flex-1 flex-col">
        <ScrollArea className="min-h-0 flex-1 p-4 pb-20">
          {transcript.length === 0 ? (
            <PageEmptyState
              className="h-full"
              title="Start a session to see the conversation"
            />
          ) : (
            <div className="space-y-4">
              {transcript.map((item) => (
                <div key={item.id}>
                  {item.speaker === "system" ? (
                    <div className="flex justify-center">
                      <div className="rounded-full bg-muted/50 px-3 py-1 text-xs text-muted-foreground">
                        {item.text}
                      </div>
                    </div>
                  ) : (
                    <div className={`flex ${item.speaker === "user" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[80%] space-y-1 ${item.speaker === "user" ? "items-end" : "items-start"}`}>
                        <div className={`flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground ${item.speaker === "user" ? "justify-end" : "justify-start"}`}>
                          <span>{item.speaker === "user" ? "You" : "Assistant"}</span>
                          <span className="opacity-50">
                            {formatTime(item.timestamp)}
                          </span>
                        </div>
                        <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                          item.speaker === "user"
                            ? "rounded-br-md bg-primary text-primary-foreground"
                            : "rounded-bl-md bg-muted"
                        }`}>
                          {item.text}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <div ref={transcriptEndRef} />
            </div>
          )}
        </ScrollArea>

        {/* Floating Control Bar */}
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
          <div className="flex items-center gap-3 rounded-full border bg-background/95 px-4 py-2 shadow-lg backdrop-blur-sm">
            <div className="flex items-center gap-2 font-mono text-sm text-muted-foreground">
              <span>{formatDuration(callDuration)}</span>
              <AudioVisualizer stream={audioStream} isActive={connectionStatus === "connected"} />
            </div>

            <Button
              onClick={() => void handleConnect()}
              variant={connectionStatus === "connected" ? "destructive" : "default"}
              size="sm"
              className="gap-2 rounded-full"
              disabled={(!selectedAgentId && connectionStatus === "idle") || connectionStatus === "connecting"}
            >
              {connectionStatus === "idle" && (
                <>
                  <Play className="h-4 w-4" />
                  Start session
                </>
              )}
              {connectionStatus === "connecting" && (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Connecting...
                </>
              )}
              {connectionStatus === "connected" && (
                <>
                  <Square className="h-3 w-3 fill-current" />
                  Stop
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Right - Settings Panel */}
      <div className="flex w-[320px] shrink-0 flex-col border-l bg-muted/20">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {/* Agent Selection */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">Agent</Label>
            <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select an agent" />
              </SelectTrigger>
              <SelectContent>
                {voiceAgents?.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {/* System Instructions */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">System instructions</Label>
            {selectedAgentId ? (
              <Textarea
                value={editedSystemPrompt}
                onChange={(e) => setEditedSystemPrompt(e.target.value)}
                className="h-[120px] resize-none text-xs"
                placeholder="Enter system instructions..."
              />
            ) : (
              <div className="flex h-[120px] items-center justify-center rounded-md border bg-muted/50 text-xs text-muted-foreground">
                Select an agent to edit
              </div>
            )}
          </div>

          <Separator />

          {/* Voice */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">Voice</Label>
            <Select value={voice} onValueChange={setVoice}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VOICES.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {/* Turn Detection */}
          <div className="space-y-3">
            <Label className="text-sm font-medium">Turn detection</Label>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Threshold</span>
                <span>{threshold.toFixed(2)}</span>
              </div>
              <Slider
                value={[threshold]}
                onValueChange={(v) => setThreshold(v[0] ?? 0.5)}
                min={0}
                max={1}
                step={0.01}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Silence duration</span>
                <span>{silenceDuration} ms</span>
              </div>
              <Slider
                value={[silenceDuration]}
                onValueChange={(v) => setSilenceDuration(v[0] ?? 500)}
                min={100}
                max={2000}
                step={50}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
