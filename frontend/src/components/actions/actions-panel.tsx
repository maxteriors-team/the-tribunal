"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import { AIAgentsSection } from "./ai-agents-section";
import { FollowupSection } from "./followup-section";
import { QuickActionsSection } from "./quick-actions-section";

interface ActionsPanelProps {
  className?: string;
  onClose?: () => void;
}

export function ActionsPanel({ className, onClose }: ActionsPanelProps) {
  const isMobile = useIsMobile();

  return (
    <div className={cn("flex flex-col h-full bg-background", className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          {!isMobile && (
            <Link href="/contacts" aria-label="Back to contacts">
              <Button size="icon" variant="ghost" className="h-8 w-8">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
          )}
          <h2 className="font-semibold">Actions</h2>
        </div>
        {isMobile && onClose && (
          <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onClose} aria-label="Close actions panel">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="flex-1">
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
