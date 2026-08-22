"use client";

/**
 * Shared appointment-details dialog for the calendar screens.
 *
 * Extracted so the week grid and the month grid drive one controlled dialog
 * (keyed by the selected appointment id) instead of each rendering their own —
 * no duplicated 100-line dialog body, one place to evolve the detail view.
 */
import { useMutation } from "@tanstack/react-query";
import { CalendarDays, Clock, ExternalLink, Phone, Trash2, Video } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  AttendanceControl,
  hasStarted,
  ReminderBadges,
  SendReminderButton,
} from "@/components/calendar/appointment-actions";
import { AppointmentAssigneePicker } from "@/components/calendar/appointment-assignee-picker";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCapabilities } from "@/hooks/useCapabilities";
import { appointmentsApi } from "@/lib/api/appointments";
import { getContactName, getInitials } from "@/lib/calendar/calendar-derivations";
import { appointmentStatusColors } from "@/lib/status-colors";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Appointment } from "@/types";

interface AppointmentDetailsDialogProps {
  appointment: Appointment | null;
  workspaceId: string | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDelete: (appointmentId: number) => void;
  onChanged: () => void;
  deleting: boolean;
}

export function AppointmentDetailsDialog({
  appointment: apt,
  workspaceId,
  open,
  onOpenChange,
  onDelete,
  onChanged,
  deleting,
}: AppointmentDetailsDialogProps) {
  const { can } = useCapabilities();
  const canAssignUsers = can("jobs:write");
  const [bookableStaffId, setBookableStaffId] = useState<string | null>(
    apt?.bookable_staff_id ?? null,
  );

  const assignmentMutation = useMutation({
    mutationFn: async (nextStaffId: string | null) => {
      if (!apt || !workspaceId) throw new Error("No appointment selected");
      return appointmentsApi.update(workspaceId, apt.id, {
        bookable_staff_id: nextStaffId,
      });
    },
    onSuccess: (_updated, nextStaffId) => {
      toast.success(nextStaffId ? "User tagged on appointment" : "Appointment unassigned");
      onChanged();
    },
    onError: (error: unknown) => {
      setBookableStaffId(apt?.bookable_staff_id ?? null);
      toast.error(getApiErrorMessage(error, "Failed to update assigned user"));
    },
  });

  const handleAssigneeChange = (nextStaffId: string | null) => {
    setBookableStaffId(nextStaffId);
    assignmentMutation.mutate(nextStaffId);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        {apt ? (
          <>
            <DialogHeader>
              <DialogTitle>{apt.service_type || "Appointment"}</DialogTitle>
              <DialogDescription>
                {formatDate(apt.scheduled_at, {
                  pattern: apt.anytime ? "EEEE, MMMM d, yyyy" : "EEEE, MMMM d, yyyy 'at' h:mm a",
                })}
                {apt.anytime ? " · Any time" : null}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Avatar className="size-10">
                    <AvatarFallback>
                      {getInitials(apt.contact?.first_name || "", apt.contact?.last_name)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <p className="font-medium">{getContactName(apt.contact)}</p>
                    <Badge variant="outline" className={appointmentStatusColors[apt.status]}>
                      {apt.status}
                    </Badge>
                    <ReminderBadges
                      reminderSentAt={apt.reminder_sent_at}
                      remindersSent={apt.reminders_sent}
                    />
                    {apt.reminder_sent_at && (
                      <p className="text-xs text-muted-foreground">
                        Last reminder:{" "}
                        {formatDate(apt.reminder_sent_at, {
                          pattern: "MMM d, h:mm a",
                        })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {workspaceId && apt.status === "scheduled" && (
                    <SendReminderButton
                      appointment={apt}
                      workspaceId={workspaceId}
                      onSent={onChanged}
                    />
                  )}
                  {apt.status === "scheduled" && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => onDelete(apt.id)}
                      disabled={deleting}
                      className="text-destructive hover:text-destructive"
                      aria-label="Delete appointment"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </div>
              </div>
              {canAssignUsers && workspaceId ? (
                <div className="rounded-md border bg-muted/20 p-3">
                  <AppointmentAssigneePicker
                    workspaceId={workspaceId}
                    value={bookableStaffId}
                    onValueChange={handleAssigneeChange}
                    disabled={assignmentMutation.isPending}
                    id="appointment-details-assignee"
                  />
                </div>
              ) : null}
              {workspaceId && hasStarted(apt.scheduled_at) && apt.status !== "cancelled" ? (
                <div className="space-y-2 rounded-md border bg-muted/30 p-3">
                  <p className="text-sm font-medium">Did they show up?</p>
                  <p className="text-xs text-muted-foreground">
                    Recording this is what makes your show-up rate a number instead of a dash — and
                    a no-show starts the re-engagement follow-up.
                  </p>
                  <AttendanceControl
                    appointment={apt}
                    workspaceId={workspaceId}
                    onMarked={onChanged}
                  />
                </div>
              ) : null}
              <div className="grid gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <Clock className="size-4 text-muted-foreground" />
                  <span>{apt.duration_minutes} minutes</span>
                </div>
                {apt.service_type === "phone_call" ? (
                  <div className="flex items-center gap-2">
                    <Phone className="size-4 text-muted-foreground" />
                    <span>Phone call</span>
                  </div>
                ) : apt.service_type === "video_call" ? (
                  <div className="flex items-center gap-2">
                    <Video className="size-4 text-muted-foreground" />
                    <span>Video call</span>
                  </div>
                ) : null}
                {apt.meeting_url ? (
                  <Button variant="default" size="sm" asChild className="w-fit">
                    <a href={apt.meeting_url} target="_blank" rel="noreferrer">
                      <Video className="mr-2 size-4" />
                      Join Google Meet
                      <ExternalLink className="ml-2 size-3" />
                    </a>
                  </Button>
                ) : null}
                {apt.google_calendar_event_url ? (
                  <Button variant="outline" size="sm" asChild className="w-fit">
                    <a href={apt.google_calendar_event_url} target="_blank" rel="noreferrer">
                      <CalendarDays className="mr-2 size-4" />
                      Open in Google Calendar
                      <ExternalLink className="ml-2 size-3" />
                    </a>
                  </Button>
                ) : null}
                {apt.sync_status === "failed" || apt.sync_status === "not_connected" ? (
                  <div className="space-y-2 rounded-md border border-destructive/30 p-3">
                    <p className="text-xs text-destructive">
                      Google Calendar sync needs attention:{" "}
                      {apt.sync_error || "Connect the assigned rep’s calendar and retry."}
                    </p>
                    <Button variant="outline" size="sm" asChild className="w-fit">
                      <a href="/settings?tab=calendar">Connect or retry Google Calendar</a>
                    </Button>
                  </div>
                ) : null}
                {apt.notes && <div className="text-sm text-muted-foreground">{apt.notes}</div>}
              </div>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
