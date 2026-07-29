"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import { AIAgentsSection } from "./ai-agents-section";
import { FollowupSection } from "./followup-section";
import { QuickActionsSection } from "./quick-actions-section";

interface ActionsPanelProps {
  className?: string;
  onClose?: () => void;
}

export function ActionsPanel({ className, onClose }: ActionsPanelProps) {
  const previousActiveElement = useRef<HTMLElement | null>(null);

  // Escape-to-close + focus restoration. Only active when rendered as a
  // slide-over (i.e. onClose is provided); inline desktop usage is a no-op.
  useEffect(() => {
    if (!onClose) return;

    previousActiveElement.current =
      typeof document !== "undefined"
        ? (document.activeElement as HTMLElement | null)
        : null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (previousActiveElement.current && typeof previousActiveElement.current.focus === "function") {
        previousActiveElement.current.focus();
      }
    };
  }, [onClose]);

  const overlayProps = onClose
    ? ({ role: "dialog" as const, "aria-modal": true })
    : {};

  return (
    <div
      className={cn("flex flex-col h-full bg-background", className)}
      {...overlayProps}
    >
      {/* Header. As a slide-over the enclosing Sheet renders the close
          control, so only the inline console view needs the back link. */}
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        {!onClose && (
          <Button size="icon" variant="ghost" className="h-8 w-8" asChild>
            <Link href="/contacts" aria-label="Back to contacts">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
        )}
        <h2 className="font-semibold">Actions</h2>
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="min-h-0 flex-1">
        <div className="p-4 space-y-6">
          {/* AI Agents Section */}
          <AIAgentsSection />

          <Separator />

          {/* Follow-up Section */}
          <FollowupSection />

          <Separator />

          {/* Quick Actions Section */}
          <QuickActionsSection />
        </div>
      </ScrollArea>
    </div>
  );
}
