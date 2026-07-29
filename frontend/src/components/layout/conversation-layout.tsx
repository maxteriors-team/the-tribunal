"use client";

import { ArrowLeft, Menu, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ActionsPanel } from "@/components/actions/actions-panel";
import { ContactSidebar } from "@/components/contacts/contact-sidebar";
import { ConversationFeed } from "@/components/conversation/conversation-feed";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useIsCompactConsole } from "@/hooks/useMobile";
import { cn } from "@/lib/utils";

interface ConversationLayoutProps {
  className?: string;
}

export function ConversationLayout({ className }: ConversationLayoutProps) {
  // Phones through small laptops: the rails become slide-overs so the message
  // column keeps a readable width instead of being crushed between them.
  const isCompact = useIsCompactConsole();
  const [showActionsPanel, setShowActionsPanel] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);

  if (isCompact) {
    return (
      <div className={cn("flex h-full flex-col", className)}>
        {/* Panel triggers for the two rails that don't fit side by side here */}
        <div className="flex shrink-0 items-center justify-between border-b px-2 py-2">
          <div className="flex items-center gap-1">
            <Button size="icon" variant="ghost" className="h-9 w-9" asChild>
              <Link href="/contacts" aria-label="Back to contacts">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <Sheet open={showActionsPanel} onOpenChange={setShowActionsPanel}>
              <SheetTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9"
                  aria-label="Open actions menu"
                >
                  <Menu className="h-4 w-4" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-full p-0 sm:w-[340px]">
                <SheetHeader className="sr-only">
                  <SheetTitle>Conversation actions</SheetTitle>
                  <SheetDescription>
                    AI agent assignment, follow-up settings and quick actions
                    for this conversation.
                  </SheetDescription>
                </SheetHeader>
                <ActionsPanel onClose={() => setShowActionsPanel(false)} />
              </SheetContent>
            </Sheet>
          </div>

          <Sheet open={showSidebar} onOpenChange={setShowSidebar}>
            <SheetTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9"
                aria-label="Open contact details"
              >
                <User className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-full p-0 sm:w-[400px]">
              <SheetHeader className="sr-only">
                <SheetTitle>Contact details</SheetTitle>
                <SheetDescription>
                  Contact information, engagement and recent activity.
                </SheetDescription>
              </SheetHeader>
              <ContactSidebar onClose={() => setShowSidebar(false)} />
            </SheetContent>
          </Sheet>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <ConversationFeed className="h-full" />
        </div>
      </div>
    );
  }

  // Desktop console: fixed-but-flexible rails around a fluid conversation.
  // `minmax(0, 1fr)` is load-bearing — a bare `1fr` floors at the message
  // column's max-content width and pushes the contact rail off screen.
  return (
    <div
      className={cn(
        "grid h-full w-full grid-cols-[minmax(280px,320px)_minmax(0,1fr)_minmax(300px,340px)]",
        className,
      )}
    >
      {/* Left rail: per-conversation automation controls */}
      <div className="flex h-full min-w-0 flex-col overflow-hidden border-r">
        <ActionsPanel className="h-full" />
      </div>

      {/* Center: the conversation itself */}
      <div className="flex h-full min-w-0 flex-col overflow-hidden">
        <ConversationFeed className="h-full" />
      </div>

      {/* Right rail: who this contact is */}
      <div className="flex h-full min-w-0 flex-col overflow-hidden border-l">
        <ContactSidebar className="h-full" />
      </div>
    </div>
  );
}
