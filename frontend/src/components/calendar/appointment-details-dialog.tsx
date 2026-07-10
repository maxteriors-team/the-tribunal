"use client";

/**
 * Shared appointment-details dialog for the calendar screens.
 *
 * Extracted so the week grid and the month grid drive one controlled dialog
 * (keyed by the selected appointment id) instead of each rendering their own —
 * no duplicated 100-line dialog body, one place to evolve the detail view.
 */
import { Clock, Trash2 } from "lucide-react";

import {
  ReminderBadges,
  SendReminderButton,
  SyncButton,
} from "@/components/calendar/appointment-actions";
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
import { getContactName, getInitials } from "@/lib/calendar/calendar-derivations";
import { appointmentStatusColors } from "@/lib/status-colors";
import { formatDate } from "@/lib/utils/date";
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {apt ? (
          <>
            <DialogHeader>
              <DialogTitle>{apt.service_type || "Appointment"}</DialogTitle>
              <DialogDescription>
                {formatDate(apt.scheduled_at, {
                  pattern: "EEEE, MMMM d, yyyy 'at' h:mm a",
                })}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Avatar className="size-10">
                    <AvatarFallback>
                      {getInitials(
                        apt.contact?.first_name || "",
                        apt.contact?.last_name,
                      )}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <p className="font-medium">{getContactName(apt.contact)}</p>
                    <Badge
                      variant="outline"
                      className={appointmentStatusColors[apt.status]}
                    >
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
                  {workspaceId && (
                    <SyncButton
                      appointment={apt}
                      workspaceId={workspaceId}
                      onSynced={onChanged}
                    />
                  )}
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
              <div className="grid gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <Clock className="size-4 text-muted-foreground" />
                  <span>{apt.duration_minutes} minutes</span>
                </div>
                {apt.sync_status === "pending" && (
                  <div className="flex items-center gap-2 text-warning">
                    <span className="text-xs">Not synced to Cal.com</span>
                  </div>
                )}
                {apt.sync_status === "synced" && apt.calcom_booking_uid && (
                  <div className="text-xs text-muted-foreground">
                    Cal.com UID: {apt.calcom_booking_uid}
                  </div>
                )}
                {apt.sync_error && (
                  <div className="text-xs text-destructive">
                    Sync error: {apt.sync_error}
                  </div>
                )}
                {apt.notes && (
                  <div className="text-sm text-muted-foreground">{apt.notes}</div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
