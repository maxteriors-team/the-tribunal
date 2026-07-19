"use client";

import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ContactFormDialog } from "@/components/contacts/contact-form-dialog";
import { ContactActions } from "@/components/contacts/contact-sidebar/contact-actions";
import { ContactAppointments } from "@/components/contacts/contact-sidebar/contact-appointments";
import { ContactFilesMedia } from "@/components/contacts/contact-sidebar/contact-files-media";
import { ContactHeader } from "@/components/contacts/contact-sidebar/contact-header";
import { ContactInfoSection } from "@/components/contacts/contact-sidebar/contact-info-section";
import { ContactNotesMeta } from "@/components/contacts/contact-sidebar/contact-notes-meta";
import { ContactQuotes } from "@/components/contacts/contact-sidebar/contact-quotes";
import { ContactTimeline } from "@/components/contacts/contact-sidebar/contact-timeline";
import { DeleteContactDialog } from "@/components/contacts/contact-sidebar/delete-contact-dialog";
import { EngagementSummary } from "@/components/contacts/contact-sidebar/engagement-summary";
import { ImportantDatesSection } from "@/components/contacts/contact-sidebar/important-dates";
import { MobileOverlayHeader } from "@/components/contacts/contact-sidebar/mobile-overlay-header";
import { useContactSidebarData } from "@/components/contacts/contact-sidebar/use-contact-sidebar-data";
import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useIsMobile } from "@/hooks/useMobile";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { useContactStore } from "@/lib/contact-store";
import { messages } from "@/lib/messages";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface ContactSidebarProps {
  className?: string;
  onClose?: () => void;
}

export function ContactSidebar({ className, onClose }: ContactSidebarProps) {
  const router = useRouter();
  const { selectedContact, setSelectedContact } = useContactStore();
  const isMobile = useIsMobile();
  const workspaceId = useWorkspaceId();
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
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (
        previousActiveElement.current &&
        typeof previousActiveElement.current.focus === "function"
      ) {
        previousActiveElement.current.focus();
      }
    };
  }, [onClose]);

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const {
    timeline,
    appointments,
    appointmentsLoading,
    quotes,
    quotesLoading,
    phoneNumbers,
    aiEnabled,
    setAiEnabled,
    initiateCallMutation,
    toggleAIMutation,
    deleteContactMutation,
  } = useContactSidebarData({ workspaceId, contact: selectedContact });

  const handleCall = () => {
    if (!selectedContact?.phone_number) {
      toast.error(messages.contacts.noPhoneNumber);
      return;
    }

    const voiceEnabledNumbers = phoneNumbers.filter((p) => p.voice_enabled);
    if (voiceEnabledNumbers.length === 0) {
      toast.error(messages.phoneNumbers.noneVoiceEnabled);
      return;
    }

    initiateCallMutation.mutate({
      to_number: selectedContact.phone_number,
      from_phone_number: voiceEnabledNumbers[0].phone_number,
      contact_phone: selectedContact.phone_number,
    });
  };

  const handleAIEngage = () => {
    if (!selectedContact) return;

    // Optimistic toggle
    const newState = !aiEnabled;
    setAiEnabled(newState);

    toggleAIMutation.mutate(
      { contactId: selectedContact.id, enabled: newState },
      {
        onSuccess: (data) => {
          toast.success(
            data.ai_enabled ? messages.contacts.aiEnabled : messages.contacts.aiDisabled,
          );
        },
        onError: (error) => {
          setAiEnabled(!newState);
          toast.error(
            getApiErrorMessage(error, messages.contacts.aiToggleFailed),
          );
        },
      },
    );
  };

  const handleDelete = () => {
    if (!selectedContact) return;

    deleteContactMutation.mutate(selectedContact.id, {
      onSuccess: () => {
        toast.success(messages.contacts.deleted);
        setSelectedContact(null);
        setDeleteDialogOpen(false);
        router.push("/contacts");
      },
      onError: (error) => {
        toast.error(
          getApiErrorMessage(error, messages.contacts.deleteFailed),
        );
      },
    });
  };

  if (!selectedContact) {
    return (
      <div
        className={cn(
          "flex flex-col h-full items-center justify-center p-8",
          className,
        )}
      >
        <p className="text-sm text-muted-foreground text-center">
          Select a contact to view details
        </p>
      </div>
    );
  }

  const displayName = [selectedContact.first_name, selectedContact.last_name]
    .filter(Boolean)
    .join(" ");

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className={cn("flex flex-col h-full bg-background", className)}
      {...(onClose ? { role: "dialog", "aria-modal": true } : {})}
    >
      {isMobile && onClose && <MobileOverlayHeader onClose={onClose} />}

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-6">
          <ContactHeader contact={selectedContact} />

          <Separator />
          <ContactActions
            hasPhoneNumber={!!selectedContact.phone_number}
            aiEnabled={aiEnabled}
            isCalling={initiateCallMutation.isPending}
            isTogglingAi={toggleAIMutation.isPending}
            onCall={handleCall}
            onSchedule={() => setScheduleDialogOpen(true)}
            onEdit={() => setEditDialogOpen(true)}
            onToggleAi={handleAIEngage}
            onDelete={() => setDeleteDialogOpen(true)}
          />

          <Separator />
          <ContactInfoSection contact={selectedContact} />

          <ContactFilesMedia contactId={selectedContact.id} />

          <Separator />
          <ImportantDatesSection
            contact={selectedContact}
            workspaceId={workspaceId}
          />

          <Separator />
          <EngagementSummary
            workspaceId={workspaceId ?? ""}
            contactId={selectedContact.id}
          />

          <Separator />
          <ContactTimeline contact={selectedContact} timeline={timeline} />

          <Separator />
          <ContactAppointments
            workspaceId={workspaceId}
            contactId={selectedContact.id}
            appointments={appointments}
            isLoading={appointmentsLoading}
          />

          <Separator />
          <ContactQuotes quotes={quotes} isLoading={quotesLoading} />

          <ContactNotesMeta contact={selectedContact} />
        </div>
      </ScrollArea>

      <ContactFormDialog
        mode="edit"
        contact={selectedContact}
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
      />
      <ScheduleAppointmentDialog
        contact={selectedContact}
        open={scheduleDialogOpen}
        onOpenChange={setScheduleDialogOpen}
      />
      <DeleteContactDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        displayName={displayName}
        isDeleting={deleteContactMutation.isPending}
        onConfirm={handleDelete}
      />
    </motion.div>
  );
}
