"use client";

import {
  ArrowLeft,
  CalendarPlus,
  Edit2,
  Flame,
  Loader2,
  MessageSquare,
  Phone,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ContactHistory } from "@/components/contacts/contact-detail/contact-history";
import { ContactFormDialog } from "@/components/contacts/contact-form-dialog";
import { ContactFilesMedia } from "@/components/contacts/contact-sidebar/contact-files-media";
import { ContactInfoSection } from "@/components/contacts/contact-sidebar/contact-info-section";
import { ContactNotesMeta } from "@/components/contacts/contact-sidebar/contact-notes-meta";
import { EngagementSummary } from "@/components/contacts/contact-sidebar/engagement-summary";
import { ImportantDatesSection } from "@/components/contacts/contact-sidebar/important-dates";
import { useContactSidebarData } from "@/components/contacts/contact-sidebar/use-contact-sidebar-data";
import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Separator } from "@/components/ui/separator";
import { useContact } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactStatusDotColors, contactStatusLabels } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils/date";
import { getContactInitials } from "@/lib/utils/initials";

interface ContactDetailPageProps {
  contactId: number;
}

/**
 * Full-width home for one contact record: identity and key facts on the left,
 * the complete activity history on the right. The conversation console keeps
 * the same data in a narrow rail; this is where it can breathe.
 */
export function ContactDetailPage({ contactId }: ContactDetailPageProps) {
  const workspaceId = useWorkspaceId();
  const [editOpen, setEditOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);

  const {
    data: contact,
    isPending,
    isError,
    refetch,
  } = useContact(workspaceId ?? "", contactId);

  const { callContact, initiateCallMutation } = useContactSidebarData({
    workspaceId,
    contact: contact ?? null,
  });

  if (isPending) {
    return <PageLoadingState message="Loading contact…" />;
  }

  if (isError || !contact) {
    return (
      <PageErrorState
        message="Couldn't load this contact."
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }

  const displayName =
    [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Unknown";
  const engagementScore = contact.engagement_score ?? 0;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
      <Button variant="ghost" size="sm" className="-ml-2" asChild>
        <Link href={`/contacts/${contact.id}`}>
          <ArrowLeft className="size-4" />
          Back to conversation
        </Link>
      </Button>

      {/* Identity + primary actions */}
      <Card>
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            <Avatar className="size-16">
              <AvatarImage src={contact.avatar_url} alt="" size={128} />
              <AvatarFallback className="bg-primary/10 text-primary text-lg font-semibold">
                {getContactInitials(contact)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold">{displayName}</h1>
              {contact.company_name && (
                <p className="text-muted-foreground truncate text-sm">
                  {contact.company_name}
                </p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="gap-1.5">
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      contactStatusDotColors[contact.status],
                    )}
                    aria-hidden
                  />
                  {contactStatusLabels[contact.status]}
                </Badge>
                <Badge variant="outline" className="gap-1">
                  <Flame className="size-3" aria-hidden />
                  Engagement {engagementScore}
                </Badge>
                {contact.last_engaged_at && (
                  <span className="text-muted-foreground text-xs">
                    Last engaged {formatRelative(contact.last_engaged_at)}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link href={`/contacts/${contact.id}`}>
                <MessageSquare className="size-4" />
                Message
              </Link>
            </Button>
            <Button
              variant="outline"
              onClick={callContact}
              disabled={!contact.phone_number || initiateCallMutation.isPending}
            >
              {initiateCallMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Phone className="size-4" />
              )}
              Call
            </Button>
            <Button variant="outline" onClick={() => setScheduleOpen(true)}>
              <CalendarPlus className="size-4" />
              Schedule
            </Button>
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Edit2 className="size-4" />
              Edit
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        {/* Details */}
        <div className="min-w-0 space-y-6">
          <Card>
            <CardContent className="space-y-6">
              <ContactInfoSection contact={contact} wrapValues />
              <Separator />
              <ImportantDatesSection contact={contact} workspaceId={workspaceId} />
              <ContactNotesMeta contact={contact} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-6">
              <EngagementSummary
                workspaceId={workspaceId ?? ""}
                contactId={contact.id}
              />
              <Separator />
              <ContactFilesMedia contactId={contact.id} />
            </CardContent>
          </Card>
        </div>

        {/* History */}
        <Card className="min-w-0">
          <CardContent>
            <ContactHistory workspaceId={workspaceId} contactId={contact.id} />
          </CardContent>
        </Card>
      </div>

      <ContactFormDialog
        mode="edit"
        contact={contact}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
      <ScheduleAppointmentDialog
        contact={contact}
        open={scheduleOpen}
        onOpenChange={setScheduleOpen}
      />
    </div>
  );
}
