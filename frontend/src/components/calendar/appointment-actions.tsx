"use client";

import { Bell, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
