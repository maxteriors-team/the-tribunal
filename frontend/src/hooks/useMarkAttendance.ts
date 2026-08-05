"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { appointmentsApi } from "@/lib/api/appointments";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Appointment } from "@/types";

/** The two outcomes that decide a show-up rate. */
export type AttendanceOutcome = "completed" | "no_show";

interface UseMarkAttendanceOptions {
  workspaceId: string | null | undefined;
  /** Called after the backend confirms the change. */
  onSuccess?: (appointment: Appointment) => void;
}

interface MarkAttendanceVariables {
  appointmentId: number;
  outcome: AttendanceOutcome;
}

/** A cached appointment payload: either a paginated list or a single record. */
type AppointmentCache = { items: Appointment[] } | Appointment | undefined;

function isPaginated(value: AppointmentCache): value is { items: Appointment[] } {
  return typeof value === "object" && value !== null && "items" in value;
}

/**
 * Mark an appointment attended or absent.
 *
 * Until this shipped, `completed` / `no_show` were written by exactly one
 * thing — the Cal.com `meeting_ended` webhook — so a workspace booking by phone
 * had no way to record attendance and its show-up rate could only ever render
 * a dash. The backend applies the same contact-side effects for both writers
 * (`app/services/appointments/attendance.py`), so an in-app no-show reaches the
 * `no_show` automation trigger and the re-engagement worker.
 *
 * Updates optimistically across every cached appointments query for the
 * workspace and rolls the exact previous snapshots back if the request fails,
 * so a failed marking never leaves a wrong status on screen.
 */
export function useMarkAttendance({
  workspaceId,
  onSuccess,
}: UseMarkAttendanceOptions) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ appointmentId, outcome }: MarkAttendanceVariables) => {
      if (!workspaceId) throw new Error(messages.workspace.notLoaded);
      return appointmentsApi.update(workspaceId, appointmentId, { status: outcome });
    },
    onMutate: async ({ appointmentId, outcome }) => {
      if (!workspaceId) return { snapshots: [] };
      const queryKey = queryKeys.appointments.all(workspaceId);

      // Stop in-flight refetches from overwriting the optimistic value.
      await queryClient.cancelQueries({ queryKey });
      const snapshots = queryClient.getQueriesData<AppointmentCache>({ queryKey });

      queryClient.setQueriesData<AppointmentCache>({ queryKey }, (cached) => {
        if (!cached) return cached;
        if (isPaginated(cached)) {
          return {
            ...cached,
            items: cached.items.map((item) =>
              item.id === appointmentId ? { ...item, status: outcome } : item,
            ),
          };
        }
        return cached.id === appointmentId ? { ...cached, status: outcome } : cached;
      });

      return { snapshots };
    },
    onError: (error, _variables, context) => {
      for (const [key, snapshot] of context?.snapshots ?? []) {
        queryClient.setQueryData(key, snapshot);
      }
      toast.error(getApiErrorMessage(error, messages.appointments.attendanceFailed));
    },
    onSuccess: (appointment, { outcome }) => {
      toast.success(
        outcome === "completed"
          ? messages.appointments.markedAttended
          : messages.appointments.markedNoShow,
      );
      onSuccess?.(appointment);
    },
    onSettled: () => {
      if (!workspaceId) return;
      // The contact's tags and no-show counter changed too, so refresh both
      // trees rather than trusting the optimistic patch.
      queryClient.invalidateQueries({
        queryKey: queryKeys.appointments.all(workspaceId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.all(workspaceId),
      });
    },
  });
}
