"use client";

import { Bell, Loader2, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useMarkAttendance, type AttendanceOutcome } from "@/hooks/useMarkAttendance";
import { appointmentsApi } from "@/lib/api/appointments";
import { offsetToLabel } from "@/lib/calendar/calendar-derivations";
import type { Appointment } from "@/types";

interface ReminderBadgesProps {
  reminderSentAt?: string | null;
  remindersSent?: number[] | null;
  reminderOffsets?: number[] | null;
}

export function ReminderBadges({
  reminderSentAt,
  remindersSent,
  reminderOffsets,
}: ReminderBadgesProps) {
  const sent = remindersSent ?? [];

  // If we have reminder offsets (from agent data on appointment), show multi-badge
  if (reminderOffsets && reminderOffsets.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
        {reminderOffsets.map((offset) => {
          const fired = sent.includes(offset);
          return (
            <Badge
              key={offset}
              variant="outline"
              className={
                fired
                  ? "text-success border-success/20 text-[10px] py-0"
                  : "text-muted-foreground border-muted text-[10px] py-0"
              }
            >
              {offsetToLabel(offset)}
              {fired ? " ✓" : ""}
            </Badge>
          );
        })}
      </div>
    );
  }

  // If we have fired reminders but no offset config, show fired ones
  if (sent.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
        {sent.map((offset) => (
          <Badge
            key={offset}
            variant="outline"
            className="text-success border-success/20 text-[10px] py-0"
          >
            {offsetToLabel(offset)} ✓
          </Badge>
        ))}
      </div>
    );
  }

  // Legacy fallback: just reminder_sent_at set
  if (reminderSentAt) {
    return (
      <Badge variant="outline" className="text-success border-success/20 text-[10px] py-0">
        Reminder sent
      </Badge>
    );
  }

  return null;
}

interface SendReminderButtonProps {
  appointment: Appointment;
  workspaceId: string;
  onSent: () => void;
}

export function SendReminderButton({
  appointment,
  workspaceId,
  onSent,
}: SendReminderButtonProps) {
  const [isSending, setIsSending] = useState(false);

  if (appointment.status !== "scheduled") return null;

  const handleSend = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsSending(true);
    try {
      const result = await appointmentsApi.sendReminder(workspaceId, appointment.id);
      if (result.success) {
        toast.success(`Reminder sent to ${result.sent_to ?? "contact"}`);
        onSent();
      } else {
        toast.error(result.message || "Failed to send reminder");
      }
    } catch {
      toast.error("Failed to send reminder");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="text-xs h-7 gap-1"
      onClick={handleSend}
      disabled={isSending}
      title="Send SMS reminder"
    >
      {isSending ? (
        <Loader2 className="size-3 animate-spin" />
      ) : (
        <Bell className="size-3" />
      )}
      Remind
    </Button>
  );
}

/** True once the appointment's slot has started, so attendance is knowable. */
export function hasStarted(scheduledAt: string, now: Date = new Date()): boolean {
  const start = new Date(scheduledAt).getTime();
  return Number.isFinite(start) && start <= now.getTime();
}

interface AttendanceControlProps {
  appointment: Appointment;
  workspaceId: string;
  onMarked?: () => void;
}

/**
 * "Attended / No-show" for an appointment whose slot has passed.
 *
 * Show-up rate is the one funnel number a CRM cannot infer, and until this
 * shipped nothing outside the Cal.com webhook could write it — a workspace
 * booking by phone saw a permanent dash. Deliberately not auto-resolved after N
 * hours: assuming attendance would manufacture a 100% show-up rate, which is
 * worse than no number at all.
 */
export function AttendanceControl({
  appointment,
  workspaceId,
  onMarked,
}: AttendanceControlProps) {
  const markAttendance = useMarkAttendance({ workspaceId, onSuccess: onMarked });

  if (!hasStarted(appointment.scheduled_at)) return null;
  if (appointment.status === "cancelled") return null;

  const pendingOutcome = markAttendance.isPending
    ? markAttendance.variables?.outcome
    : undefined;

  const mark = (outcome: AttendanceOutcome) => (event: React.MouseEvent) => {
    event.stopPropagation();
    markAttendance.mutate({ appointmentId: appointment.id, outcome });
  };

  const buttons: {
    outcome: AttendanceOutcome;
    label: string;
    icon: typeof UserCheck;
    activeClass: string;
  }[] = [
    {
      outcome: "completed",
      label: "Attended",
      icon: UserCheck,
      activeClass: "border-success/40 bg-success/10 text-success",
    },
    {
      outcome: "no_show",
      label: "No-show",
      icon: UserX,
      activeClass: "border-destructive/40 bg-destructive/10 text-destructive",
    },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2">
      {buttons.map(({ outcome, label, icon: Icon, activeClass }) => {
        const isCurrent = appointment.status === outcome;
        return (
          <Button
            key={outcome}
            variant="outline"
            size="sm"
            className={`h-7 gap-1 text-xs ${isCurrent ? activeClass : ""}`}
            onClick={mark(outcome)}
            disabled={markAttendance.isPending || isCurrent}
            aria-pressed={isCurrent}
          >
            {pendingOutcome === outcome ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Icon className="size-3" />
            )}
            {label}
          </Button>
        );
      })}
    </div>
  );
}
