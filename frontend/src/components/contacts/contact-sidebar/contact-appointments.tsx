"use client";

import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Calendar, Loader2, Bell } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { appointmentsApi } from "@/lib/api/appointments";
import { queryKeys } from "@/lib/query-keys";
import type { Appointment } from "@/types";

interface ContactAppointmentsProps {
  workspaceId: string | null | undefined;
  contactId: number;
  appointments: Appointment[];
  isLoading: boolean;
}

export function ContactAppointments({
  workspaceId,
  contactId,
  appointments,
  isLoading,
}: ContactAppointmentsProps) {
  const queryClient = useQueryClient();
  const [sendingReminderIds, setSendingReminderIds] = useState<Set<number>>(
    new Set(),
  );

  const handleSendReminder = async (appointmentId: number) => {
    if (!workspaceId) return;
    setSendingReminderIds((prev) => new Set(prev).add(appointmentId));
    try {
      const result = await appointmentsApi.sendReminder(
        workspaceId,
        appointmentId,
      );
      if (result.success) {
        toast.success(`Reminder sent to ${result.sent_to ?? "contact"}`);
        void queryClient.invalidateQueries({
          queryKey: queryKeys.appointments.byContact(workspaceId, contactId),
        });
      } else {
        toast.error(result.message || "Failed to send reminder");
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Failed to send reminder"));
    } finally {
      setSendingReminderIds((prev) => {
        const next = new Set(prev);
        next.delete(appointmentId);
        return next;
      });
    }
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground px-2">
        Appointments
      </h3>
      {isLoading ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      ) : appointments.length === 0 ? (
        <p className="text-xs text-muted-foreground px-2 py-2">
          No appointments scheduled
        </p>
      ) : (
        <div className="space-y-2 px-2">
          {appointments.slice(0, 3).map((apt) => (
            <div
              key={apt.id}
              className="flex items-center gap-2 p-2 rounded-lg bg-muted/30 text-xs"
            >
              <Calendar className="h-3 w-3 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">
                  {apt.service_type || "Appointment"}
                </p>
                <p className="text-muted-foreground text-xs">
                  {formatDate(apt.scheduled_at, { pattern: "MMM d, h:mm a" })}
                </p>
              </div>
              <Badge variant="outline" className="text-xs py-0">
                {apt.status}
              </Badge>
              {apt.status === "scheduled" && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  title="Send SMS reminder"
                  aria-label="Send SMS reminder"
                  disabled={sendingReminderIds.has(apt.id)}
                  onClick={() => void handleSendReminder(apt.id)}
                >
                  {sendingReminderIds.has(apt.id) ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Bell className="h-3 w-3" />
                  )}
                </Button>
              )}
            </div>
          ))}
          {appointments.length > 3 && (
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              asChild
            >
              <Link href="/calendar">View all ({appointments.length})</Link>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
