"use client";

import {
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Voicemail,
  Check,
  X,
  Clock,
  PhoneMissed,
  PlayCircle,
} from "lucide-react";
import { type ReactNode } from "react";

import { TranscriptViewer } from "@/components/calls/transcript-viewer";
import { AudioPlayer } from "@/components/ui/audio-player";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TimelineItem } from "@/types";

interface CallMessageItemProps {
  item: TimelineItem;
  isOutbound: boolean;
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

const callStatusConfig: Record<
  string,
  { icon: ReactNode; label: string; color: string }
> = {
  completed: {
    icon: <Check className="h-3 w-3" />,
    label: "Completed",
    color: "text-success bg-success/10",
  },
  failed: {
    icon: <X className="h-3 w-3" />,
    label: "Failed",
    color: "text-destructive bg-destructive/10",
  },
  no_answer: {
    icon: <PhoneMissed className="h-3 w-3" />,
    label: "No Answer",
    color: "text-warning bg-warning/10",
  },
  busy: {
    icon: <PhoneMissed className="h-3 w-3" />,
    label: "Busy",
    color: "text-warning bg-warning/10",
  },
  voicemail: {
    icon: <Voicemail className="h-3 w-3" />,
    label: "Voicemail",
    color: "text-info bg-info/10",
  },
  in_progress: {
    icon: <Phone className="h-3 w-3" />,
    label: "In Progress",
    color: "text-info bg-info/10",
  },
  initiated: {
    icon: <Clock className="h-3 w-3" />,
    label: "Initiated",
    color: "text-muted-foreground bg-muted",
  },
  ringing: {
    icon: <Phone className="h-3 w-3" />,
    label: "Ringing",
    color: "text-info bg-info/10",
  },
};

const sentimentStyles: Record<"positive" | "neutral" | "negative", string> = {
  positive: "bg-success/10 text-success border-success/20",
  neutral: "bg-muted text-muted-foreground border-border",
  negative: "bg-destructive/10 text-destructive border-destructive/20",
};

function unavailableRecordingLabel(status?: string): string | null {
  switch (status) {
    case "completed":
      return "Recording not available";
    case "no_answer":
      return "No recording - call not answered";
    case "busy":
      return "No recording - line busy";
    case "failed":
      return "No recording - call failed";
    default:
      return null;
  }
}

export function CallMessageItem({ item, isOutbound }: CallMessageItemProps) {
  const sentiment = item.signals?.sentiment;
  const callSummary = item.signals?.summary;
  const callStatus = item.status
    ? callStatusConfig[item.status] ?? {
        icon: <Phone className="h-3 w-3" />,
        label: item.status,
        color: "text-muted-foreground bg-muted",
      }
    : null;

  const callIcon = isOutbound ? (
    <PhoneOutgoing className="h-4 w-4 text-success" />
  ) : (
    <PhoneIncoming className="h-4 w-4 text-info" />
  );

  const unavailableLabel = unavailableRecordingLabel(item.status);

  return (
    <div className="space-y-3">
      {/* Call header */}
      <div className="flex items-center gap-3">
        <div
          className={cn(
            "h-10 w-10 rounded-full flex items-center justify-center",
            isOutbound ? "bg-success/10" : "bg-info/10",
          )}
        >
          {callIcon}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <p className="font-medium text-sm">
              {isOutbound ? "Outgoing Call" : "Incoming Call"}
            </p>
            {callStatus && (
              <Badge
                variant="secondary"
                className={cn(
                  "text-[10px] px-1.5 py-0 h-4 gap-0.5",
                  callStatus.color,
                )}
              >
                {callStatus.icon}
                <span className="ml-0.5">{callStatus.label}</span>
              </Badge>
            )}
            {sentiment && (
              <Badge
                variant="outline"
                title={callSummary || undefined}
                className={cn(
                  "text-[10px] px-1.5 py-0 h-4 capitalize",
                  sentimentStyles[sentiment],
                )}
              >
                {sentiment}
              </Badge>
            )}
          </div>
          {callSummary && (
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
              {callSummary}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            {item.status === "completed" && item.duration_seconds
              ? `Duration: ${formatDuration(item.duration_seconds)}`
              : item.status !== "completed"
                ? ""
                : "Duration: 0:00"}
          </p>
        </div>
      </div>

      {/* Recording player */}
      {item.recording_url && (
        <div className="pt-2 border-t">
          <AudioPlayer
            url={item.recording_url}
            duration={item.duration_seconds}
          />
        </div>
      )}

      {/* Recording unavailable indicator */}
      {!item.recording_url && unavailableLabel && (
        <div className="pt-2 border-t">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <PlayCircle className="h-4 w-4" />
            <span>{unavailableLabel}</span>
          </div>
        </div>
      )}

      {/* Transcript */}
      {item.transcript && (
        <div className="pt-2 border-t">
          <TranscriptViewer
            transcript={item.transcript}
            maxHeight="400px"
            collapsible
            defaultExpanded={false}
          />
        </div>
      )}
    </div>
  );
}
