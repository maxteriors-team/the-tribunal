"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { appointmentsApi } from "@/lib/api/appointments";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Appointment } from "@/types";

interface AppointmentEditFormProps {
  appointment: Appointment;
  workspaceId: string;
  rescheduling?: boolean;
  onCancel: () => void;
  onSaved: () => void;
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function localDateParts(value: string) {
  const date = new Date(value);
  return {
    date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  };
}

export function AppointmentEditForm({
  appointment,
  workspaceId,
  rescheduling = false,
  onCancel,
  onSaved,
}: AppointmentEditFormProps) {
  const initial = localDateParts(appointment.scheduled_at);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const [anytime, setAnytime] = useState(appointment.anytime);
  const [duration, setDuration] = useState(String(appointment.duration_minutes));
  const [serviceType, setServiceType] = useState(appointment.service_type ?? "");
  const [notes, setNotes] = useState(appointment.notes ?? "");

  const updateMutation = useMutation({
    mutationFn: () => {
      const scheduledAt = new Date(`${date}T${time || "09:00"}:00`);
      if (Number.isNaN(scheduledAt.getTime())) throw new Error("Choose a valid date and time");

      return appointmentsApi.update(workspaceId, appointment.id, {
        scheduled_at: scheduledAt.toISOString(),
        anytime,
        duration_minutes: Number(duration),
        service_type: serviceType.trim(),
        notes: notes.trim(),
        ...(rescheduling ? { status: "scheduled" as const } : {}),
      });
    },
    onSuccess: () => {
      toast.success(rescheduling ? "Appointment rescheduled" : "Appointment updated");
      onSaved();
    },
    onError: (error: unknown) => {
      toast.error(getApiErrorMessage(error, "Failed to update appointment"));
    },
  });

  return (
    <form
      className="space-y-4 py-4"
      onSubmit={(event) => {
        event.preventDefault();
        updateMutation.mutate();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="appointment-edit-date">Date</Label>
          <Input
            id="appointment-edit-date"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="appointment-edit-time">Time</Label>
          <Input
            id="appointment-edit-time"
            type="time"
            value={time}
            onChange={(event) => setTime(event.target.value)}
            disabled={anytime}
            required={!anytime}
          />
        </div>
      </div>

      <label htmlFor="appointment-edit-anytime" className="flex items-center gap-2 text-sm">
        <Checkbox
          id="appointment-edit-anytime"
          checked={anytime}
          onCheckedChange={(checked) => setAnytime(checked === true)}
        />
        Any time
      </label>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="appointment-edit-duration">Duration (minutes)</Label>
          <Input
            id="appointment-edit-duration"
            type="number"
            min={15}
            max={480}
            step={15}
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="appointment-edit-service">Service</Label>
          <Input
            id="appointment-edit-service"
            value={serviceType}
            maxLength={100}
            onChange={(event) => setServiceType(event.target.value)}
            placeholder="Discovery call"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="appointment-edit-notes">Notes</Label>
        <Textarea
          id="appointment-edit-notes"
          value={notes}
          maxLength={5000}
          onChange={(event) => setNotes(event.target.value)}
          rows={4}
        />
      </div>

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={updateMutation.isPending}
        >
          Back
        </Button>
        <Button type="submit" disabled={updateMutation.isPending}>
          {updateMutation.isPending ? "Saving…" : rescheduling ? "Save new time" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
