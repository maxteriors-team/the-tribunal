"use client";

import { Headphones, Loader2, Mic, MicOff, PhoneIncoming, PhoneOff, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { SoftphonePhase } from "@/providers/softphone-provider";

interface SoftphoneBarProps {
  phase: SoftphonePhase;
  contactName: string;
  isMuted: boolean;
  startedAt: number | null;
  error: string | null;
  onAnswer: () => Promise<void>;
  onToggleMute: () => Promise<void>;
  onHangup: () => Promise<void>;
  onDismiss: () => void;
}

function formatDuration(startedAt: number | null, now: number): string {
  if (!startedAt) return "00:00";
  const totalSeconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function SoftphoneBar({
  phase,
  contactName,
  isMuted,
  startedAt,
  error,
  onAnswer,
  onToggleMute,
  onHangup,
  onDismiss,
}: SoftphoneBarProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (phase !== "active") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  if (phase === "idle") return null;

  const status =
    phase === "preparing"
      ? "Connecting headset"
      : phase === "waiting"
        ? "Calling your browser"
        : phase === "ringing"
          ? "Headset ready"
          : phase === "active"
            ? `Call active · ${formatDuration(startedAt, now)}`
            : phase === "ended"
              ? "Call ended"
              : "Browser call failed";

  return (
    <section
      aria-label="Browser call"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-xl items-center gap-3 rounded-lg border border-border bg-background p-3 shadow-lg"
    >
      <div className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-muted">
        {phase === "preparing" || phase === "waiting" ? (
          <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        ) : (
          <Headphones className="size-5" aria-hidden="true" />
        )}
      </div>

      <div className="min-w-0 flex-1" aria-live="polite" aria-atomic="true">
        <p className="truncate text-sm font-medium">{contactName || "Browser call"}</p>
        <p className="truncate text-sm text-muted-foreground">{error || status}</p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {phase === "ringing" && (
          <Button type="button" size="sm" onClick={() => void onAnswer()}>
            <PhoneIncoming className="mr-2 size-4" aria-hidden="true" />
            Answer
          </Button>
        )}
        {phase === "active" && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
            aria-pressed={isMuted}
            onClick={() => void onToggleMute()}
          >
            {isMuted ? (
              <MicOff className="size-4" aria-hidden="true" />
            ) : (
              <Mic className="size-4" aria-hidden="true" />
            )}
          </Button>
        )}
        {phase !== "ended" && phase !== "error" ? (
          <Button
            type="button"
            variant="destructive"
            size="icon"
            aria-label="End browser call"
            onClick={() => void onHangup()}
          >
            <PhoneOff className="size-4" aria-hidden="true" />
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Dismiss browser call"
            onClick={onDismiss}
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        )}
      </div>
    </section>
  );
}
