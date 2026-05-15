"use client";

import * as React from "react";
import { motion, AnimatePresence } from "motion/react";
import { Search, Plus, User, Phone, Mail, Building2, Sparkles } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { contactStatusColors } from "@/lib/status-colors";
import { useContactStore } from "@/lib/contact-store";
import { useContactsPaginated } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { formatPhoneNumber } from "@/lib/utils/phone";
import { getContactInitials } from "@/lib/utils/initials";
import { CreateContactDialog } from "./create-contact-dialog";
import type { Contact } from "@/types";

interface ContactsListProps {
  className?: string;
}

function ContactItemSkeleton() {
  return (
    <div className="flex items-center gap-3 p-3">
      <Skeleton className="h-10 w-10 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  );
}

interface ContactItemProps {
  contact: Contact;
  isSelected: boolean;
  onClick: () => void;
}

function ContactItem({ contact, isSelected, onClick }: ContactItemProps) {
  const displayName = [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Unknown";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.15 }}
    >
      <button
        onClick={onClick}
        className={cn(
          "w-full flex items-start gap-3 p-3 rounded-lg text-left transition-colors",
          "hover:bg-accent/50",
          isSelected && "bg-accent"
        )}
      >
        <Avatar className="h-10 w-10 shrink-0">
          <AvatarFallback className="bg-primary/10 text-primary text-sm font-medium">
            {getContactInitials(contact)}
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium truncate">{displayName}</span>
            <div className="flex items-center gap-1 shrink-0">
              {contact.lead_score != null && contact.lead_score > 0 && (
                <span
                  className={cn(
                    "text-[10px] font-bold px-1 py-0.5 rounded",
                    contact.lead_score >= 80
                      ? "text-success bg-success/10"
                      : contact.lead_score >= 40
                        ? "text-warning bg-warning/10"
                        : "text-muted-foreground bg-muted"
                  )}
                  title={`Lead Score: ${contact.lead_score}`}
                >
                  {contact.lead_score}
                </span>
              )}
              {(contact.business_intel?.ad_pixels?.meta_pixel || contact.business_intel?.ad_pixels?.google_ads) && (
                <span title="Running paid ads">
                  <Sparkles className="h-3 w-3 text-primary" />
                </span>
              )}
              <Badge variant="secondary" className={cn("text-xs", contactStatusColors[contact.status])}>
                {contact.status}
              </Badge>
            </div>
          </div>

          <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
            {contact.phone_number && (
              <div className="flex items-center gap-1.5 truncate">
                <Phone className="h-3 w-3 shrink-0" />
                <span className="truncate">{formatPhoneNumber(contact.phone_number)}</span>
              </div>
            )}
            {contact.company_name && (
              <div className="flex items-center gap-1.5 truncate">
                <Building2 className="h-3 w-3 shrink-0" />
                <span className="truncate">{contact.company_name}</span>
              </div>
            )}
            {contact.email && !contact.phone_number && (
              <div className="flex items-center gap-1.5 truncate">
                <Mail className="h-3 w-3 shrink-0" />
                <span className="truncate">{contact.email}</span>
              </div>
            )}
          </div>
        </div>
      </button>
    </motion.div>
  );
}

export function ContactsList({ className }: ContactsListProps) {
  const [isCreateDialogOpen, setIsCreateDialogOpen] = React.useState(false);
  const { selectedContact, setSelectedContact, searchQuery, setSearchQuery } = useContactStore();
  const workspaceId = useWorkspaceId();

  // Fetch contacts with server-side search filtering
  const { data, isPending } = useContactsPaginated(workspaceId ?? "", {
    page: 1,
    page_size: 50,
    ...(searchQuery.trim() && { search: searchQuery.trim() }),
  });
  const contacts = data?.items ?? [];

  return (
    <div className={cn("flex flex-col h-full", className)}>
      {/* Header */}
      <div className="p-4 border-b space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Contacts</h2>
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8"
            onClick={() => setIsCreateDialogOpen(true)}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search contacts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Contacts List */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {isPending ? (
            <div className="space-y-1">
              {Array.from({ length: 8 }).map((_, i) => (
                <ContactItemSkeleton key={i} />
              ))}
            </div>
          ) : contacts.length === 0 ? (
            <PageEmptyState
              className="py-12"
              icon={<User className="h-12 w-12" />}
              title={searchQuery ? "No contacts found" : "No contacts yet"}
            />
          ) : (
            <AnimatePresence mode="popLayout">
              <div className="space-y-1">
                {contacts.map((contact) => (
                  <ContactItem
                    key={contact.id}
                    contact={contact}
                    isSelected={selectedContact?.id === contact.id}
                    onClick={() => setSelectedContact(contact)}
                  />
                ))}
              </div>
            </AnimatePresence>
          )}
        </div>
      </ScrollArea>

      <CreateContactDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
      />
    </div>
  );
}
