"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Menu, User } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import { ActionsPanel } from "@/components/actions/actions-panel";
import { ConversationFeed } from "@/components/conversation/conversation-feed";
import { ContactSidebar } from "@/components/contacts/contact-sidebar";

interface ConversationLayoutProps {
  className?: string;
}

export function ConversationLayout({ className }: ConversationLayoutProps) {
  const isMobile = useIsMobile();
  const [showActionsPanel, setShowActionsPanel] = React.useState(false);
  const [showSidebar, setShowSidebar] = React.useState(false);

  // On mobile, show sheets for left and right panels
  if (isMobile) {
    return (
      <div className={cn("flex flex-col h-full", className)}>
        {/* Mobile Header with navigation */}
        <div className="flex items-center justify-between px-2 py-2 border-b">
          <div className="flex items-center gap-1">
            <Link href="/contacts" aria-label="Back to contacts">
              <Button size="icon" variant="ghost" className="h-9 w-9">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <Sheet open={showActionsPanel} onOpenChange={setShowActionsPanel}>
              <SheetTrigger asChild>
                <Button size="icon" variant="ghost" className="h-9 w-9" aria-label="Open actions menu">
                  <Menu className="h-4 w-4" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[320px] p-0">
                <ActionsPanel onClose={() => setShowActionsPanel(false)} />
              </SheetContent>
            </Sheet>
          </div>

          <Sheet open={showSidebar} onOpenChange={setShowSidebar}>
            <SheetTrigger asChild>
              <Button size="icon" variant="ghost" className="h-9 w-9" aria-label="Open contact details">
                <User className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-full sm:w-[400px] p-0">
              <ContactSidebar onClose={() => setShowSidebar(false)} />
            </SheetContent>
          </Sheet>
        </div>

        {/* Conversation Feed takes full width on mobile */}
        <div className="flex-1 overflow-hidden">
          <ConversationFeed className="h-full" />
        </div>
      </div>
    );
  }

  // Desktop: 3-column layout using CSS Grid
  return (
    <div
      className={cn("grid h-full w-full", className)}
      style={{
        gridTemplateColumns: "320px 1fr 320px",
      }}
    >
      {/* Left Panel: Actions Panel */}
      <div className="flex flex-col h-full border-r overflow-hidden">
        <ActionsPanel className="h-full" />
      </div>

      {/* Center Panel: Conversation Feed */}
      <div className="flex flex-col h-full overflow-hidden">
        <ConversationFeed className="h-full" />
      </div>

      {/* Right Panel: Contact Sidebar */}
      <div className="flex flex-col h-full border-l overflow-hidden">
        <ContactSidebar className="h-full" />
      </div>
    </div>
  );
}
