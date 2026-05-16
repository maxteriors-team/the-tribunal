"use client";

import { motion, AnimatePresence } from "motion/react";
import { useState } from "react";

import { ContactSidebar } from "@/components/contacts/contact-sidebar";
import { ContactsList } from "@/components/contacts/contacts-list";
import { ConversationFeed } from "@/components/conversation/conversation-feed";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { useContactStore } from "@/lib/contact-store";
import { cn } from "@/lib/utils";

interface UnifiedInboxProps {
  className?: string;
}

export function UnifiedInbox({ className }: UnifiedInboxProps) {
  const isMobile = useIsMobile();
  const { selectedContact } = useContactStore();
  const [showSidebar, setShowSidebar] = useState(false);

  // On mobile, show sidebar as a sheet
  if (isMobile) {
    return (
      <div className={cn("flex h-full", className)}>
        {/* On mobile, show either list or conversation */}
        <AnimatePresence mode="wait">
          {!selectedContact ? (
            <motion.div
              key="contacts"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="flex-1"
            >
              <ContactsList />
            </motion.div>
          ) : (
            <motion.div
              key="conversation"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="flex-1"
            >
              <ConversationFeed />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Contact details sheet on mobile */}
        <Sheet open={showSidebar} onOpenChange={setShowSidebar}>
          <SheetContent side="right" className="w-full sm:w-[400px] p-0">
            <ContactSidebar onClose={() => setShowSidebar(false)} />
          </SheetContent>
        </Sheet>
      </div>
    );
  }

  // Desktop: 3-column layout using CSS Grid
  return (
    <div
      className={cn(
        "grid h-full w-full",
        className
      )}
      style={{
        gridTemplateColumns: "300px 1fr 320px"
      }}
    >
      {/* Left Panel: Contacts List */}
      <div className="flex flex-col h-full border-r overflow-hidden">
        <ContactsList className="h-full" />
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
