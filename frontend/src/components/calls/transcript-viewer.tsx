"use client";

import { User, Bot, ChevronDown, ChevronUp, FileText } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
}

interface TranscriptViewerProps {
  transcript: string;
  maxHeight?: string;
  className?: string;
  collapsible?: boolean;
  defaultExpanded?: boolean;
}

/**
 * Parse transcript string into structured entries.
 * Supports both JSON format and plain text format.
 */
function parseTranscript(transcript: string): TranscriptEntry[] {
  // Try parsing as JSON array first
  try {
    const parsed = JSON.parse(transcript);
    if (Array.isArray(parsed)) {
      return parsed.map((entry) => ({
        // Handle both "agent" and "assistant" roles
        role: entry.role === "user" ? "user" : "agent",
        text: String(entry.text || entry.content || ""),
      }));
    }
  } catch {
    // Not valid JSON, fall through to plain text parsing
  }

  // Fall back to plain text parsing
  // Common patterns: "Agent: ..." / "User: ..." or "Customer: ..." / "Contact: ..."
  const lines = transcript.split("\n").filter((line) => line.trim());
  const entries: TranscriptEntry[] = [];

  for (const line of lines) {
    const lowerLine = line.toLowerCase();
    if (
      lowerLine.startsWith("agent:") ||
      lowerLine.startsWith("assistant:") ||
      lowerLine.startsWith("ai:") ||
      lowerLine.startsWith("bot:")
    ) {
      entries.push({
        role: "agent",
        text: line.replace(/^(agent|assistant|ai|bot):\s*/i, ""),
      });
    } else if (
      lowerLine.startsWith("user:") ||
      lowerLine.startsWith("customer:") ||
      lowerLine.startsWith("contact:") ||
      lowerLine.startsWith("caller:") ||
      lowerLine.startsWith("human:")
    ) {
      entries.push({
        role: "user",
        text: line.replace(/^(user|customer|contact|caller|human):\s*/i, ""),
      });
    } else if (entries.length > 0) {
      // Continuation of previous entry
      entries[entries.length - 1].text += " " + line.trim();
    } else {
      // Unknown format, treat as user message
      entries.push({ role: "user", text: line.trim() });
    }
  }

  return entries;
}

function TranscriptContent({
  entries,
  maxHeight,
  className,
}: {
  entries: TranscriptEntry[];
  maxHeight: string;
  className?: string;
}) {
  return (
    <div
      className={cn("rounded-md border overflow-y-auto", className)}
      style={{ maxHeight }}
    >
      <div className="p-3 space-y-3">
        {entries.map((entry, index) => (
          <div
            key={index}
            className={cn(
              "flex gap-2",
              entry.role === "user" ? "justify-end" : "justify-start"
            )}
          >
            {entry.role === "agent" && (
              <div className="flex-shrink-0 size-6 rounded-full bg-primary/10 flex items-center justify-center">
                <Bot className="size-3.5 text-primary" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                entry.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted"
              )}
            >
              {entry.text}
            </div>
            {entry.role === "user" && (
              <div className="flex-shrink-0 size-6 rounded-full bg-info/10 flex items-center justify-center">
                <User className="size-3.5 text-info" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function TranscriptViewer({
  transcript,
  maxHeight = "200px",
  className,
  collapsible = false,
  defaultExpanded = true,
}: TranscriptViewerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const entries = parseTranscript(transcript);

  if (entries.length === 0) {
    return (
      <div className="text-sm text-muted-foreground italic">
        No transcript available
      </div>
    );
  }

  // Non-collapsible mode (original behavior)
  if (!collapsible) {
    return (
      <TranscriptContent
        entries={entries}
        maxHeight={maxHeight}
        className={className}
      />
    );
  }

  // Collapsible mode
  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-between px-2 py-1.5 h-auto hover:bg-muted/50"
        >
          <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <FileText className="h-3.5 w-3.5" />
            Transcript ({entries.length} messages)
          </span>
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2">
        <TranscriptContent
          entries={entries}
          maxHeight={maxHeight}
          className={className}
        />
      </CollapsibleContent>
    </Collapsible>
  );
}
