import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppointmentDetailsDialog } from "@/components/calendar/appointment-details-dialog";
import { appointmentsApi } from "@/lib/api/appointments";
import type { Appointment } from "@/types";

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => false }),
}));

vi.mock("@/components/calendar/appointment-actions", () => ({
  AttendanceControl: () => null,
  ReminderBadges: () => null,
  SendReminderButton: () => null,
  hasStarted: () => false,
}));

vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, appointmentsApi: { ...actual.appointmentsApi, update: vi.fn() } };
});

const appointment: Appointment = {
  id: 42,
  contact_id: 7,
  workspace_id: "workspace-1",
  scheduled_at: "2026-09-10T14:00:00.000Z",
  anytime: false,
  duration_minutes: 30,
  status: "scheduled",
  service_type: "Discovery call",
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-01T00:00:00.000Z",
};

describe("AppointmentDetailsDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(appointmentsApi.update).mockResolvedValue({ ...appointment, status: "completed" });
  });

  it("offers the requested statuses and marks a show", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <AppointmentDetailsDialog
          appointment={appointment}
          workspaceId="workspace-1"
          open
          onOpenChange={vi.fn()}
          onDelete={vi.fn()}
          onChanged={onChanged}
          deleting={false}
        />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("combobox", { name: "Update appointment status" }));
    expect(screen.getByRole("option", { name: "Show" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Cancelled" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Rescheduled" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "No-show" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: "Show" }));

    await waitFor(() => {
      expect(appointmentsApi.update).toHaveBeenCalledWith("workspace-1", 42, {
        status: "completed",
      });
    });
    expect(onChanged).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("combobox", { name: "Update appointment status" }));
    await user.click(screen.getByRole("option", { name: "Rescheduled" }));
    expect(screen.getByRole("button", { name: "Save new time" })).toBeInTheDocument();
  });
});
